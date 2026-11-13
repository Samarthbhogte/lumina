"""Runtime configuration, read from environment variables or a .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent

Provider = Literal["openai", "gemini"]

# Per-provider defaults. Confidence thresholds are cosine-similarity cut-offs for the cited
# passages; each embedding model spreads scores differently, so they are tuned per model.
DEFAULTS: dict[str, dict] = {
    "openai": {
        "label": "OpenAI",
        "chat_model": "gpt-4o-mini",
        "fallback_models": "",
        "embedding_model": "text-embedding-3-small",
        "confidence_high": 0.55,
        "confidence_medium": 0.40,
    },
    "gemini": {
        "label": "Gemini",
        "chat_model": "gemini-2.5-flash",
        # Each free-tier model has its own daily request quota; when one runs out the
        # next is tried, which roughly triples the free questions per day.
        "fallback_models": "gemini-3.5-flash-lite,gemini-3.1-flash-lite",
        "embedding_model": "gemini-embedding-001",
        # From the golden-set eval (backend/tests/eval, section chunks): correct passages scored
        # 0.68-0.80 (median 0.74); best passages for out-of-scope questions 0.55-0.64.
        "confidence_high": 0.70,
        "confidence_medium": 0.64,
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR / "backend" / ".env"),
        env_prefix="LUMINA_",
        extra="ignore",
        populate_by_name=True,
    )

    # Which AI provider answers questions and embeds documents.
    provider: Provider = "openai"
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    google_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"))

    # Left empty, these take the provider's defaults above.
    chat_model: str = ""
    # Comma-separated models to try, in order, when the chat model is rate-limited.
    # Unset uses the provider default; set to "none" to disable.
    fallback_models: str = ""
    embedding_model: str = ""
    confidence_high: float = 0.0
    confidence_medium: float = 0.0
    temperature: float = 0.1

    data_dir: Path = ROOT_DIR / "data"
    # Comma-separated list of origins allowed to call the API from a browser.
    cors_origins: str = "http://localhost:3000"

    max_upload_mb: int = 25
    max_files_per_upload: int = 10
    max_pages: int = 1000
    max_chunks_per_document: int = 4000
    chunk_size: int = 1000
    chunk_overlap: int = 150

    top_k: int = 6
    max_context_chars: int = 14000
    max_history_messages: int = 8

    # Interactive API docs at /docs. Turn off when the API is reachable beyond your machine.
    enable_docs: bool = True

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, v: str) -> str:
        if "*" in v:
            raise ValueError("LUMINA_CORS_ORIGINS must list explicit origins, not '*'.")
        return v

    @model_validator(mode="after")
    def _apply_provider_defaults(self) -> "Settings":
        d = DEFAULTS[self.provider]
        self.chat_model = self.chat_model or d["chat_model"]
        self.fallback_models = self.fallback_models or d["fallback_models"]
        self.embedding_model = self.embedding_model or d["embedding_model"]
        self.confidence_high = self.confidence_high or d["confidence_high"]
        self.confidence_medium = self.confidence_medium or d["confidence_medium"]
        return self

    @property
    def fallback_model_list(self) -> list[str]:
        if self.fallback_models.strip().lower() == "none":
            return []
        models = [m.strip() for m in self.fallback_models.split(",") if m.strip()]
        return [m for m in models if m != self.chat_model]

    @property
    def provider_label(self) -> str:
        return DEFAULTS[self.provider]["label"]

    @property
    def api_key(self) -> str | None:
        return self.openai_api_key if self.provider == "openai" else self.google_api_key

    @property
    def api_key_name(self) -> str:
        return "OPENAI_API_KEY" if self.provider == "openai" else "GOOGLE_API_KEY"

    @property
    def embedding_id(self) -> str:
        """Identifies the vector space; the index is rebuilt when this changes."""
        return f"{self.provider}:{self.embedding_model}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_request_bytes(self) -> int:
        # Whole multipart request: every file at the limit, plus form overhead.
        return self.max_upload_bytes * self.max_files_per_upload + 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
