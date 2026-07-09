import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    add_column_if_missing(
        connection,
        "users",
        "notify_poultry_advisor",
        "INTEGER NOT NULL DEFAULT 1",
    )
