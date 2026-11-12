"""HTTP routes. Everything lives under /api; the app is assembled in backend.main."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend.config import Settings
from backend.guard import looks_like_injection
from backend.pdf import PDFError, extract_pages
from backend.rag import RagService
from backend.schemas import (
    AskRequest,
    AskResponse,
    DocumentOut,
    Health,
    UploadResponse,
    UploadResult,
)
from backend.store import DocumentRecord, DocumentStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

DocumentId = PathParam(pattern=r"^[0-9a-f]{32}$")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> DocumentStore:
    return request.app.state.store


def require_ai(request: Request) -> None:
    if not request.app.state.ai_ready:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not set on the server. Add it to .env and restart.",
        )


def get_rag(request: Request, _: None = Depends(require_ai)) -> RagService:
    return request.app.state.rag


def _doc_out(record: DocumentRecord) -> DocumentOut:
    return DocumentOut(
        id=record.id,
        filename=record.filename,
        pages=record.pages,
        chunks=record.chunks,
        size_bytes=record.size_bytes,
        uploaded_at=record.uploaded_at,
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/health", response_model=Health)
def health(request: Request, store: DocumentStore = Depends(get_store)) -> Health:
    settings: Settings = request.app.state.settings
    return Health(
        status="ok",
        openai_configured=request.app.state.ai_ready,
        chat_model=settings.chat_model,
        documents=len(store.list_documents()),
        chunks=store.chunk_count,
    )


# ---------- documents ----------


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(store: DocumentStore = Depends(get_store)) -> list[DocumentOut]:
    return [_doc_out(d) for d in store.list_documents()]


@router.post("/documents", response_model=UploadResponse, dependencies=[Depends(require_ai)])
async def upload_documents(
    files: list[UploadFile] = File(...),
    store: DocumentStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    results: list[UploadResult] = []
    for upload in files:
        name = Path(upload.filename or "document.pdf").name[:200]
        data = await upload.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            results.append(
                UploadResult(
                    filename=name,
                    status="failed",
                    error=f"File is larger than {settings.max_upload_mb} MB.",
                )
            )
            continue
        try:
            pages = await run_in_threadpool(extract_pages, data, settings.max_pages)
            record, created = await run_in_threadpool(store.add, name, data, pages)
        except PDFError as exc:
            results.append(UploadResult(filename=name, status="failed", error=str(exc)))
            continue
        except Exception:
            logger.exception("Indexing %s failed", name)
            results.append(
                UploadResult(
                    filename=name,
                    status="failed",
                    error="Indexing failed. Check the server log and your OpenAI key.",
                )
            )
            continue
        results.append(
            UploadResult(
                filename=name,
                status="indexed" if created else "duplicate",
                document=_doc_out(record),
            )
        )
    return UploadResponse(results=results)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: str = DocumentId, store: DocumentStore = Depends(get_store)) -> Response:
    if not await run_in_threadpool(store.delete, document_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    return Response(status_code=204)


@router.get("/documents/{document_id}/file")
def document_file(document_id: str = DocumentId, store: DocumentStore = Depends(get_store)) -> FileResponse:
    record = store.get(document_id)
    path = store.file_path(document_id)
    if record is None or not path.exists():
        raise HTTPException(status_code=404, detail="Document not found.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=record.filename,
        content_disposition_type="inline",
    )


# ---------- questions ----------


def _check_question(req: AskRequest) -> bool:
    flagged = looks_like_injection(req.question)
    if flagged:
        logger.warning("Possible prompt injection rejected")
    return flagged


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest, rag: RagService = Depends(get_rag)) -> AskResponse:
    return await rag.answer(req, flagged=_check_question(req))


@router.post("/ask/stream")
async def ask_stream(req: AskRequest, rag: RagService = Depends(get_rag)) -> StreamingResponse:
    """Server-sent events: `sources`, then `token` events, then `done` (or `error`)."""
    prepared = await rag.prepare(req, flagged=_check_question(req))

    async def events():
        yield _sse("sources", [s.model_dump() for s in prepared.sources])
        parts: list[str] = []
        try:
            async for token in rag.stream(prepared):
                parts.append(token)
                yield _sse("token", {"text": token})
        except Exception:
            logger.exception("Streaming answer failed")
            yield _sse("error", {"message": "The AI model request failed. Please try again."})
            return
        yield _sse("done", rag.finish(prepared, "".join(parts).strip()).model_dump())

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
