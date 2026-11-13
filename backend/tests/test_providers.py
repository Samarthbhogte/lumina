import httpx
import numpy as np
import openai
import pytest
from google.genai import errors as genai_errors
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_google_genai._common import GoogleGenerativeAIError

from backend.config import Settings
from backend.pdf import Page
from backend.providers import UnitEmbeddings, build_models, classify
from backend.store import DocumentStore


def test_gemini_defaults_and_key_aliases(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    s = Settings(data_dir=tmp_path, provider="gemini", _env_file=None)
    assert s.api_key == "g-key" and s.api_key_name == "GOOGLE_API_KEY"
    assert s.chat_model == "gemini-2.5-flash" and s.embedding_model == "gemini-embedding-001"
    assert s.embedding_id == "gemini:gemini-embedding-001"
    assert s.provider_label == "Gemini"


def test_explicit_model_overrides_provider_default(tmp_path):
    s = Settings(data_dir=tmp_path, provider="gemini", chat_model="gemini-flash-lite-latest", _env_file=None)
    assert s.chat_model == "gemini-flash-lite-latest"


def test_build_models_gemini_offline(tmp_path):
    s = Settings(data_dir=tmp_path, provider="gemini", google_api_key="g-key", _env_file=None)
    emb, chat = build_models(s)
    assert isinstance(emb, UnitEmbeddings) and isinstance(emb.inner, GoogleGenerativeAIEmbeddings)
    assert isinstance(chat, ChatGoogleGenerativeAI) and chat.model.endswith("gemini-2.5-flash")
    assert chat.thinking_budget == 0


def test_build_models_without_key(tmp_path):
    assert build_models(Settings(data_dir=tmp_path, provider="gemini", _env_file=None)) == (None, None)


def _genai_error(code: int) -> genai_errors.ClientError:
    return genai_errors.ClientError(code, {"error": {"code": code, "status": "X", "message": "m"}})


@pytest.mark.parametrize("code,kind", [(401, "auth"), (403, "auth"), (429, "rate"), (400, "provider")])
def test_classify_gemini_errors_through_wrapper(code, kind):
    try:
        try:
            raise _genai_error(code)
        except genai_errors.ClientError as inner:
            raise GoogleGenerativeAIError("Error embedding content") from inner
    except GoogleGenerativeAIError as wrapped:
        assert classify(wrapped) == kind


def test_classify_openai_and_unrelated_errors():
    req = httpx.Request("POST", "https://api.openai.com/v1/x")
    assert classify(openai.AuthenticationError("k", response=httpx.Response(401, request=req), body=None)) == "auth"
    assert classify(openai.RateLimitError("r", response=httpx.Response(429, request=req), body=None)) == "rate"
    assert classify(ValueError("bug")) is None


def test_unit_embeddings_are_normalised():
    emb = UnitEmbeddings(DeterministicFakeEmbedding(size=32))
    vecs = np.array(emb.embed_documents(["a", "b"]) + [emb.embed_query("c")])
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-5)


def test_switching_embedding_model_reindexes(tmp_path):
    from backend.tests.conftest import make_pdf

    pdf = make_pdf("Retention is 30 days.")
    store = DocumentStore(tmp_path, DeterministicFakeEmbedding(size=16), embedding_id="openai:small")
    store.add("gdpr.pdf", pdf, [Page(1, "Retention is 30 days.")])
    # Same documents, new provider with a different vector size.
    switched = DocumentStore(tmp_path, DeterministicFakeEmbedding(size=48), embedding_id="gemini:emb")
    hits = switched.search("retention")
    assert hits and hits[0].filename == "gdpr.pdf"
    assert switched._index.index.d == 48
    import json

    assert json.loads((tmp_path / "documents.json").read_text())["embedding_id"] == "gemini:emb"


def test_gemini_auth_error_maps_to_502(tmp_path):
    from fastapi.testclient import TestClient
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    from backend.main import create_app
    from backend.tests.conftest import make_pdf, upload

    class Rejecting(GenericFakeChatModel):
        def _generate(self, *args, **kwargs):
            raise GoogleGenerativeAIError("bad key") from _genai_error(403)

    settings = Settings(data_dir=tmp_path, provider="gemini", google_api_key="g", _env_file=None)
    app = create_app(settings, embeddings=DeterministicFakeEmbedding(size=16), llm=Rejecting(messages=iter([])))
    with TestClient(app) as c:
        upload(c, "a.pdf", make_pdf("Retention is 30 days."))
        res = c.post("/api/ask", json={"question": "How long is data kept?"})
    assert res.status_code == 502 and res.json()["detail"] == "Gemini rejected the API key."
