import itertools

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


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, openai_api_key="test-key")


@pytest.fixture
def client(settings, fake_llm):
    app = create_app(settings, embeddings=DeterministicFakeEmbedding(size=64), llm=fake_llm.model())
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gdpr_pdf() -> bytes:
    return make_pdf(
        "GDPR Policy. Section 1: Scope. This policy covers customer personal data.",
        "Section 4: Retention. Personal data must be deleted within 30 days of account closure.",
    )


def upload(client, name: str, data: bytes):
    return client.post("/api/documents", files=[("files", (name, data, "application/pdf"))])
