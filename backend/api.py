"""Workspace content: documents, conversations and questions. Accounts live in account_api.

Every route is under /api/workspaces/{workspace_id}/... and checks membership: non-members
get 404, so other workspaces' existence and documents are never revealed.
"""

import json
import logging
import re
from contextlib import aclosing
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend import __version__, evidence, quota
from backend.account_api import require_role
from backend.auth import audit, csrf_protect, current_user, get_db
from backend.config import Settings
from backend.db import AuditEvent, Conversation, Message, User, Workspace, now
from backend.guard import looks_like_injection
from backend.pdf import PDFError, extract_pages
from backend.providers import classify, rate_limit_message
from backend.rag import Prepared, RagService
from backend.schemas import (
    AskRequest,
    AskResponse,
    ChatMessage,
    ConversationDetail,
    ConversationOut,
    DocumentOut,
    Health,
    StoredMessage,
    UploadResponse,
    UploadResult,
)
from backend.store import DocumentRecord, DocumentStore, DocumentTooLarge

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", dependencies=[Depends(csrf_protect)])


def HexId():  # noqa: N802 - a fresh Path() per parameter (sharing one breaks FastAPI routing)
    return PathParam(pattern=r"^[0-9a-f]{32}$")


_streaming_users: set[str] = set()  # one answer in flight per user


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def require_ai(request: Request) -> None:
    if not request.app.state.ai_ready:
        settings: Settings = request.app.state.settings
        raise HTTPException(
            status_code=503,
            detail=f"{settings.api_key_name} is not set on the server. Add it to backend/.env and restart.",
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


def _iso(dt) -> str:
    return dt.isoformat(timespec="seconds") + "Z"


@router.get("/health", response_model=Health)
def health(request: Request, db: Session = Depends(get_db)) -> Health:
    settings: Settings = request.app.state.settings
    return Health(
        status="ok",
        ai_configured=request.app.state.ai_ready,
        provider=settings.provider_label,
        chat_model=settings.chat_model,
        needs_setup=db.scalar(select(func.count()).select_from(User)) == 0,
    )


# ---------- documents ----------


@router.get("/workspaces/{workspace_id}/documents", response_model=list[DocumentOut])
def list_documents(
    request: Request, workspace_id: str = HexId(), user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[DocumentOut]:
    require_role(db, user, workspace_id, "viewer")
    with request.app.state.registry.use(workspace_id) as store:
        return [_doc_out(d) for d in store.list_documents()]


@router.post("/workspaces/{workspace_id}/documents", response_model=UploadResponse, dependencies=[Depends(require_ai)])
async def upload_documents(
    request: Request,
    workspace_id: str = HexId(),
    files: list[UploadFile] = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    require_role(db, user, workspace_id, "editor")
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")
    if len(files) > settings.max_files_per_upload:
        raise HTTPException(status_code=400, detail=f"Upload at most {settings.max_files_per_upload} files at a time.")

    results: list[UploadResult] = []
    with request.app.state.registry.use(workspace_id) as store:
        for upload in files:
            name = Path(upload.filename or "document.pdf").name[:200]
            data = await upload.read(settings.max_upload_bytes + 1)
            if len(data) > settings.max_upload_bytes:
                results.append(
                    UploadResult(
                        filename=name, status="failed", error=f"File is larger than {settings.max_upload_mb} MB."
                    )
                )
                continue
            try:
                pages = await run_in_threadpool(extract_pages, data, settings.max_pages)
                record, created = await run_in_threadpool(store.add, name, data, pages)
            except (PDFError, DocumentTooLarge) as exc:
                results.append(UploadResult(filename=name, status="failed", error=str(exc)))
                continue
            except Exception as exc:
                if classify(exc) in ("auth", "rate"):
                    raise  # a bad key or quota affects every file: return one clear 502/503 (main.py)
                logger.exception("Indexing %s failed", name)
                results.append(
                    UploadResult(filename=name, status="failed", error="Indexing failed. Check the server log.")
                )
                continue
            if created:
                audit(
                    db,
                    "document.uploaded",
                    request,
                    user,
                    workspace_id,
                    document_id=record.id,
                    filename=record.filename,
                    sha256=record.sha256,
                    pages=record.pages,
                )
            results.append(
                UploadResult(filename=name, status="indexed" if created else "duplicate", document=_doc_out(record))
            )
    db.commit()
    return UploadResponse(results=results)


@router.delete("/workspaces/{workspace_id}/documents/{document_id}", status_code=204)
async def delete_document(
    request: Request,
    workspace_id: str = HexId(),
    document_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    require_role(db, user, workspace_id, "editor")
    with request.app.state.registry.use(workspace_id) as store:
        record = store.get(document_id)
        if record is None or not await run_in_threadpool(store.delete, document_id):
            raise HTTPException(status_code=404, detail="Document not found.")
    audit(
        db,
        "document.deleted",
        request,
        user,
        workspace_id,
        document_id=document_id,
        filename=record.filename,
        sha256=record.sha256,
    )
    db.commit()
    return Response(status_code=204)


@router.get("/workspaces/{workspace_id}/documents/{document_id}/file")
def document_file(
    request: Request,
    workspace_id: str = HexId(),
    document_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    require_role(db, user, workspace_id, "viewer")
    with request.app.state.registry.use(workspace_id) as store:
        record = store.get(document_id)
        path = store.file_path(document_id)
    if record is None or not path.exists():
        raise HTTPException(status_code=404, detail="Document not found.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=record.filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=3600"},
    )


# ---------- conversations ----------


def _own_conversation(db: Session, workspace_id: str, user: User, conversation_id: str) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.workspace_id != workspace_id or conv.created_by != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conv


def _stored(m: Message) -> StoredMessage:
    result = AskResponse.model_validate(m.payload["response"]) if m.payload and "response" in m.payload else None
    return StoredMessage(id=m.id, role=m.role, content=m.content, result=result, created_at=_iso(m.created_at))


@router.get("/workspaces/{workspace_id}/conversations", response_model=list[ConversationOut])
def list_conversations(
    workspace_id: str = HexId(), user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[ConversationOut]:
    require_role(db, user, workspace_id, "viewer")
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.workspace_id == workspace_id, Conversation.created_by == user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    )
    return [ConversationOut(id=c.id, title=c.title, updated_at=_iso(c.updated_at)) for c in rows]


@router.get("/workspaces/{workspace_id}/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    workspace_id: str = HexId(),
    conversation_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ConversationDetail:
    require_role(db, user, workspace_id, "viewer")
    conv = _own_conversation(db, workspace_id, user, conversation_id)
    messages = db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at))
    return ConversationDetail(
        id=conv.id, title=conv.title, updated_at=_iso(conv.updated_at), messages=[_stored(m) for m in messages]
    )


@router.delete("/workspaces/{workspace_id}/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    request: Request,
    workspace_id: str = HexId(),
    conversation_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    require_role(db, user, workspace_id, "viewer")
    conv = _own_conversation(db, workspace_id, user, conversation_id)
    for m in db.scalars(select(Message).where(Message.conversation_id == conv.id)):
        db.delete(m)
    db.delete(conv)
    audit(db, "conversation.deleted", request, user, workspace_id, conversation_id=conversation_id)
    db.commit()
    return Response(status_code=204)


# ---------- questions ----------


def _history(db: Session, conv: Conversation | None, limit: int) -> list[ChatMessage]:
    if conv is None:
        return []
    rows = db.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.desc()).limit(limit)
    ).all()
    return [ChatMessage(role=m.role, content=m.content[:8000]) for m in reversed(rows)]


def _record(
    db: Session,
    settings: Settings,
    ws: Workspace,
    user: User,
    conv: Conversation | None,
    req: AskRequest,
    prepared: Prepared,
    response: AskResponse,
    store: DocumentStore,
) -> AskResponse:
    """Store the question and the answer record (the evidence later exports are built from)."""
    if conv is None:
        conv = Conversation(workspace_id=ws.id, created_by=user.id, title=req.question[:120])
        db.add(conv)
        db.flush()
    conv.updated_at = now()
    db.add(Message(conversation_id=conv.id, role="user", content=req.question))
    documents = {}
    for s in response.sources:
        if (rec := store.get(s.document_id)) is not None:
            documents[rec.id] = {"filename": rec.filename, "sha256": rec.sha256, "uploaded_at": rec.uploaded_at}
    answer = Message(conversation_id=conv.id, role="assistant", content=response.answer)
    db.add(answer)
    db.flush()  # assigns answer.id
    final = response.model_copy(update={"conversation_id": conv.id, "message_id": answer.id})
    answer.payload = {
        "response": final.model_dump(),
        "search_query": prepared.search_query,
        "provider": settings.provider,
        "embedding_model": settings.embedding_model,
        "thresholds": {"high": settings.confidence_high, "medium": settings.confidence_medium},
        "documents": documents,
        "document_filter": req.document_ids,
        "asked_by": user.id,
        "workspace_id": ws.id,
        "answered_at": now().isoformat(timespec="seconds") + "Z",
        # Full passage text (not the UI snippet), so evidence exports quote exactly what was used.
        "excerpts": {str(n): hit.text for n, hit in prepared.hits.items()},
    }
    db.commit()
    return final


async def _begin(request: Request, db: Session, user: User, workspace_id: str, req: AskRequest):
    """Common start of an answer: authorise, load the conversation, reserve quota."""
    settings: Settings = request.app.state.settings
    ws = require_role(db, user, workspace_id, "viewer")
    conv = _own_conversation(db, workspace_id, user, req.conversation_id) if req.conversation_id else None
    flagged = looks_like_injection(req.question)
    if flagged:
        logger.warning("Possible prompt injection rejected")
    else:
        try:
            quota.reserve(db, settings, user.id)
        except quota.QuotaExceeded as exc:
            raise HTTPException(
                status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)}
            ) from exc
    return settings, ws, conv, flagged


