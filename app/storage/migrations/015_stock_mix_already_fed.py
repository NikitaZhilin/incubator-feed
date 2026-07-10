import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    add_column_if_missing(
        connection,
        "mix_productions",
        "mode",
        "TEXT NOT NULL DEFAULT 'to_stock'",
    )
    add_column_if_missing(
        connection,
        "mix_productions",
        "produced_at",
        "TEXT",
    )
    add_column_if_missing(
        connection,
        "stock_transactions",
        "occurred_at",
        "TEXT",
    )
    connection.execute(
        """
        UPDATE mix_productions
        SET produced_at = created_at
        WHERE produced_at IS NULL AND mode = 'to_stock'
        """
    )
    connection.execute(
        """
        UPDATE stock_transactions
        SET occurred_at = created_at
        WHERE occurred_at IS NULL
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stock_transactions_occurred
        ON stock_transactions(user_id, occurred_at DESC, id DESC)
        """
    )
