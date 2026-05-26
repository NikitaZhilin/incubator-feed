import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    add_column_if_missing(connection, "users", "notify_eggs", "INTEGER NOT NULL DEFAULT 1")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS egg_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            entry_date TEXT NOT NULL,
            eggs_count INTEGER NOT NULL CHECK(eggs_count >= 0),
            active_hens_count INTEGER NOT NULL DEFAULT 0 CHECK(active_hens_count >= 0),
            total_hens_count INTEGER NOT NULL DEFAULT 0 CHECK(total_hens_count >= 0),
            excluded_hens_count INTEGER NOT NULL DEFAULT 0 CHECK(excluded_hens_count >= 0),
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_egg_entries_user_date
        ON egg_entries(user_id, entry_date)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS hen_laying_exclusions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            bird_group_id INTEGER,
            hens_count INTEGER NOT NULL CHECK(hens_count > 0),
            reason TEXT NOT NULL,
            started_at TEXT NOT NULL,
            expected_until TEXT,
            actual_ended_at TEXT,
            note TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(bird_group_id) REFERENCES bird_groups(id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hen_laying_exclusions_user_active
        ON hen_laying_exclusions(user_id, is_active, started_at, expected_until)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS weather_settings (
            user_id INTEGER PRIMARY KEY,
            city TEXT NOT NULL DEFAULT 'Курск',
            latitude REAL,
            longitude REAL,
            provider TEXT NOT NULL DEFAULT 'manual',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_weather (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            weather_date TEXT NOT NULL,
            city TEXT NOT NULL,
            temperature_avg_c REAL,
            temperature_min_c REAL,
            temperature_max_c REAL,
            humidity_avg_percent REAL,
            precipitation_mm REAL,
            condition TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_weather_user_date
        ON daily_weather(user_id, weather_date)
        """
    )
