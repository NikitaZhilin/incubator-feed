import sqlite3


def up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            batch_id INTEGER,
            feed_id INTEGER,
            type TEXT NOT NULL,
            event_key TEXT NOT NULL UNIQUE,
            scheduled_for TEXT NOT NULL,
            sent_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error_code TEXT,
            error_message TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notification_log_user_type
        ON notification_log(user_id, type, status)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notification_log_created
        ON notification_log(created_at)
        """
    )
