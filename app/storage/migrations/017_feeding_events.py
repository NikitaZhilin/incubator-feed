import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feeding_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fed_at TEXT NOT NULL,
            fed_date TEXT NOT NULL,
            bird_count INTEGER NOT NULL DEFAULT 0,
            daily_norm_kg REAL NOT NULL DEFAULT 0 CHECK(daily_norm_kg >= 0),
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_feeding_events_user_date
        ON feeding_events(user_id, fed_date)
        """
    )
    add_column_if_missing(
        connection,
        "users",
        "notify_feeding",
        "INTEGER NOT NULL DEFAULT 1",
    )
