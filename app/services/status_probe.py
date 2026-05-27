from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from app.version import APP_VERSION


REQUIRED_SERVICES = ("polling_bot", "reminder_runner")
HEARTBEAT_DOWN_AFTER_SECONDS = 120


def build_status_report(
    db_path: Path,
    *,
    now: datetime | None = None,
    heartbeat_down_after_seconds: int = HEARTBEAT_DOWN_AFTER_SECONDS,
) -> dict:
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    try:
        with closing(_connect_read_only(db_path)) as connection:
            heartbeats = _read_heartbeats(connection, generated_at, heartbeat_down_after_seconds)
            users_total = _count_rows(connection, "users")
            critical_total, recent_errors = _read_critical_errors(connection)
    except Exception as exc:
        return {
            "status": "probe_error",
            "version": APP_VERSION,
            "generated_at": generated_at.isoformat(),
            "db": {
                "status": "error",
                "path": str(db_path),
                "last_error": str(exc),
            },
            "users": {"total": 0},
            "errors": {"critical_total": 0, "recent": []},
            "heartbeat_down_after_seconds": heartbeat_down_after_seconds,
            "heartbeats": [],
        }

    overall_status = _overall_status(heartbeats, critical_total)
    return {
        "status": overall_status,
        "version": _report_version(heartbeats),
        "generated_at": generated_at.isoformat(),
        "db": {
            "status": "ok",
            "path": str(db_path),
            "last_error": None,
        },
        "users": {"total": users_total},
        "errors": {
            "critical_total": critical_total,
            "recent": recent_errors,
        },
        "heartbeat_down_after_seconds": heartbeat_down_after_seconds,
        "heartbeats": heartbeats,
    }


def status_exit_code(report: dict) -> int:
    if report.get("db", {}).get("status") != "ok":
        return 2
    return 0 if report.get("status") == "ok" else 1


def _connect_read_only(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _read_heartbeats(
    connection: sqlite3.Connection,
    now: datetime,
    heartbeat_down_after_seconds: int,
) -> list[dict]:
    rows = connection.execute(
        """
        SELECT service_name, status, version, started_at, last_seen_at,
               uptime_seconds, last_error, metadata_json
        FROM service_heartbeats
        """
    ).fetchall()
    by_service = {str(row["service_name"]): row for row in rows}
    heartbeats: list[dict] = []
    for service_name in REQUIRED_SERVICES:
        row = by_service.get(service_name)
        if row is None:
            heartbeats.append(
                {
                    "service_name": service_name,
                    "status": "down",
                    "required": True,
                    "stale": True,
                    "seconds_since_seen": None,
                    "version": "",
                    "started_at": None,
                    "last_seen_at": None,
                    "uptime_seconds": 0,
                    "last_error": "heartbeat отсутствует",
                    "metadata": {},
                }
            )
            continue
        last_seen_at = _parse_datetime(str(row["last_seen_at"]))
        seconds_since_seen = max(int((now - last_seen_at).total_seconds()), 0)
        stale = seconds_since_seen > heartbeat_down_after_seconds
        status = str(row["status"])
        if stale:
            status = "down"
        heartbeats.append(
            {
                "service_name": service_name,
                "status": status,
                "required": True,
                "stale": stale,
                "seconds_since_seen": seconds_since_seen,
                "version": str(row["version"]),
                "started_at": str(row["started_at"]),
                "last_seen_at": str(row["last_seen_at"]),
                "uptime_seconds": int(row["uptime_seconds"]),
                "last_error": str(row["last_error"]) if row["last_error"] else None,
                "metadata": _decode_metadata(row["metadata_json"]),
            }
        )
    return heartbeats


def _read_critical_errors(connection: sqlite3.Connection) -> tuple[int, list[dict]]:
    total = _count_rows(connection, "critical_errors")
    rows = connection.execute(
        """
        SELECT source, message, created_at
        FROM critical_errors
        ORDER BY created_at DESC
        LIMIT 5
        """
    ).fetchall()
    return total, [dict(row) for row in rows]


def _count_rows(connection: sqlite3.Connection, table_name: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS c FROM {table_name}").fetchone()
    return int(row["c"] or 0)


def _overall_status(heartbeats: list[dict], critical_total: int) -> str:
    if any(item["status"] == "down" or item["stale"] for item in heartbeats):
        return "down"
    if critical_total > 0:
        return "degraded"
    if any(item["status"] == "degraded" or item["last_error"] for item in heartbeats):
        return "degraded"
    return "ok"


def _report_version(heartbeats: list[dict]) -> str:
    for item in heartbeats:
        if item.get("version"):
            return str(item["version"])
    return APP_VERSION


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decode_metadata(value: str | None) -> dict:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}
