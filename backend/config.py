"""Runtime configuration, read from environment variables or a .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR / "backend" / ".env"),
        env_prefix="LUMINA_",
        extra="ignore",
        populate_by_name=True,
    )

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")

    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
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
