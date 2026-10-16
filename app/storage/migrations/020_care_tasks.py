import sqlite3


def up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS care_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            title TEXT NOT NULL,
            interval_days INTEGER NOT NULL CHECK(interval_days > 0),
            next_due TEXT NOT NULL,
            last_done TEXT,
            reminded_on TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, code)
        )
        """
    )
