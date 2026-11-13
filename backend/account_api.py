"""Accounts, workspaces, members, invites and password resets."""

import logging
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi import Path as PathParam
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import quota
from backend.auth import (
    audit,
    client_ip,
    csrf_protect,
    current_user,
    end_all_sessions,
    end_session,
    get_db,
    hash_password,
    login_blocked,
    needs_rehash,
    new_token,
    optional_user,
    password_problem,
    record_login_failure,
    start_session,
    token_hash,
    verify_password,
)
from backend.config import Settings
from backend.db import ROLES, AuthSession, Invite, Membership, Meta, PasswordReset, User, Workspace, now
from backend.migrate import migrate_legacy_library

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", dependencies=[Depends(csrf_protect)])

Role = Literal["viewer", "editor", "owner"]


def HexId():  # noqa: N802 - a fresh Path() per parameter (sharing one breaks FastAPI routing)
    return PathParam(pattern=r"^[0-9a-f]{32}$")


INVITE_DAYS = 7
RESET_HOURS = 24


def _settings(request: Request) -> Settings:
    return request.app.state.settings


# ---------- schemas ----------


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)

    @field_validator("email")
    @classmethod
    def _norm(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v:
            raise ValueError("Enter a valid email address.")
        return v


class Signup(Credentials):
    display_name: str = Field(min_length=1, max_length=120)
    invite_token: str | None = Field(default=None, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class ResetPassword(BaseModel):
    token: str = Field(max_length=128)
    new_password: str = Field(max_length=256)


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class InviteIn(BaseModel):
    role: Role = "viewer"
    email: str | None = Field(default=None, max_length=320)


class RoleIn(BaseModel):
    role: Role


class WorkspaceOut(BaseModel):
    id: str
    name: str
    kind: str
    role: str


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    is_admin: bool


class Me(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceOut]
    questions_used_today: int
    questions_per_day: int


class MemberOut(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str


class InviteOut(BaseModel):
    id: str
    role: str
    email: str | None
    expires_at: str
    link: str | None = None  # only returned once, at creation


class SetupStatus(BaseModel):
    needs_setup: bool  # no users yet: the first sign-up becomes admin
    signup: str


# ---------- helpers ----------


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, display_name=u.display_name, is_admin=u.is_admin)


def _workspaces_for(db: Session, user: User) -> list[WorkspaceOut]:
    rows = db.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id, Workspace.deleted_at.is_(None))
        .order_by(Workspace.kind.desc(), Workspace.created_at)
    ).all()
    return [WorkspaceOut(id=w.id, name=w.name, kind=w.kind, role=r) for w, r in rows]


def require_role(db: Session, user: User, workspace_id: str, minimum: str) -> Workspace:
    """The workspace if `user` holds at least `minimum` there. Non-members get 404, not 403."""
    row = db.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Workspace.id == workspace_id, Membership.user_id == user.id, Workspace.deleted_at.is_(None))
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    workspace, role = row
    if ROLES.index(role) < ROLES.index(minimum):
        raise HTTPException(status_code=403, detail=f"This needs the {minimum} role in this workspace.")
    return workspace


def _owners(db: Session, workspace_id: str) -> int:
    return db.scalar(select(func.count()).where(Membership.workspace_id == workspace_id, Membership.role == "owner"))


def _invite_link(request: Request, token: str) -> str:
    origin = request.headers.get("origin") or ""
    return f"{origin}/invite/{token}"


def _valid_invite(db: Session, token: str) -> Invite | None:
    invite = db.scalar(select(Invite).where(Invite.token_hash == token_hash(token)))
    if invite is None or invite.accepted_at or invite.revoked_at or invite.expires_at <= now():
        return None
    ws = db.get(Workspace, invite.workspace_id)
    return invite if ws and ws.deleted_at is None else None


def _accept(db: Session, invite: Invite, user: User, request: Request) -> None:
    if invite.email and invite.email != user.email:
        raise HTTPException(status_code=403, detail="This invite is for a different email address.")
    existing = db.get(Membership, {"workspace_id": invite.workspace_id, "user_id": user.id})
    if existing is None:
        db.add(Membership(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role))
    elif ROLES.index(invite.role) > ROLES.index(existing.role):
        existing.role = invite.role
    invite.accepted_at, invite.accepted_by = now(), user.id
    audit(db, "invite.accepted", request, user, invite.workspace_id, role=invite.role)


