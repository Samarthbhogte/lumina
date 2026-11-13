"""Per-user and global daily limits on AI questions, reserved atomically before calling the model."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.db import Usage

PACIFIC = ZoneInfo("America/Los_Angeles")  # Gemini free-tier quotas reset at midnight Pacific
KIND = "ask"


class QuotaExceeded(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


def _day() -> str:
    return datetime.now(PACIFIC).date().isoformat()


def seconds_until_reset() -> int:
    t = datetime.now(PACIFIC)
    next_midnight = (t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((next_midnight - t).total_seconds()))


def _take(db: Session, scope: str, limit: int) -> bool:
    """Atomically count one use if under the limit. True when it was counted."""
    if limit <= 0:  # the first use inserts a row with count=1, so a zero limit must be checked here
        return False
    stmt = insert(Usage).values(scope=scope, window=_day(), kind=KIND, count=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=["scope", "window", "kind"],
        set_={"count": Usage.count + 1},
        where=Usage.count < limit,
    ).returning(Usage.count)
    return db.execute(stmt).first() is not None


def _give_back(db: Session, scope: str) -> None:
    # One atomic UPDATE, so a concurrent reservation can't be overwritten.
    db.execute(
        update(Usage)
        .where(Usage.scope == scope, Usage.window == _day(), Usage.kind == KIND, Usage.count > 0)
        .values(count=Usage.count - 1)
    )


def reserve(db: Session, settings: Settings, user_id: str) -> None:
    """Reserve one question for this user (and the global budget), or raise QuotaExceeded."""
    hours = seconds_until_reset() // 3600
    if not _take(db, f"user:{user_id}", settings.daily_questions_per_user):
        db.rollback()
        raise QuotaExceeded(
            f"You've used your {settings.daily_questions_per_user} questions for today. "
            f"The limit resets in about {hours} h.",
            seconds_until_reset(),
        )
    if not _take(db, "global", settings.daily_questions_total):
        db.rollback()
        raise QuotaExceeded(
            f"This Lumina server has used its {settings.daily_questions_total} AI questions for today. "
            f"The limit resets in about {hours} h.",
            seconds_until_reset(),
        )
    db.commit()


def refund(db: Session, user_id: str) -> None:
    """Return a reservation when no model call happened (blocked, no documents, nothing found)."""
    _give_back(db, f"user:{user_id}")
    _give_back(db, "global")
    db.commit()


def used_today(db: Session, user_id: str) -> int:
    row = db.get(Usage, {"scope": f"user:{user_id}", "window": _day(), "kind": KIND})
    return row.count if row else 0
