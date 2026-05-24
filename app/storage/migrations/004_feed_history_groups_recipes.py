import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS bird_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            bird_count INTEGER NOT NULL CHECK(bird_count > 0),
            species TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bird_groups_user
        ON bird_groups(user_id, is_active)
        """
    )
    add_column_if_missing(connection, "feed_stocks", "bird_group_id", "INTEGER")
    add_column_if_missing(connection, "feed_stocks", "is_archived", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(connection, "feed_stocks", "archived_at", "TEXT")
    add_column_if_missing(connection, "feed_stocks", "updated_at", "TEXT")
    connection.execute(
        """
        UPDATE feed_stocks
        SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('initial', 'restock', 'write_off', 'adjustment')),
            amount_kg REAL NOT NULL,
            balance_after_kg REAL NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(feed_id) REFERENCES feed_stocks(id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_feed_transactions_feed
        ON feed_transactions(feed_id, created_at DESC)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            version TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_recipe_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            parts REAL NOT NULL CHECK(parts > 0),
            density_kg_per_l REAL NOT NULL CHECK(density_kg_per_l > 0),
            group_name TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(recipe_id) REFERENCES feed_recipes(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO feed_transactions (feed_id, user_id, type, amount_kg, balance_after_kg, note, created_at)
        SELECT id, user_id, 'initial', amount_kg, amount_kg, 'Начальный остаток до миграции', created_at
        FROM feed_stocks
        """
    )
