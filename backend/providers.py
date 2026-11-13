"""Build the chat and embedding models for the configured provider, and classify their errors."""

import re
from typing import Literal

import numpy as np
from langchain_core.embeddings import Embeddings
from langchain_core.exceptions import ModelAuthenticationError, ModelRateLimitError
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

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


def _gemini_thinking(model: str) -> dict:
    """Grounded Q&A over short passages doesn't need long reasoning, and extended "thinking"
    can push a free-tier request past Google's 60 s deadline. Keep it off or low."""
    if model.startswith("gemini-2.5"):
        return {"thinking_budget": 0}
    if model.startswith("gemini-3"):
        return {"thinking_level": "low"}
    return {}


def _chat_model(settings: Settings, model: str, key: str) -> BaseChatModel:
    if settings.provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=key,
            temperature=settings.temperature,
            max_retries=1,  # quota errors don't clear in seconds; fall back instead
            timeout=60,
            **_gemini_thinking(model),
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, temperature=settings.temperature, api_key=key, max_retries=2, timeout=60)


def build_models(settings: Settings) -> tuple[Embeddings | None, Runnable | None]:
    """Return (embeddings, chat model), or (None, None) when the provider's key is missing.

    The chat model falls back to settings.fallback_model_list, in order, when it is rate-limited.
    LangChain's fallbacks also cover streaming: a model that fails before its first token
    (which is when quota errors arrive) hands the request to the next one.
    """
    key = settings.api_key
    if not key:
        return None, None

    if settings.provider == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        embeddings: Embeddings = GoogleGenerativeAIEmbeddings(model=settings.embedding_model, google_api_key=key)
    else:
        from langchain_openai import OpenAIEmbeddings

        embeddings = OpenAIEmbeddings(model=settings.embedding_model, api_key=key)

    chat: Runnable = _chat_model(settings, settings.chat_model, key)
    fallbacks = [_chat_model(settings, m, key) for m in settings.fallback_model_list]
    if fallbacks:
        chat = chat.with_fallbacks(fallbacks, exceptions_to_handle=(ModelRateLimitError,))
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


_RETRY_IN = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.IGNORECASE)


def rate_limit_message(exc: BaseException, label: str) -> str:
    """User-facing text for a rate-limit error, saying when a daily quota resets."""
    text = ""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text += f" {current}"
        current = current.__cause__ or current.__context__
    daily = "PerDay" in text or "per day" in text.lower()
    wait = ""
    if (m := _RETRY_IN.search(text)) and any(m.groups()):
        hours, minutes = int(m.group(1) or 0), int(m.group(2) or 0)
        if hours:
            wait = f" It resets in about {hours} h {minutes} min."
        elif minutes:
            wait = f" Try again in about {minutes} min."
        else:
            wait = " Try again in a minute."
    if daily:
        return f"{label}'s free daily request limit is used up.{wait or ' It resets within 24 hours.'}"
    return f"{label} rate limit reached.{wait or ' Try again shortly.'}"