@router.post("/workspaces/{workspace_id}/ask", response_model=AskResponse)
async def ask(
    req: AskRequest,
    request: Request,
    workspace_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    rag: RagService = Depends(get_rag),
) -> AskResponse:
    settings, ws, conv, flagged = await _begin(request, db, user, workspace_id, req)
    history = _history(db, conv, settings.max_history_messages)
    with request.app.state.registry.use(workspace_id) as store:
        try:
            prepared = await rag.prepare(req, store, history, flagged)
            if prepared.messages is None and not flagged and not history:
                quota.refund(db, user.id)  # answered without calling the model
            response = await rag.complete(prepared)
        except Exception:
            if not flagged:
                quota.refund(db, user.id)
            raise
        return await run_in_threadpool(_record, db, settings, ws, user, conv, req, prepared, response, store)


@router.post("/workspaces/{workspace_id}/ask/stream")
async def ask_stream(
    req: AskRequest,
    request: Request,
    workspace_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    rag: RagService = Depends(get_rag),
) -> StreamingResponse:
    """Server-sent events: `sources`, then `token` events, then `done` (or `error`)."""
    if user.id in _streaming_users:
        return JSONResponse(status_code=429, content={"detail": "Wait for your current answer to finish."})
    settings, ws, conv, flagged = await _begin(request, db, user, workspace_id, req)
    history = _history(db, conv, settings.max_history_messages)
    borrow = request.app.state.registry.use(workspace_id)
    store = borrow.__enter__()
    try:
        prepared = await rag.prepare(req, store, history, flagged)
    except BaseException:
        borrow.__exit__(None, None, None)
        if not flagged:
            quota.refund(db, user.id)
        raise
    if prepared.messages is None and not flagged and not history:
        quota.refund(db, user.id)
    _streaming_users.add(user.id)
    user_id, ws_id, conv_id = user.id, ws.id, conv.id if conv else None
    sessionmaker = request.app.state.sessionmaker

    async def events():
        try:
            yield _sse("sources", [s.model_dump() for s in prepared.sources])
            parts: list[str] = []
            try:
                # aclosing() closes the upstream model stream as soon as the client disconnects.
                async with aclosing(rag.stream(prepared)) as tokens:
                    async for token in tokens:
                        parts.append(token)
                        yield _sse("token", {"text": token})
                response = rag.finish(prepared, "".join(parts).strip())
                with sessionmaker() as rdb:  # the request's DB session may already be closed
                    final = await run_in_threadpool(
                        _record,
                        rdb,
                        settings,
                        rdb.get(Workspace, ws_id),
                        rdb.get(User, user_id),
                        rdb.get(Conversation, conv_id) if conv_id else None,
                        req,
                        prepared,
                        response,
                        store,
                    )
            except Exception as exc:
                kind = classify(exc)
                label = settings.provider_label
                if kind == "rate":
                    logger.warning("%s", rate_limit_message(exc, label))
                else:
                    logger.exception("Streaming answer failed")
                message = {
                    "auth": f"{label} rejected the API key.",
                    "rate": rate_limit_message(exc, label),
                }.get(kind or "", "The AI model request failed. Please try again.")
                yield _sse("error", {"message": message})
                return
            yield _sse("done", final.model_dump())
        finally:
            _streaming_users.discard(user_id)
            borrow.__exit__(None, None, None)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


