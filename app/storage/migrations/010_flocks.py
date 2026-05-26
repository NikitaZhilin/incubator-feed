import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    add_column_if_missing(connection, "bird_groups", "role", "TEXT NOT NULL DEFAULT 'mixed'")
    connection.execute(
        """
        UPDATE bird_groups
        SET role = CASE
            WHEN group_kind = 'chicks' THEN 'chicks'
            ELSE COALESCE(NULLIF(role, ''), 'mixed')
        END
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS flocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_flocks_user
        ON flocks(user_id, is_active)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS flock_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            flock_id INTEGER NOT NULL,
            bird_group_id INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            left_at TEXT,
            FOREIGN KEY(flock_id) REFERENCES flocks(id),
            FOREIGN KEY(bird_group_id) REFERENCES bird_groups(id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_flock_members_flock
        ON flock_members(flock_id, is_active)
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_flock_members_active_unique
        ON flock_members(flock_id, bird_group_id)
        WHERE is_active = 1
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS flock_feed_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            flock_id INTEGER NOT NULL,
            stock_item_id INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            share_percent REAL NOT NULL DEFAULT 100 CHECK(share_percent > 0),
            daily_per_hen_g REAL NOT NULL DEFAULT 120 CHECK(daily_per_hen_g > 0),
            daily_per_rooster_g REAL NOT NULL DEFAULT 150 CHECK(daily_per_rooster_g > 0),
            daily_per_adult_g REAL NOT NULL DEFAULT 120 CHECK(daily_per_adult_g > 0),
            reserve_percent REAL NOT NULL DEFAULT 0 CHECK(reserve_percent >= 0),
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ended_at TEXT,
            FOREIGN KEY(flock_id) REFERENCES flocks(id),
            FOREIGN KEY(stock_item_id) REFERENCES stock_items(id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_flock_feed_assignments_user
        ON flock_feed_assignments(user_id, is_active)
        """
    )
