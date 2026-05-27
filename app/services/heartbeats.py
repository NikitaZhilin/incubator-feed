from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
import logging

from app.storage.repositories.heartbeats import HeartbeatRepository


logger = logging.getLogger(__name__)


class HeartbeatLoop:
    def __init__(
        self,
        *,
        heartbeats: HeartbeatRepository,
        service_name: str,
        version: str,
        started_at: datetime,
        interval_seconds: int = 30,
        metadata: dict | None = None,
    ) -> None:
        self.heartbeats = heartbeats
        self.service_name = service_name
        self.version = version
        self.started_at = started_at
        self.interval_seconds = interval_seconds
        self.metadata = metadata or {}
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self.write(status="ok")
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    def write(self, *, status: str = "ok", last_error: str | None = None) -> None:
        self.heartbeats.upsert(
            service_name=self.service_name,
            status=status,
            version=self.version,
            started_at=self.started_at,
            last_error=last_error,
            metadata=self.metadata,
        )

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            try:
                self.write(status="ok")
            except Exception:
                logger.exception("Failed to write heartbeat for %s", self.service_name)
