"""App database (SQLite via SQLAlchemy): users, workspaces, sessions, conversations, usage, audit.

Documents and their vectors stay in per-workspace DocumentStore directories; this database
holds everything about people and access. Tables are created on startup. When the schema
first changes, add Alembic migrations; SCHEMA_VERSION records what a database was built with.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    insert,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

SCHEMA_VERSION = 1
ROLES = ("viewer", "editor", "owner")  # ascending privilege


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # stored as naive UTC


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON}


class Meta(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16), default="team")  # personal | team
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class Membership(Base):
    __tablename__ = "memberships"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(16))  # viewer | editor | owner
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str | None] = mapped_column(String(320))  # optional: restrict to one address
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    accepted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class PasswordReset(Base):
    __tablename__ = "password_resets"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuthSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the cookie value
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)  # absolute limit
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Message(Base):
    """One turn. Assistant turns are the server's record of an answer (evidence for exports)."""

    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # Assistant turns: sources, cited, confidence, found, flagged, model, search query, ...
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Usage(Base):
    """Counters per scope and window: AI questions per user/day, login failures per key/window."""

    __tablename__ = "usage"
    scope: Mapped[str] = mapped_column(String(400), primary_key=True)
    window: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(32))
    workspace_id: Mapped[str | None] = mapped_column(String(32), index=True)
    event: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON)


def make_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _):  # pragma: no cover - exercised by every test
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        found = conn.execute(select(Meta.value).where(Meta.key == "schema_version")).scalar()
        if found is None:
            conn.execute(insert(Meta).values(key="schema_version", value=str(SCHEMA_VERSION)))
    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker:
    return sessionmaker(engine, expire_on_commit=False)
