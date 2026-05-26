from __future__ import annotations

from importlib import import_module
import sqlite3
from typing import Protocol


MIGRATIONS = (
    "001_initial",
    "002_notification_log",
    "003_user_settings",
    "004_feed_history_groups_recipes",
    "005_analytics",
    "006_sync_user_notification_settings",
    "007_feed_gender_counts",
    "008_bird_group_lifecycle",
    "009_stock_warehouse",
    "010_flocks",
    "011_eggs",
    "012_weather_parts",
)


class DatabaseLike(Protocol):
    def connect(self) -> sqlite3.Connection:
        ...


def run_migrations(database: DatabaseLike) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied = {
            str(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }

    for version in MIGRATIONS:
        if version in applied:
            continue
        module = import_module(f"app.storage.migrations.{version}")
        with database.connect() as connection:
            connection.execute("BEGIN")
            try:
                module.up(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)",
                    (version,),
                )
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()


def add_column_if_missing(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
