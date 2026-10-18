import sqlite3


def up(connection: sqlite3.Connection) -> None:
    # Where eggs are kept at home: fridge door, trays, shelves...
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS egg_places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            capacity INTEGER CHECK(capacity IS NULL OR capacity > 0),
            priority INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Eggs of one laying day in one place; count goes down as eggs are used.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS egg_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            place_id INTEGER NOT NULL,
            laid_on TEXT NOT NULL,
            count INTEGER NOT NULL CHECK(count >= 0),
            entry_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_egg_lots_user_place ON egg_lots(user_id, place_id, laid_on)")
    # What an «eggs out» record took from storage, so undo can put it back.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS egg_takes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            outflow_id INTEGER NOT NULL,
            place_id INTEGER NOT NULL,
            laid_on TEXT NOT NULL,
            count INTEGER NOT NULL CHECK(count > 0)
        )
        """
    )
