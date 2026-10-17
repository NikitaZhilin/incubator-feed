import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    # Weighed cup of the home mix, kg; overrides the density-based estimate.
    add_column_if_missing(connection, "feeding_settings", "cup_kg", "REAL")
    # Why eggs of a finished batch did not hatch.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_losses (
            batch_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            infertile INTEGER NOT NULL DEFAULT 0 CHECK(infertile >= 0),
            dead_embryo INTEGER NOT NULL DEFAULT 0 CHECK(dead_embryo >= 0),
            not_hatched INTEGER NOT NULL DEFAULT 0 CHECK(not_hatched >= 0),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