# ---------- evidence & audit trail ----------


def _pdf(data: bytes, name: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name)[:80].strip("-") or "evidence"
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"', "Cache-Control": "no-store"},
    )


def _export(db: Session, request: Request, user: User, ws: Workspace, conv: Conversation, messages: list[Message]):
    answers, question = [], ""
    for m in messages:
        if m.role == "user":
            question = m.content
        elif m.payload and "response" in m.payload:
            answers.append(evidence.answer_entry(question, m.payload))
    if not answers:
        raise HTTPException(status_code=404, detail="No recorded answers to export.")
    record = evidence.build_record(
        workspace={"id": ws.id, "name": ws.name},
        exported_by={"id": user.id, "email": user.email, "display_name": user.display_name},
        conversation={"id": conv.id, "title": conv.title},
        answers=answers,
        app_version=__version__,
    )
    data = evidence.render_pdf(record)
    audit(
        db,
        "evidence.exported",
        request,
        user,
        ws.id,
        conversation_id=conv.id,
        answers=[a["message_id"] for a in answers],
        sha256=evidence.digest(record),
    )
    db.commit()
    return _pdf(data, f"lumina-evidence-{conv.title}")


@router.get("/workspaces/{workspace_id}/answers/{message_id}/export")
def export_answer(
    request: Request,
    workspace_id: str = HexId(),
    message_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """One recorded answer (with the question that prompted it) as an evidence pack."""
    ws = require_role(db, user, workspace_id, "viewer")
    answer = db.get(Message, message_id)
    if answer is None or answer.role != "assistant":
        raise HTTPException(status_code=404, detail="Answer not found.")
    conv = _own_conversation(db, workspace_id, user, answer.conversation_id)
    question = db.scalars(
        select(Message)
        .where(Message.conversation_id == conv.id, Message.role == "user", Message.created_at <= answer.created_at)
        .order_by(Message.created_at.desc())
        .limit(1)
    ).first()
    return _export(db, request, user, ws, conv, [m for m in (question, answer) if m is not None])


@router.get("/workspaces/{workspace_id}/conversations/{conversation_id}/export")
def export_conversation(
    request: Request,
    workspace_id: str = HexId(),
    conversation_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    ws = require_role(db, user, workspace_id, "viewer")
    conv = _own_conversation(db, workspace_id, user, conversation_id)
    messages = list(db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)))
    return _export(db, request, user, ws, conv, messages)


@router.get("/workspaces/{workspace_id}/documents/history")
def document_history(
    workspace_id: str = HexId(), user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    """Who added or removed which document version, and when: "which version was in force on date D"."""
    require_role(db, user, workspace_id, "viewer")
    rows = db.execute(
        select(AuditEvent, User.display_name)
        .outerjoin(User, User.id == AuditEvent.actor_id)
        .where(AuditEvent.workspace_id == workspace_id, AuditEvent.event.in_(["document.uploaded", "document.deleted"]))
        .order_by(AuditEvent.ts.desc())
        .limit(500)
    ).all()
    return [{"at": _iso(e.ts), "event": e.event.split(".")[1], "by": name, **(e.detail or {})} for e, name in rows]


@router.post("/evidence/verify")
async def verify_evidence(file: UploadFile = File(...), user: User = Depends(current_user)) -> dict:
    data = await file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File is too large.")
    valid, message, record = await run_in_threadpool(evidence.verify_pack, data)
    return {
        "valid": valid,
        "message": message,
        "exported_at": record.get("exported_at") if record else None,
        "answers": len(record.get("answers", [])) if record else 0,
    }
