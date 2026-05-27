from __future__ import annotations

from datetime import datetime, timezone
import json

from app.storage.database import Database


class HeartbeatRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(
        self,
        *,
        service_name: str,
        status: str,
        version: str,
        started_at: datetime,
        last_seen_at: datetime | None = None,
        uptime_seconds: int | None = None,
        last_error: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if status not in {"ok", "degraded", "down"}:
            raise ValueError("Unknown heartbeat status.")
        seen_at = last_seen_at or datetime.now(timezone.utc)
        if seen_at.tzinfo is None:
            seen_at = seen_at.replace(tzinfo=timezone.utc)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        uptime = uptime_seconds
        if uptime is None:
            uptime = max(int((seen_at - started_at).total_seconds()), 0)

        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO service_heartbeats (
                    service_name, status, version, started_at, last_seen_at,
                    uptime_seconds, last_error, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_name) DO UPDATE SET
                    status = excluded.status,
                    version = excluded.version,
                    started_at = excluded.started_at,
                    last_seen_at = excluded.last_seen_at,
                    uptime_seconds = excluded.uptime_seconds,
                    last_error = excluded.last_error,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    service_name[:80],
                    status,
                    version,
                    started_at.isoformat(),
                    seen_at.isoformat(),
                    int(uptime),
                    last_error[:500] if last_error else None,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                ),
            )

    def list_all(self) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT service_name, status, version, started_at, last_seen_at,
                       uptime_seconds, last_error, metadata_json, created_at, updated_at
                FROM service_heartbeats
                ORDER BY service_name
                """
            ).fetchall()
        return [dict(row) for row in rows]
