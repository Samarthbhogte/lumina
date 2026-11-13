"""Move a v2 single-library data directory into the first account's workspace.

v2 kept one library at data_dir/{documents.json, index/, files/}. v3 keeps one per workspace
under data_dir/workspaces/<id>/. The first sign-up adopts the old library; a timestamped
backup copy is taken first, because the move can't be undone otherwise.
"""

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from backend.config import Settings

logger = logging.getLogger(__name__)
LEGACY = ("documents.json", "index", "files")


def has_legacy_library(data_dir: Path) -> bool:
    return (data_dir / "documents.json").exists()


def migrate_legacy_library(settings: Settings, target: Path) -> bool:
    """Back up and move the v2 library into `target`. Returns True if anything moved."""
    data_dir = settings.data_dir
    if not has_legacy_library(data_dir):
        return False
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = data_dir / f"backup-v2-{stamp}"
    backup.mkdir(parents=True)
    for name in LEGACY:
        src = data_dir / name
        if src.is_dir():
            shutil.copytree(src, backup / name)
        elif src.exists():
            shutil.copy2(src, backup / name)
    target.mkdir(parents=True, exist_ok=True)
    for name in LEGACY:
        src = data_dir / name
        if src.exists():
            dest = target / name
            if dest.exists():  # an empty store was opened before migration; replace it
                shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
            src.rename(dest)
    logger.info("Moved the v2 library into %s (backup: %s)", target, backup)
    return True
