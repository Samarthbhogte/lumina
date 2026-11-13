"""Gap check routes: estimate, run, resume, list and read comparisons in a workspace."""

import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend import compare, quota
from backend.account_api import require_role
from backend.api import get_rag
from backend.auth import audit, csrf_protect, current_user, get_db
from backend.db import Comparison, User, now
from backend.providers import classify, rate_limit_message
from backend.rag import RagService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", dependencies=[Depends(csrf_protect)])


def HexId():  # noqa: N802
    return PathParam(pattern=r"^[0-9a-f]{32}$")


class CompareIn(BaseModel):
    requirements_document_id: str = Field(pattern=r"^[0-9a-f]{32}$")  # e.g. the regulation
    policy_document_id: str = Field(pattern=r"^[0-9a-f]{32}$")  # e.g. our policy


def _out(c: Comparison) -> dict:
    rows = (c.rows or {}).get("rows", [])
    return {
        "id": c.id,
        "title": c.title,
        "status": c.status,
        "note": c.note,
        "requirements_document_id": c.requirements_document_id,
        "policy_document_id": c.policy_document_id,
        "created_at": c.created_at.isoformat(timespec="seconds") + "Z",
        "rows": rows,
        "summary": compare.summary(rows) if rows else None,
        "total_requirements": (c.rows or {}).get("total", 0),
    }


def _documents(store, body: CompareIn):
    req, pol = store.get(body.requirements_document_id), store.get(body.policy_document_id)
    if req is None or pol is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if req.id == pol.id:
        raise HTTPException(status_code=400, detail="Pick two different documents.")
    return req, pol


@router.post("/workspaces/{workspace_id}/comparisons/estimate")
def estimate(
    body: CompareIn,
    request: Request,
    workspace_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_role(db, user, workspace_id, "viewer")
    with request.app.state.registry.use(workspace_id) as store:
        _documents(store, body)
        reqs = compare.requirements_of(store, body.requirements_document_id)
    settings = request.app.state.settings
    left = max(0, settings.daily_questions_per_user - quota.used_today(db, user.id))
    return {**compare.plan(reqs), "questions_left_today": left}


async def _run(request: Request, db: Session, user: User, comp: Comparison, rag: RagService) -> Comparison:
    settings = request.app.state.settings
    with request.app.state.registry.use(comp.workspace_id) as store:
        reqs = compare.requirements_of(store, comp.requirements_document_id)
        if not reqs:
            raise HTTPException(
                status_code=422,
                detail="No numbered clauses found in the requirements document, so there's nothing to check.",
            )
        rows = list((comp.rows or {}).get("rows", []))
        done = {r["requirement"]["id"] for r in rows}
        pending: list[tuple] = []
        stopped: str | None = None
        for req in reqs:
            if req.id in done:
                continue
            try:
                hits = await run_in_threadpool(compare.retrieve, store, req, comp.policy_document_id)
            except Exception as exc:  # embedding limits (often per minute on free tiers)
                kind = classify(exc)
                if kind is None:
                    raise
                stopped = (
                    rate_limit_message(exc, settings.provider_label) if kind == "rate" else "The AI request failed."
                )
                break
            if not hits or max(h.score for h in hits) < settings.confidence_medium:
                rationale = "No passage in the policy is close enough to this requirement."
                match = compare._match(hits[0]) if hits else None
                rows.append(asdict(compare.Row(asdict(req), "not_found", match, rationale=rationale)))
            else:
                pending.append((req, hits))
        comp.rows, comp.note = {"rows": rows, "total": len(reqs)}, None
        comp.status = "running"

        for start in range(0, len(pending), compare.BATCH):
            batch = pending[start : start + compare.BATCH]
            try:
                quota.reserve(db, settings, user.id)
            except quota.QuotaExceeded as exc:
                comp.status, comp.note = "partial", str(exc)
                break
            try:
                rows.extend(asdict(r) for r in await compare.classify_batch(rag.llm, batch))
            except Exception as exc:
                quota.refund(db, user.id)
                kind = classify(exc)
                if kind is None:
                    raise
                comp.status = "partial"
                comp.note = (
                    rate_limit_message(exc, settings.provider_label) if kind == "rate" else "The AI request failed."
                )
                break
            comp.rows = {"rows": list(rows), "total": len(reqs)}  # checkpoint after every batch
            comp.updated_at = now()
            db.commit()
        else:
            comp.status = "partial" if stopped else "done"
            comp.note = stopped
    order = {r.id: i for i, r in enumerate(reqs)}
    rows.sort(key=lambda r: order.get(r["requirement"]["id"], 1_000_000))
    comp.rows, comp.updated_at = {"rows": rows, "total": len(reqs)}, now()
    db.commit()
    return comp


@router.post("/workspaces/{workspace_id}/comparisons", status_code=201)
async def run_comparison(
    body: CompareIn,
    request: Request,
    workspace_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    rag: RagService = Depends(get_rag),
) -> dict:
    require_role(db, user, workspace_id, "viewer")
    with request.app.state.registry.use(workspace_id) as store:
        req, pol = _documents(store, body)
    comp = Comparison(
        workspace_id=workspace_id,
        created_by=user.id,
        requirements_document_id=req.id,
        policy_document_id=pol.id,
        title=f"{pol.filename} vs {req.filename}",
    )
    db.add(comp)
    audit(db, "comparison.started", request, user, workspace_id, requirements=req.filename, policy=pol.filename)
    db.commit()
    return _out(await _run(request, db, user, comp, rag))


@router.post("/workspaces/{workspace_id}/comparisons/{comparison_id}/resume")
async def resume_comparison(
    request: Request,
    workspace_id: str = HexId(),
    comparison_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    rag: RagService = Depends(get_rag),
) -> dict:
    require_role(db, user, workspace_id, "viewer")
    comp = db.get(Comparison, comparison_id)
    if comp is None or comp.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Comparison not found.")
    if comp.status == "done":
        return _out(comp)
    comp.status = "running"
    return _out(await _run(request, db, user, comp, rag))


@router.get("/workspaces/{workspace_id}/comparisons")
def list_comparisons(workspace_id: str = HexId(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(db, user, workspace_id, "viewer")
    rows = db.scalars(
        select(Comparison)
        .where(Comparison.workspace_id == workspace_id)
        .order_by(Comparison.created_at.desc())
        .limit(50)
    )
    return [{k: v for k, v in _out(c).items() if k != "rows"} for c in rows]


@router.get("/workspaces/{workspace_id}/comparisons/{comparison_id}")
def get_comparison(
    workspace_id: str = HexId(),
    comparison_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_role(db, user, workspace_id, "viewer")
    comp = db.get(Comparison, comparison_id)
    if comp is None or comp.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Comparison not found.")
    return _out(comp)
