"""Authentication: passwords, server-side sessions, CSRF, login throttling and audit events.

Sessions are opaque random tokens in an HttpOnly, SameSite=Lax cookie; the database keeps
only their SHA-256, so a leaked database can't be replayed. All browser traffic arrives
same-origin through the Next.js proxy.
"""

import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.db import AuditEvent, AuthSession, Usage, User, now

_hasher = PasswordHasher()  # argon2id with library defaults
_DUMMY_HASH = _hasher.hash("lumina-timing-equaliser")

MIN_PASSWORD = 15  # NIST SP 800-63B-4 for single-factor passwords
MAX_PASSWORD = 128
_COMMON = {
    "password",
    "passwordpassword",
    "123456789012345",
    "qwertyuiopasdfg",
    "iloveyouiloveyou",
    "letmeinletmein!",
    "welcome12345678",
    "administrator123",
    "changemechangeme",
    "correcthorsebatterystaple",
}

LOGIN_WINDOW_MINUTES = 15
MAX_FAILURES_PER_ACCOUNT = 5  # per account from one IP
MAX_FAILURES_PER_ACCOUNT_ANY_IP = 50  # slows distributed guessing without letting a stranger lock you out
MAX_FAILURES_PER_IP = 20
CSRF_HEADER = "x-lumina-csrf"


# ---------- passwords ----------


def password_problem(password: str, email: str = "") -> str | None:
    """A user-facing reason the password is unacceptable, or None."""
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters. A short phrase of four or five words works well."
    if len(password) > MAX_PASSWORD:
        return f"Use at most {MAX_PASSWORD} characters."
    lowered = password.lower()
    if lowered in _COMMON or len(set(lowered)) < 4:
        return "That password is too common or repetitive. Try a phrase only you would use."
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in lowered:
        return "Don't include your email address in the password."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(user: User | None, password: str) -> bool:
    """Constant-ish time: a missing user still costs one argon2 verify."""
    try:
        return _hasher.verify(user.password_hash if user else _DUMMY_HASH, password) and user is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(user: User) -> bool:
    return _hasher.check_needs_rehash(user.password_hash)


# ---------- tokens and sessions ----------


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def cookie_name(settings: Settings) -> str:
    # The __Host- prefix makes browsers refuse the cookie unless Secure, host-only and Path=/.
    return "__Host-lumina_session" if settings.cookie_secure else "lumina_session"


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def start_session(db: Session, settings: Settings, user: User, request: Request, response: Response) -> None:
    """Issue a fresh session (never reuse an existing token: prevents session fixation)."""
    token, digest = new_token()
    db.add(
        AuthSession(
            token_hash=digest,
            user_id=user.id,
            expires_at=now() + timedelta(days=settings.session_max_days),
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:255],
        )
    )
    response.set_cookie(
        cookie_name(settings),
        token,
        max_age=settings.session_max_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def end_session(db: Session, settings: Settings, request: Request, response: Response) -> None:
    token = request.cookies.get(cookie_name(settings))
    if token:
        found = db.get(AuthSession, token_hash(token))
        if found:
            db.delete(found)
    response.delete_cookie(
        cookie_name(settings), path="/", secure=settings.cookie_secure, httponly=True, samesite="lax"
    )


def end_all_sessions(db: Session, user_id: str) -> None:
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user_id)):
        db.delete(s)


# ---------- FastAPI dependencies ----------


def get_db(request: Request):
    with request.app.state.sessionmaker() as db:
        yield db


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    settings = _settings(request)
    token = request.cookies.get(cookie_name(settings))
    if not token:
        return None
    session = db.get(AuthSession, token_hash(token))
    if session is None:
        return None
    t = now()
    if session.expires_at <= t or session.last_seen_at + timedelta(days=settings.session_idle_days) <= t:
        db.delete(session)
        db.commit()
        return None
    user = db.get(User, session.user_id)
    if user is None or user.disabled_at is not None:
        return None
    if t - session.last_seen_at > timedelta(minutes=1):  # avoid a write on every request
        session.last_seen_at = t
        db.commit()
    return user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user


def _origin_allowed(request: Request, settings: Settings) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True  # non-browser clients; the custom header below still has to be present
    allowed = set(settings.trusted_origin_list)
    forwarded_host = request.headers.get("x-forwarded-host")
    proto = request.headers.get("x-forwarded-proto", "http")
    if forwarded_host:  # same-origin through the Next.js proxy
        allowed.add(f"{proto}://{forwarded_host}")
    return origin in allowed


def csrf_protect(request: Request) -> None:
    """Unsafe methods need a trusted Origin and a custom header (which forms can't send)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get(CSRF_HEADER) != "1" or not _origin_allowed(request, _settings(request)):
        raise HTTPException(status_code=403, detail="Request blocked by cross-site protection.")


# ---------- login throttling ----------


def _window() -> str:
    t = now()
    return t.replace(
        minute=(t.minute // LOGIN_WINDOW_MINUTES) * LOGIN_WINDOW_MINUTES, second=0, microsecond=0
    ).isoformat()


def _failures(db: Session, scope: str) -> int:
    row = db.get(Usage, {"scope": scope, "window": _window(), "kind": "login_fail"})
    return row.count if row else 0


def login_blocked(db: Session, email: str, ip: str) -> bool:
    return (
        _failures(db, f"email:{email}|ip:{ip}") >= MAX_FAILURES_PER_ACCOUNT
        or _failures(db, f"email:{email}") >= MAX_FAILURES_PER_ACCOUNT_ANY_IP
        or _failures(db, f"ip:{ip}") >= MAX_FAILURES_PER_IP
    )


def record_login_failure(db: Session, email: str, ip: str) -> None:
    for scope in (f"email:{email}|ip:{ip}", f"email:{email}", f"ip:{ip}"):
        stmt = insert(Usage).values(scope=scope, window=_window(), kind="login_fail", count=1)
        db.execute(
            stmt.on_conflict_do_update(index_elements=["scope", "window", "kind"], set_={"count": Usage.count + 1})
        )


# ---------- audit ----------


def audit(
    db: Session,
    event: str,
    request: Request | None = None,
    actor: User | None = None,
    workspace_id: str | None = None,
    **detail,
) -> None:
    db.add(
        AuditEvent(
            event=event,
            actor_id=actor.id if actor else None,
            workspace_id=workspace_id,
            ip=client_ip(request) if request else None,
            detail=detail or None,
        )
    )
