import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    add_column_if_missing(connection, "users", "timezone", "TEXT NOT NULL DEFAULT 'Europe/Moscow'")
    add_column_if_missing(connection, "users", "notification_time", "TEXT NOT NULL DEFAULT '09:00'")
    add_column_if_missing(connection, "users", "notify_incubation", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing(connection, "users", "notify_feed", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing(connection, "users", "notify_post_hatch_care", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing(connection, "users", "notify_service", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing(connection, "users", "units", "TEXT NOT NULL DEFAULT 'metric'")
    add_column_if_missing(connection, "users", "farm_name", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(connection, "users", "is_active", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing(connection, "users", "inactive_reason", "TEXT")
    add_column_if_missing(connection, "users", "deactivated_at", "TEXT")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_users_active_seen
        ON users(is_active, last_seen_at)
        """
    )
