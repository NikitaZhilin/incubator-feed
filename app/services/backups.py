from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sqlite3


logger = logging.getLogger(__name__)


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


def latest_backup_time(db_path: Path, backup_dir: Path) -> datetime | None:
    backups = list(backup_dir.glob(f"{db_path.stem}_*.db"))
    if not backups:
        return None
    newest = max(path.stat().st_mtime for path in backups)
    return datetime.fromtimestamp(newest, tz=timezone.utc)


def backup_is_due(
    db_path: Path,
    backup_dir: Path,
    *,
    every: timedelta,
    now: datetime | None = None,
) -> bool:
    if not db_path.exists():
        return False
    latest = latest_backup_time(db_path, backup_dir)
    if latest is None:
        return True
    return (now or datetime.now(timezone.utc)) - latest >= every


def run_verified_backup(db_path: Path, backup_dir: Path, *, keep_last: int = 7) -> Path:
    backup_path = create_sqlite_backup(db_path, backup_dir, keep_last=keep_last)
    if not verify_sqlite_backup(backup_path):
        raise RuntimeError(f"Backup integrity check failed: {backup_path}")
    return backup_path


OFFSITE_STAMP = ".last_telegram_copy"
# Telegram bots can send documents up to 50 MB.
TELEGRAM_DOCUMENT_LIMIT = 49 * 1024 * 1024


def offsite_copy_is_due(backup_dir: Path, *, every: timedelta, now: datetime | None = None) -> bool:
    stamp = backup_dir / OFFSITE_STAMP
    if not stamp.exists():
        return True
    current = now or datetime.now(timezone.utc)
    sent_at = datetime.fromtimestamp(stamp.stat().st_mtime, tz=timezone.utc)
    return current - sent_at >= every


def mark_offsite_copy_sent(backup_dir: Path) -> None:
    (backup_dir / OFFSITE_STAMP).write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def latest_backup_path(db_path: Path, backup_dir: Path) -> Path | None:
    candidates = sorted(backup_dir.glob(f"{db_path.stem}_*.db"), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def compress_backup(backup_path: Path) -> tuple[bytes, str]:
    """Gzip a verified backup for sending; returns (payload, file name)."""
    import gzip

    payload = gzip.compress(backup_path.read_bytes(), compresslevel=9)
    return payload, backup_path.name + ".gz"


class DailyBackupLoop:
    """Make a verified SQLite backup once a day inside the bot process.

    Works the same under Docker and systemd, so backups no longer depend on a
    host timer that may not be installed.
    """

    def __init__(
        self,
        *,
        db_path: Path,
        backup_dir: Path,
        every: timedelta = timedelta(hours=24),
        check_interval_seconds: int = 3600,
        keep_last: int = 7,
        on_failure: Callable[[BaseException], Awaitable[None]] | None = None,
        send_offsite: Callable[[Path], Awaitable[bool]] | None = None,
        offsite_every: timedelta = timedelta(days=7),
    ) -> None:
        self.send_offsite = send_offsite
        self.offsite_every = offsite_every
        self.db_path = db_path
        self.backup_dir = backup_dir
        self.every = every
        self.check_interval_seconds = check_interval_seconds
        self.keep_last = keep_last
        self.on_failure = on_failure
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def run_once(self) -> Path | None:
        if not backup_is_due(self.db_path, self.backup_dir, every=self.every):
            return None
        path = await asyncio.to_thread(
            run_verified_backup,
            self.db_path,
            self.backup_dir,
            keep_last=self.keep_last,
        )
        logger.info("Daily backup created: %s", path)
        return path

    async def send_offsite_if_due(self) -> bool:
        """Weekly copy of the latest backup off the server (to the admin in Telegram)."""
        if self.send_offsite is None or not offsite_copy_is_due(self.backup_dir, every=self.offsite_every):
            return False
        path = latest_backup_path(self.db_path, self.backup_dir)
        if path is None:
            return False
        if await self.send_offsite(path):
            mark_offsite_copy_sent(self.backup_dir)
            return True
        return False

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
                await self.send_offsite_if_due()
            except Exception as exc:
                logger.exception("Daily backup failed")
                if self.on_failure is not None:
                    try:
                        await self.on_failure(exc)
                    except Exception:
                        logger.exception("Failed to report backup failure")
            await asyncio.sleep(self.check_interval_seconds)
