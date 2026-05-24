import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS incubation_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            species TEXT NOT NULL,
            eggs_count INTEGER NOT NULL CHECK(eggs_count > 0),
            start_date TEXT NOT NULL,
            title TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
            hatched_count INTEGER CHECK(hatched_count IS NULL OR hatched_count >= 0),
            completed_at TEXT,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK(hatched_count IS NULL OR hatched_count <= eggs_count)
        )
        """
    )
    add_column_if_missing(connection, "incubation_batches", "hatched_count", "INTEGER")
    add_column_if_missing(connection, "incubation_batches", "completed_at", "TEXT")
    add_column_if_missing(connection, "incubation_batches", "note", "TEXT NOT NULL DEFAULT ''")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_batches_user_active
        ON incubation_batches(user_id, is_active)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reminder_settings (
            user_id INTEGER PRIMARY KEY,
            is_enabled INTEGER NOT NULL DEFAULT 0 CHECK(is_enabled IN (0, 1)),
            hour INTEGER NOT NULL DEFAULT 9 CHECK(hour BETWEEN 0 AND 23),
            minute INTEGER NOT NULL DEFAULT 0 CHECK(minute BETWEEN 0 AND 59),
            last_sent_date TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            amount_kg REAL NOT NULL CHECK(amount_kg > 0),
            bird_count INTEGER NOT NULL CHECK(bird_count > 0),
            daily_per_bird_g REAL NOT NULL CHECK(daily_per_bird_g > 0),
            low_threshold_kg REAL NOT NULL DEFAULT 5 CHECK(low_threshold_kg >= 0),
            purchase_reminded_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    add_column_if_missing(connection, "feed_stocks", "purchase_reminded_at", "TEXT")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_feed_stocks_user
        ON feed_stocks(user_id)
        """
    )
