"""Build the chat and embedding models for the configured provider, and classify their errors."""

from typing import Literal

import numpy as np
from langchain_core.embeddings import Embeddings
from langchain_core.exceptions import ModelAuthenticationError, ModelRateLimitError
from langchain_core.language_models import BaseChatModel

from backend.config import Settings

ErrorKind = Literal["auth", "rate", "provider"]


def _provider_error_types() -> tuple[type[BaseException], ...]:
    import openai
    from google.genai import errors as genai_errors
    from langchain_core.exceptions import ModelError
    from langchain_google_genai._common import GoogleGenerativeAIError

    return (ModelError, openai.APIError, genai_errors.APIError, GoogleGenerativeAIError)


# Exceptions the app maps to clean 502/503 responses (see main.py).
PROVIDER_ERRORS = _provider_error_types()


class UnitEmbeddings(Embeddings):
    """Scales every vector to length 1, so FAISS inner product is cosine similarity for any model."""

    def __init__(self, inner: Embeddings):
        self.inner = inner

    @staticmethod
    def _unit(vectors: list[list[float]]) -> list[list[float]]:
        arr = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return (arr / np.where(norms == 0, 1, norms)).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._unit(self.inner.embed_documents(texts))

    def embed_query(self, text: str) -> list[float]:
        return self._unit([self.inner.embed_query(text)])[0]


def build_models(settings: Settings) -> tuple[Embeddings | None, BaseChatModel | None]:
    """Return (embeddings, chat model), or (None, None) when the provider's key is missing."""
    key = settings.api_key
    if not key:
        return None, None

    if settings.provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

        embeddings: Embeddings = GoogleGenerativeAIEmbeddings(model=settings.embedding_model, google_api_key=key)
        chat: BaseChatModel = ChatGoogleGenerativeAI(
            model=settings.chat_model,
            google_api_key=key,
            temperature=settings.temperature,
            max_retries=2,
            timeout=60,
        )
    else:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings

        embeddings = OpenAIEmbeddings(model=settings.embedding_model, api_key=key)
        chat = ChatOpenAI(
            model=settings.chat_model,
            temperature=settings.temperature,
            api_key=key,
            max_retries=2,
            timeout=60,
        )
    return UnitEmbeddings(embeddings), chat


def _status(exc: BaseException) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def classify(exc: BaseException) -> ErrorKind | None:
    """Auth, rate limit, other provider failure, or None if this isn't a provider error at all.

    Walks the exception chain, since integrations often wrap the SDK's error.
    """
    seen: set[int] = set()
    kind: ErrorKind | None = None
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ModelAuthenticationError):
            return "auth"
        if isinstance(current, ModelRateLimitError):
            return "rate"
        module = type(current).__module__
        if module.startswith(("openai", "google", "langchain_google_genai", "langchain_openai")):
            status = _status(current)
            if status in (401, 403):
                return "auth"
            if status == 429:
                return "rate"
            kind = "provider"
        current = current.__cause__ or current.__context__
    return kind
