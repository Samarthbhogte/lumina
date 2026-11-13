import itertools
import os
from contextlib import contextmanager

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from backend.config import Settings
from backend.main import create_app


def make_pdf(*pages: str) -> bytes:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(fitz.Rect(72, 72, 540, 770), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


class FakeLLM:
    """Hands out scripted answers and records the prompts it was given."""

    def __init__(self):
        self.answers = ["Personal data must be deleted within 30 days [1]."]
        self.calls: list[list] = []

    def model(self) -> GenericFakeChatModel:
        owner = self

        def messages():
            for i in itertools.count():
                yield AIMessage(owner.answers[min(i, len(owner.answers) - 1)])

        class Recording(GenericFakeChatModel):
            def _generate(self, messages, *args, **kwargs):
                owner.calls.append(messages)
                return super()._generate(messages, *args, **kwargs)

            def _stream(self, messages, *args, **kwargs):
                owner.calls.append(messages)
                yield from super()._stream(messages, *args, **kwargs)

        return Recording(messages=messages())


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """Tests must not see the developer's backend/.env or shell variables."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.startswith("LUMINA_") or name in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(name)


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, openai_api_key="test-key")


PASSWORD = "four random words make a passphrase"


class WsClient(TestClient):
    """A signed-in test client. Paths starting with /w/ go to the user's personal workspace,
    and every request carries the CSRF header the browser app sends."""

    ws: str = ""

    def _map(self, url):
        text = str(url)
        for prefix in ("/w/", "http://testserver/w/"):
            if text.startswith(prefix):
                return text.replace("/w/", f"/api/workspaces/{self.ws}/", 1)
        return url

    def request(self, method, url, *args, **kwargs):
        return super().request(method, self._map(url), *args, **kwargs)

    def build_request(self, method, url, *args, **kwargs):  # used by both request() and stream()
        url = self._map(url)
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("X-Lumina-CSRF", "1")
        return super().build_request(method, url, *args, headers=headers, **kwargs)

    def sign_in(self, email: str = "admin@example.com", name: str = "Admin", invite: str | None = None) -> dict:
        res = self.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        if res.status_code == 401:
            body = {"email": email, "password": PASSWORD, "display_name": name, "invite_token": invite}
            res = self.post("/api/auth/signup", json=body)
        assert res.status_code == 200, res.text
        me = res.json()
        self.ws = next(w["id"] for w in me["workspaces"] if w["kind"] == "personal")
        return me


@contextmanager
def connect(app, email: str = "admin@example.com"):
    """Start the app and return a client signed in as `email` (signing up if needed)."""
    with WsClient(app) as c:
        c.sign_in(email)
        yield c


@pytest.fixture
def client(settings, fake_llm):
    app = create_app(settings, embeddings=DeterministicFakeEmbedding(size=64), llm=fake_llm.model())
    with connect(app) as c:
        yield c


@pytest.fixture
def gdpr_pdf() -> bytes:
    return make_pdf(
        "GDPR Policy. Section 1: Scope. This policy covers customer personal data.",
        "Section 4: Retention. Personal data must be deleted within 30 days of account closure.",
    )


def upload(client, name: str, data: bytes):
    return client.post("/w/documents", files=[("files", (name, data, "application/pdf"))])
