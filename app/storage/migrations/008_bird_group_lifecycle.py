import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    add_column_if_missing(
        connection,
        "bird_groups",
        "group_kind",
        "TEXT NOT NULL DEFAULT 'adult' CHECK(group_kind IN ('adult', 'chicks'))",
    )
    add_column_if_missing(connection, "bird_groups", "hatched_at", "TEXT")
    add_column_if_missing(connection, "bird_groups", "joined_at", "TEXT")
    add_column_if_missing(
        connection,
        "bird_groups",
        "reserve_percent",
        "REAL NOT NULL DEFAULT 0",
    )
    connection.execute(
        """
        UPDATE bird_groups
        SET group_kind = COALESCE(group_kind, 'adult'),
            reserve_percent = COALESCE(reserve_percent, 0)
        """
    )
