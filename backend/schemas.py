"""Request and response models shared by the API and the frontend."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Confidence = Literal["high", "medium", "low"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)
    # Restrict retrieval to these documents. None or empty means search everything.
    document_ids: list[str] | None = None

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Ask a slightly longer question.")
        return v


class Source(BaseModel):
    n: int  # the number the answer cites, as in [n]
    document_id: str
    filename: str
    page: int
    snippet: str
    score: float


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    cited: list[int]  # which source numbers the answer actually cites
    confidence: Confidence
    found: bool  # False when the documents don't contain an answer
    flagged: bool = False  # True when the question was rejected as an injection attempt


class DocumentOut(BaseModel):
    id: str
    filename: str
    pages: int
    chunks: int
    size_bytes: int
    uploaded_at: str


class UploadResult(BaseModel):
    filename: str
    status: Literal["indexed", "duplicate", "failed"]
    document: DocumentOut | None = None
    error: str | None = None


class UploadResponse(BaseModel):
    results: list[UploadResult]


class Health(BaseModel):
    status: Literal["ok"]
    ai_configured: bool
    provider: str
    chat_model: str
    documents: int
    chunks: int
