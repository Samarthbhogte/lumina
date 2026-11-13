"""Policy-vs-regulation gap check."""

import json

from langchain_core.embeddings import DeterministicFakeEmbedding

from backend.config import Settings
from backend.main import create_app
from backend.tests.conftest import connect, make_pdf, upload

REGULATION = (
    "Sample Regulation\n1. Security\n1.1 Personal data must be encrypted at rest.\n"
    "1.2 Access to personal data must be logged.\n2. Breach\n2.1 Breaches must be reported within 72 hours.\n"
    "3. Other\n3.1 Records are kept."
)
POLICY = "Our policy. We encrypt all personal data at rest using AES-256, and we review access monthly."

VERDICTS = [
    dict(id="1.1", status="addressed", source=1, quote="encrypt all personal data at rest", rationale="Encryption."),
    dict(id="1.2", status="partial", source=1, quote="we log every access in real time", rationale="Reviews."),
    dict(id="2.1", status="not_addressed", source=None, quote="", rationale="No breach timeline."),
    dict(id="3.1", status="addressed", source=1, quote="", rationale="No quote given."),
]


def _setup(tmp_path, fake_llm, **overrides):
    settings = Settings(data_dir=tmp_path, openai_api_key="k", confidence_medium=-1e9, **overrides)
    fake_llm.answers = [json.dumps(VERDICTS)]
    return create_app(settings, embeddings=DeterministicFakeEmbedding(size=32), llm=fake_llm.model())


def _ids(c):
    reg = upload(c, "Regulation.pdf", make_pdf(REGULATION)).json()["results"][0]["document"]["id"]
    pol = upload(c, "Policy.pdf", make_pdf(POLICY)).json()["results"][0]["document"]["id"]
    return {"requirements_document_id": reg, "policy_document_id": pol}


def test_estimate_counts_requirements_and_ai_requests(tmp_path, fake_llm):
    with connect(_setup(tmp_path, fake_llm)) as c:
        est = c.post("/w/comparisons/estimate", json=_ids(c)).json()
        assert est["requirements"] == 4 and est["max_ai_requests"] == 1
        assert est["questions_left_today"] == 25


def test_gap_check_classifies_and_verifies_quotes(tmp_path, fake_llm):
    with connect(_setup(tmp_path, fake_llm)) as c:
        res = c.post("/w/comparisons", json=_ids(c))
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["status"] == "done"
        status = {r["requirement"]["id"]: r["status"] for r in body["rows"]}
        assert status == {"1.1": "addressed", "1.2": "needs_review", "2.1": "not_found", "3.1": "needs_review"}
        assert body["summary"]["headline"] == "1 of 4 requirements have a matching passage"
        first = body["rows"][0]
        assert first["requirement"]["text"].startswith("Personal data must be encrypted")
        assert first["match"]["label"].startswith("Policy") and "encrypt" in first["match"]["excerpt"]
        assert len(fake_llm.calls) == 1  # four requirements, one AI request
        assert c.get("/api/auth/me").json()["questions_used_today"] == 2  # retrieval + one AI batch
        listed = c.get("/w/comparisons").json()
        assert listed[0]["title"] == "Policy.pdf vs Regulation.pdf" and "rows" not in listed[0]


def test_weak_matches_skip_the_model(tmp_path, fake_llm):
    with connect(_setup(tmp_path, fake_llm, confidence_high=1e9)) as c:
        c.app.state.settings.confidence_medium = 1e9  # nothing is close enough
        body = c.post("/w/comparisons", json=_ids(c)).json()
        assert {r["status"] for r in body["rows"]} == {"not_found"} and fake_llm.calls == []


def test_quota_stop_is_saved_and_resumable(tmp_path, fake_llm):
    with connect(_setup(tmp_path, fake_llm, daily_questions_per_user=1)) as c:
        body = c.post("/w/comparisons", json=_ids(c)).json()  # retrieval uses the only question
        assert body["status"] == "partial" and "used your 1 questions" in body["note"]
        c.app.state.settings.daily_questions_per_user = 5
        resumed = c.post(f"/w/comparisons/{body['id']}/resume").json()
        assert resumed["status"] == "done" and len(resumed["rows"]) == 4


def test_same_document_and_unstructured_requirements_are_rejected(tmp_path, fake_llm):
    with connect(_setup(tmp_path, fake_llm)) as c:
        ids = _ids(c)
        pol, reg = ids["policy_document_id"], ids["requirements_document_id"]
        same = {"requirements_document_id": pol, "policy_document_id": pol}
        assert c.post("/w/comparisons", json=same).status_code == 400
        flipped = {"requirements_document_id": pol, "policy_document_id": reg}
        assert c.post("/w/comparisons", json=flipped).status_code == 422  # policy text has no numbered clauses


def test_embedding_rate_limit_during_retrieval_is_resumable(tmp_path, fake_llm, monkeypatch):
    from langchain_core.exceptions import ModelRateLimitError

    from backend import compare

    with connect(_setup(tmp_path, fake_llm)) as c:
        ids = _ids(c)
        real, calls = compare.retrieve, {"n": 0}

        def flaky(store, req, policy_id):
            calls["n"] += 1
            if calls["n"] == 3:
                raise ModelRateLimitError("429 per minute. Please retry in 20s.")
            return real(store, req, policy_id)

        monkeypatch.setattr(compare, "retrieve", flaky)
        body = c.post("/w/comparisons", json=ids).json()
        assert body["status"] == "partial" and "rate limit" in body["note"] and len(body["rows"]) == 2
        resumed = c.post(f"/w/comparisons/{body['id']}/resume").json()
        assert resumed["status"] == "done" and len(resumed["rows"]) == 4


def test_viewers_cannot_run_gap_checks_and_zero_quota_is_refused(tmp_path, fake_llm):
    from backend.tests.conftest import WsClient

    app = _setup(tmp_path, fake_llm)
    with connect(app) as owner, WsClient(app) as viewer:
        ws = owner.post("/api/workspaces", json={"name": "T"}).json()["id"]
        link = owner.post(f"/api/workspaces/{ws}/invites", json={"role": "viewer"}).json()["link"]
        viewer.sign_in("v@example.com", "V", invite=link.rsplit("/", 1)[-1])
        owner.ws = ws
        ids = _ids(owner)
        assert viewer.post(f"/api/workspaces/{ws}/comparisons", json=ids).status_code == 403
        app.state.settings.daily_questions_per_user = 0
        assert owner.post(f"/api/workspaces/{ws}/comparisons", json=ids).status_code == 429
