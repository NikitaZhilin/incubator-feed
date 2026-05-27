import sqlite3


def up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS service_heartbeats (
            service_name TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('ok', 'degraded', 'down')),
            version TEXT NOT NULL,
            started_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            uptime_seconds INTEGER NOT NULL,
            last_error TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_service_heartbeats_last_seen
        ON service_heartbeats(last_seen_at)
        """
    )