# ---------- auth ----------


@router.get("/auth/setup", response_model=SetupStatus)
def setup_status(request: Request, db: Session = Depends(get_db)) -> SetupStatus:
    return SetupStatus(
        needs_setup=db.scalar(select(func.count()).select_from(User)) == 0, signup=_settings(request).signup
    )


@router.post("/auth/signup", response_model=Me)
def signup(body: Signup, request: Request, response: Response, db: Session = Depends(get_db)) -> Me:
    settings = _settings(request)
    first_user = db.scalar(select(func.count()).select_from(User)) == 0
    invite = _valid_invite(db, body.invite_token) if body.invite_token else None
    if not first_user and settings.signup == "invite" and invite is None:
        raise HTTPException(status_code=403, detail="Sign-up needs an invite link from a workspace owner.")
    if problem := password_problem(body.password, body.email):
        raise HTTPException(status_code=422, detail=problem)
    if db.scalar(select(User).where(User.email == body.email)):
        # Only reachable with a valid invite or open sign-up, so this doesn't leak to strangers.
        raise HTTPException(status_code=409, detail="An account with this email already exists. Sign in instead.")

    user = User(
        email=body.email,
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
        is_admin=first_user,
    )
    db.add(user)
    try:
        db.flush()
        if first_user:  # a unique row: of two simultaneous first sign-ups, only one becomes admin
            db.add(Meta(key="first_admin", value=user.id))
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Setup was just completed by someone else. Sign in instead."
        ) from exc
    personal = Workspace(name=f"{user.display_name}'s workspace", kind="personal", created_by=user.id)
    db.add(personal)
    db.flush()
    db.add(Membership(workspace_id=personal.id, user_id=user.id, role="owner"))
    if invite:
        _accept(db, invite, user, request)
    audit(db, "user.signup", request, user, personal.id, first_user=first_user)
    if first_user and migrate_legacy_library(settings, request.app.state.registry.path(personal.id)):
        audit(db, "library.migrated", request, user, personal.id)
    start_session(db, settings, user, request, response)
    user.last_login_at = now()
    db.commit()
    return me(request, user, db)


@router.post("/auth/login", response_model=Me)
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)) -> Me:
    settings, ip = _settings(request), client_ip(request)
    if login_blocked(db, body.email, ip):
        raise HTTPException(status_code=429, detail="Too many failed sign-ins. Wait 15 minutes and try again.")
    user = db.scalar(select(User).where(User.email == body.email))
    if not verify_password(user, body.password) or user is None or user.disabled_at is not None:
        record_login_failure(db, body.email, ip)
        audit(db, "auth.login_failed", request, None, None, email=body.email)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if needs_rehash(user):
        user.password_hash = hash_password(body.password)
    end_session(db, settings, request, response)  # drop any pre-login session cookie
    start_session(db, settings, user, request, response)
    user.last_login_at = now()
    audit(db, "auth.login", request, user)
    db.commit()
    return me(request, user, db)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    end_session(db, _settings(request), request, response)
    db.commit()
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=Me)
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Me:
    return Me(
        user=_user_out(user),
        workspaces=_workspaces_for(db, user),
        questions_used_today=quota.used_today(db, user.id),
        questions_per_day=_settings(request).daily_questions_per_user,
    )


@router.post("/auth/password", status_code=204)
def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    if not verify_password(user, body.current_password):
        raise HTTPException(status_code=401, detail="Your current password is incorrect.")
    if problem := password_problem(body.new_password, user.email):
        raise HTTPException(status_code=422, detail=problem)
    user.password_hash, user.password_changed_at = hash_password(body.new_password), now()
    end_all_sessions(db, user.id)  # sign out everywhere else
    start_session(db, _settings(request), user, request, response)
    audit(db, "auth.password_changed", request, user)
    db.commit()
    response.status_code = 204
    return response


