"""Request and response models shared by the API and the frontend."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Confidence = Literal["high", "medium", "low"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # Continue this conversation; omitted starts a new one. History comes from the server's
    # record of the conversation, never from the client (forged turns were an injection path).
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
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
    page_end: int | None = None
    section: str | None = None
    heading: str | None = None
    clause: str | None = None  # set once the answer shows which clause was relied on
    label: str = ""  # e.g. "GDPR Sample Compliance §7.2, p.1"


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    cited: list[int]  # which source numbers the answer actually cites
    confidence: Confidence
    found: bool  # False when the documents don't contain an answer
    flagged: bool = False  # True when the question was rejected as an injection attempt
    model: str | None = None  # the model that produced the answer
    conversation_id: str | None = None
    message_id: str | None = None  # the stored answer record (for evidence export)


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
    needs_setup: bool  # no accounts yet


class ConversationOut(BaseModel):
    id: str
    title: str
    updated_at: str


class StoredMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    result: AskResponse | None = None  # assistant turns: the full recorded answer
    created_at: str


class ConversationDetail(ConversationOut):
    messages: list[StoredMessage]
