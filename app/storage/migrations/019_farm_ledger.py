import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    # Optional price paid for a purchase, in rubles, for the whole amount.
    add_column_if_missing(connection, "stock_transactions", "price_rub", "REAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS bird_losses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            bird_group_id INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            count INTEGER NOT NULL CHECK(count > 0),
            reason TEXT NOT NULL,
            occurred_on TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            group_archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_bird_losses_user_date ON bird_losses(user_id, occurred_on)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS egg_outflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('sold', 'given', 'eaten', 'incubated')),
            eggs_count INTEGER NOT NULL CHECK(eggs_count > 0),
            amount_rub REAL,
            occurred_on TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_egg_outflows_user_date ON egg_outflows(user_id, occurred_on)"
    )
