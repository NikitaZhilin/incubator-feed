from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3


def create_sqlite_backup(db_path: Path, backup_dir: Path, *, keep_last: int = 7) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{db_path.stem}_{timestamp}.db"

    source = sqlite3.connect(db_path)
    try:
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    _prune_backups(backup_dir, db_path.stem, keep_last)
    return backup_path


def verify_sqlite_backup(backup_path: Path) -> bool:
    connection = sqlite3.connect(backup_path)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        return bool(row and row[0] == "ok")
    finally:
        connection.close()


def _prune_backups(backup_dir: Path, stem: str, keep_last: int) -> None:
    backups = sorted(
        backup_dir.glob(f"{stem}_*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old_backup in backups[keep_last:]:
        old_backup.unlink(missing_ok=True)