@router.post("/auth/reset", status_code=204)
def reset_password(body: ResetPassword, request: Request, db: Session = Depends(get_db)) -> Response:
    reset = db.get(PasswordReset, token_hash(body.token))
    if reset is None or reset.used_at or reset.expires_at <= now():
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
    user = db.get(User, reset.user_id)
    if problem := password_problem(body.new_password, user.email):
        raise HTTPException(status_code=422, detail=problem)
    user.password_hash, user.password_changed_at = hash_password(body.new_password), now()
    reset.used_at = now()
    end_all_sessions(db, user.id)
    audit(db, "auth.password_reset", request, user)
    db.commit()
    return Response(status_code=204)


@router.post("/admin/users/{user_id}/reset-link")
def create_reset_link(
    request: Request, user_id: str = HexId(), admin: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    """No email service: an admin generates a single-use link and passes it on."""
    if not admin.is_admin:
        raise HTTPException(status_code=403, detail="Only an admin can create reset links.")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    token, digest = new_token()
    db.add(
        PasswordReset(
            token_hash=digest, user_id=target.id, created_by=admin.id, expires_at=now() + timedelta(hours=RESET_HOURS)
        )
    )
    audit(db, "auth.reset_link_created", request, admin, None, target=target.id)
    db.commit()
    return {"link": f"{request.headers.get('origin') or ''}/reset/{token}", "expires_in_hours": RESET_HOURS}


# ---------- workspaces ----------


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[WorkspaceOut]:
    return _workspaces_for(db, user)


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
def create_workspace(
    body: WorkspaceIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> WorkspaceOut:
    ws = Workspace(name=body.name.strip(), kind="team", created_by=user.id)
    db.add(ws)
    db.flush()
    db.add(Membership(workspace_id=ws.id, user_id=user.id, role="owner"))
    audit(db, "workspace.created", request, user, ws.id, name=ws.name)
    db.commit()
    return WorkspaceOut(id=ws.id, name=ws.name, kind=ws.kind, role="owner")


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
def rename_workspace(
    body: WorkspaceIn,
    request: Request,
    workspace_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    ws = require_role(db, user, workspace_id, "owner")
    ws.name = body.name.strip()
    audit(db, "workspace.renamed", request, user, ws.id, name=ws.name)
    db.commit()
    return WorkspaceOut(id=ws.id, name=ws.name, kind=ws.kind, role="owner")


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(
    request: Request, workspace_id: str = HexId(), user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    ws = require_role(db, user, workspace_id, "owner")
    if ws.kind == "personal":
        raise HTTPException(status_code=400, detail="Your personal workspace can't be deleted.")
    ws.deleted_at = now()  # soft delete: files stay on disk until an admin purges them
    request.app.state.registry.forget(ws.id)
    audit(db, "workspace.deleted", request, user, ws.id)
    db.commit()
    return Response(status_code=204)


# ---------- members ----------


@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberOut])
def list_members(
    workspace_id: str = HexId(), user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[MemberOut]:
    require_role(db, user, workspace_id, "viewer")
    rows = db.execute(
        select(User, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(User.display_name)
    ).all()
    return [MemberOut(user_id=u.id, email=u.email, display_name=u.display_name, role=r) for u, r in rows]


@router.patch("/workspaces/{workspace_id}/members/{member_id}", response_model=MemberOut)
def change_role(
    body: RoleIn,
    request: Request,
    workspace_id: str = HexId(),
    member_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MemberOut:
    require_role(db, user, workspace_id, "owner")
    m = db.get(Membership, {"workspace_id": workspace_id, "user_id": member_id})
    if m is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if m.role == "owner" and body.role != "owner" and _owners(db, workspace_id) == 1:
        raise HTTPException(status_code=400, detail="A workspace needs at least one owner.")
    m.role = body.role
    audit(db, "member.role_changed", request, user, workspace_id, member=member_id, role=body.role)
    db.commit()
    target = db.get(User, member_id)
    return MemberOut(user_id=target.id, email=target.email, display_name=target.display_name, role=m.role)


@router.delete("/workspaces/{workspace_id}/members/{member_id}", status_code=204)
def remove_member(
    request: Request,
    workspace_id: str = HexId(),
    member_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    ws = require_role(db, user, workspace_id, "viewer" if member_id == user.id else "owner")
    m = db.get(Membership, {"workspace_id": workspace_id, "user_id": member_id})
    if m is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if ws.kind == "personal":
        raise HTTPException(status_code=400, detail="Members can't be removed from a personal workspace.")
    if m.role == "owner" and _owners(db, workspace_id) == 1:
        raise HTTPException(status_code=400, detail="A workspace needs at least one owner.")
    db.delete(m)
    audit(db, "member.removed", request, user, workspace_id, member=member_id)
    db.commit()
    return Response(status_code=204)


# ---------- invites ----------


@router.post("/workspaces/{workspace_id}/invites", response_model=InviteOut, status_code=201)
def create_invite(
    body: InviteIn,
    request: Request,
    workspace_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> InviteOut:
    ws = require_role(db, user, workspace_id, "owner")
    if ws.kind == "personal":
        raise HTTPException(status_code=400, detail="Create a team workspace to invite people.")
    token, digest = new_token()
    invite = Invite(
        workspace_id=ws.id,
        role=body.role,
        token_hash=digest,
        email=body.email.strip().lower() if body.email else None,
        created_by=user.id,
        expires_at=now() + timedelta(days=INVITE_DAYS),
    )
    db.add(invite)
    audit(db, "invite.created", request, user, ws.id, role=body.role)
    db.commit()
    return InviteOut(
        id=invite.id,
        role=invite.role,
        email=invite.email,
        expires_at=invite.expires_at.isoformat() + "Z",
        link=_invite_link(request, token),
    )


@router.get("/workspaces/{workspace_id}/invites", response_model=list[InviteOut])
def list_invites(
    workspace_id: str = HexId(), user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[InviteOut]:
    require_role(db, user, workspace_id, "owner")
    invites = db.scalars(
        select(Invite).where(
            Invite.workspace_id == workspace_id,
            Invite.accepted_at.is_(None),
            Invite.revoked_at.is_(None),
            Invite.expires_at > now(),
        )
    )
    return [InviteOut(id=i.id, role=i.role, email=i.email, expires_at=i.expires_at.isoformat() + "Z") for i in invites]


@router.delete("/workspaces/{workspace_id}/invites/{invite_id}", status_code=204)
def revoke_invite(
    request: Request,
    workspace_id: str = HexId(),
    invite_id: str = HexId(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    require_role(db, user, workspace_id, "owner")
    invite = db.get(Invite, invite_id)
    if invite is None or invite.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Invite not found.")
    invite.revoked_at = now()
    audit(db, "invite.revoked", request, user, workspace_id)
    db.commit()
    return Response(status_code=204)


@router.get("/invites/{token}")
def preview_invite(token: str, db: Session = Depends(get_db), user: User | None = Depends(optional_user)) -> dict:
    invite = _valid_invite(db, token)
    if invite is None:
        raise HTTPException(status_code=404, detail="This invite link is invalid or has expired.")
    ws = db.get(Workspace, invite.workspace_id)
    return {"workspace": ws.name, "role": invite.role, "signed_in": user is not None}


@router.post("/invites/{token}/accept", response_model=WorkspaceOut)
def accept_invite(
    token: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> WorkspaceOut:
    invite = _valid_invite(db, token)
    if invite is None:
        raise HTTPException(status_code=404, detail="This invite link is invalid or has expired.")
    _accept(db, invite, user, request)
    db.commit()
    ws = db.get(Workspace, invite.workspace_id)
    role = db.get(Membership, {"workspace_id": ws.id, "user_id": user.id}).role
    return WorkspaceOut(id=ws.id, name=ws.name, kind=ws.kind, role=role)


@router.get("/auth/sessions")
def list_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(
        select(AuthSession).where(AuthSession.user_id == user.id).order_by(AuthSession.last_seen_at.desc())
    )
    return [
        {
            "created_at": s.created_at.isoformat() + "Z",
            "last_seen_at": s.last_seen_at.isoformat() + "Z",
            "ip": s.ip,
            "user_agent": s.user_agent,
        }
        for s in rows
    ]
