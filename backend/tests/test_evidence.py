"""Evidence packs and the document version log."""

import json

import pymupdf
import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from backend.evidence import HASH_PREFIX, verify_pack
from backend.main import create_app
from backend.tests.conftest import WsClient, connect, make_pdf, upload

POLICY = (
    "Breach Policy\n7. Breach Notification\n7.1 Incidents are triaged and documented.\n"
    "7.2 Notices to authorities follow statutory timelines.\n8. Transfers\n8.1 SCCs are required.\n9. Other\n9.1 None."
)


@pytest.fixture
def app(settings, fake_llm):
    fake_llm.answers = ["Notices to authorities follow statutory timelines [1]."]
    return create_app(settings, embeddings=DeterministicFakeEmbedding(size=32), llm=fake_llm.model())


def _answer(c: WsClient) -> dict:
    upload(c, "Breach_Policy.pdf", make_pdf(POLICY))
    return c.post("/w/ask", json={"question": "When are authorities notified?"}).json()


def test_answer_export_is_a_verifiable_pdf(app):
    with connect(app) as c:
        body = _answer(c)
        res = c.get(f"/w/answers/{body['message_id']}/export")
        assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
        assert "attachment" in res.headers["content-disposition"]
        valid, message, record = verify_pack(res.content)
        assert valid, message
        entry = record["answers"][0]
        assert entry["question"] == "When are authorities notified?"
        assert entry["answer"].startswith("Notices to authorities")
        cited = [s for s in entry["sources"] if s["cited"]]
        assert cited and cited[0]["excerpt"] and len(cited[0]["document_sha256"]) == 64
        assert record["exported_by"]["email"] == "admin@example.com"
        text = "".join(p.get_text() for p in pymupdf.open("pdf", res.content))
        assert "Lumina evidence pack" in text and "Cited passages" in text and "statutory timelines" in text


def test_tampering_is_detected(app):
    with connect(app) as c:
        pack = c.get(f"/w/answers/{_answer(c)['message_id']}/export").content
    doc = pymupdf.open("pdf", pack)
    record = json.loads(doc.embfile_get("evidence.json"))
    record["answers"][0]["answer"] = "You are fully compliant."
    doc.embfile_del("evidence.json")  # (embfile_upd is broken in PyMuPDF 2.1)
    doc.embfile_add("evidence.json", json.dumps(record).encode())
    valid, message, _ = verify_pack(doc.tobytes())
    assert not valid and "Modified" in message
    plain = pymupdf.open()
    plain.new_page()
    assert verify_pack(plain.tobytes())[0] is False


def test_conversation_export_and_verify_endpoint(app):
    with connect(app) as c:
        first = _answer(c)
        c.post("/w/ask", json={"question": "And transfers?", "conversation_id": first["conversation_id"]})
        pack = c.get(f"/w/conversations/{first['conversation_id']}/export")
        assert pack.status_code == 200
        res = c.post("/api/evidence/verify", files=[("file", ("p.pdf", pack.content, "application/pdf"))]).json()
        assert res["valid"] is True and res["answers"] == 2
        assert pymupdf.open("pdf", pack.content).metadata["keywords"].startswith(HASH_PREFIX)


def test_others_cannot_export_your_answers(app):
    with connect(app) as alice, WsClient(app) as bob:
        ws = alice.post("/api/workspaces", json={"name": "Team"}).json()["id"]
        link = alice.post(f"/api/workspaces/{ws}/invites", json={"role": "viewer"}).json()["link"]
        bob.sign_in("bob@example.com", "Bob", invite=link.rsplit("/", 1)[-1])
        alice.post(f"/api/workspaces/{ws}/documents", files=[("files", ("B.pdf", make_pdf(POLICY), "application/pdf"))])
        answer = alice.post(f"/api/workspaces/{ws}/ask", json={"question": "When are authorities notified?"}).json()
        assert bob.get(f"/api/workspaces/{ws}/answers/{answer['message_id']}/export").status_code == 404
        assert bob.get(f"/api/workspaces/{alice.ws}/answers/{answer['message_id']}/export").status_code == 404


def test_document_history_records_versions(app):
    with connect(app) as c:
        doc = upload(c, "Breach_Policy.pdf", make_pdf(POLICY)).json()["results"][0]["document"]
        c.delete(f"/w/documents/{doc['id']}")
        history = c.get("/w/documents/history").json()
        assert [h["event"] for h in history] == ["deleted", "uploaded"]
        assert history[1]["filename"] == "Breach_Policy.pdf" and len(history[1]["sha256"]) == 64
        assert history[1]["by"] == "Admin"
        assert c.get("/api/auth/me").status_code == 200
