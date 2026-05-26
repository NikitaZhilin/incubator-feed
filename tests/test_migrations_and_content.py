from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.domain import CONTENT, DISCLAIMER_TEXT, PROFILES
from app.storage.database import Database


class MigrationsAndContentTest(unittest.TestCase):
    def test_clean_database_gets_mvp_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "clean.db")
            database.initialize()

            with database.connect() as connection:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                bird_group_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(bird_groups)").fetchall()
                }
                weather_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(daily_weather)").fetchall()
                }

        self.assertIn("schema_migrations", tables)
        self.assertIn("notification_log", tables)
        self.assertIn("analytics_events", tables)
        self.assertIn("feed_transactions", tables)
        self.assertIn("bird_groups", tables)
        self.assertIn("stock_items", tables)
        self.assertIn("stock_transactions", tables)
        self.assertIn("mix_productions", tables)
        self.assertIn("feeding_assignments", tables)
        self.assertIn("egg_entries", tables)
        self.assertIn("hen_laying_exclusions", tables)
        self.assertIn("weather_settings", tables)
        self.assertIn("group_kind", bird_group_columns)
        self.assertIn("hatched_at", bird_group_columns)
        self.assertIn("joined_at", bird_group_columns)
        self.assertIn("day_temperature_min_c", weather_columns)
        self.assertIn("night_temperature_min_c", weather_columns)
        self.assertIn("tomorrow_condition", weather_columns)

    def test_existing_database_is_migrated_without_dropping_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO users (user_id, username, first_name, last_name)
                    VALUES (1, 'legacy', 'Legacy', 'User')
                    """
                )
                connection.commit()
            finally:
                connection.close()

            database = Database(db_path)
            database.initialize()

            with database.connect() as migrated:
                user = migrated.execute(
                    "SELECT username, is_active, timezone FROM users WHERE user_id = 1"
                ).fetchone()

        self.assertEqual(user["username"], "legacy")
        self.assertEqual(user["is_active"], 1)
        self.assertEqual(user["timezone"], "Europe/Moscow")

    def test_legacy_reminder_settings_are_synced_to_users(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy_reminders.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE reminder_settings (
                        user_id INTEGER PRIMARY KEY,
                        is_enabled INTEGER NOT NULL DEFAULT 0,
                        hour INTEGER NOT NULL DEFAULT 9,
                        minute INTEGER NOT NULL DEFAULT 0,
                        last_sent_date TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO reminder_settings (user_id, is_enabled, hour, minute)
                    VALUES (7, 1, 8, 30)
                    """
                )
                connection.commit()
            finally:
                connection.close()

            database = Database(db_path)
            database.initialize()

            with database.connect() as migrated:
                row = migrated.execute(
                    """
                    SELECT notification_time, notify_incubation, notify_eggs
                    FROM users
                    WHERE user_id = 7
                    """
                ).fetchone()

        self.assertEqual(row["notification_time"], "08:30")
        self.assertEqual(row["notify_incubation"], 1)
        self.assertEqual(row["notify_eggs"], 1)

    def test_content_structure_is_valid(self) -> None:
        self.assertTrue(CONTENT["version"])
        self.assertIn("ветспециалистом", DISCLAIMER_TEXT)
        self.assertGreaterEqual(len(PROFILES), 5)
        for profile in PROFILES.values():
            self.assertLess(profile.turn_until_day, profile.lockdown_from_day)
            self.assertLess(profile.lockdown_from_day, profile.hatch_days + 1)
            self.assertTrue(profile.candle_days)


if __name__ == "__main__":
    unittest.main()
