import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    add_column_if_missing(connection, "feed_stocks", "hen_count", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(connection, "feed_stocks", "rooster_count", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(connection, "feed_stocks", "hen_daily_g", "REAL")
    add_column_if_missing(connection, "feed_stocks", "rooster_daily_g", "REAL")
    connection.execute(
        """
        UPDATE feed_stocks
        SET hen_count = CASE
                WHEN COALESCE(hen_count, 0) = 0 AND COALESCE(rooster_count, 0) = 0
                THEN bird_count
                ELSE hen_count
            END,
            rooster_count = COALESCE(rooster_count, 0),
            hen_daily_g = COALESCE(hen_daily_g, daily_per_bird_g),
            rooster_daily_g = COALESCE(rooster_daily_g, daily_per_bird_g)
        """
    )
