import sqlite3


def up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('ingredient', 'finished_mix', 'commercial_feed', 'other')),
            unit TEXT NOT NULL DEFAULT 'kg',
            low_threshold_kg REAL NOT NULL DEFAULT 5 CHECK(low_threshold_kg >= 0),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, name)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stock_items_user
        ON stock_items(user_id, is_active, kind)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS mix_productions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            recipe_code TEXT NOT NULL,
            recipe_version TEXT NOT NULL,
            mix_count REAL NOT NULL CHECK(mix_count > 0),
            output_stock_item_id INTEGER NOT NULL,
            output_kg REAL NOT NULL CHECK(output_kg > 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(output_stock_item_id) REFERENCES stock_items(id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stock_item_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN (
                'purchase', 'mix_input', 'mix_output', 'manual_adjustment', 'write_off'
            )),
            amount_kg REAL NOT NULL,
            balance_after_kg REAL NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            related_mix_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(stock_item_id) REFERENCES stock_items(id),
            FOREIGN KEY(related_mix_id) REFERENCES mix_productions(id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stock_transactions_item
        ON stock_transactions(stock_item_id, created_at DESC, id DESC)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS mix_production_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mix_production_id INTEGER NOT NULL,
            ingredient_stock_item_id INTEGER NOT NULL,
            ingredient_name TEXT NOT NULL,
            amount_kg REAL NOT NULL CHECK(amount_kg > 0),
            FOREIGN KEY(mix_production_id) REFERENCES mix_productions(id),
            FOREIGN KEY(ingredient_stock_item_id) REFERENCES stock_items(id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feeding_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            bird_group_id INTEGER NOT NULL,
            stock_item_id INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ended_at TEXT,
            daily_per_bird_g REAL NOT NULL DEFAULT 120 CHECK(daily_per_bird_g > 0),
            reserve_percent REAL NOT NULL DEFAULT 0 CHECK(reserve_percent >= 0),
            FOREIGN KEY(bird_group_id) REFERENCES bird_groups(id),
            FOREIGN KEY(stock_item_id) REFERENCES stock_items(id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_feeding_assignments_user
        ON feeding_assignments(user_id, is_active)
        """
    )
