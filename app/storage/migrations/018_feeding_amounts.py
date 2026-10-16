import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    add_column_if_missing(connection, "feeding_events", "cups", "REAL")
    add_column_if_missing(connection, "feeding_events", "mix_kg", "REAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feeding_event_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            kg REAL NOT NULL CHECK(kg >= 0),
            stock_item_id INTEGER,
            stock_transaction_id INTEGER,
            FOREIGN KEY(event_id) REFERENCES feeding_events(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_feeding_event_items_event
        ON feeding_event_items(event_id)
        """
    )
    # Per-user "my usual mix": composition in cups (parts), cup volume, last amount given.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feeding_settings (
            user_id INTEGER PRIMARY KEY,
            cup_liters REAL NOT NULL DEFAULT 1.0 CHECK(cup_liters > 0),
            mix_json TEXT,
            last_cups REAL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
