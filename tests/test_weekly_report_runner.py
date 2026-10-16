"""The weekly report goes out once, on Sunday evening."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec("aiogram"), "aiogram is not installed")
class WeeklyReportRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        from app.services.eggs import EggService
        from app.services.incubation import IncubationService
        from app.services.reminders import ReminderRunner
        from app.storage.database import Database
        from app.storage.repositories.batches import BatchRepository
        from app.storage.repositories.eggs import EggRepository
        from app.storage.repositories.feeds import FeedRepository
        from app.storage.repositories.notifications import NotificationRepository
        from app.storage.repositories.users import UserRepository

        self.temp_dir = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_dir.name) / "t.db")
        database.initialize()
        users = UserRepository(database)
        users.upsert(user_id=1, first_name="Никита")
        self.users = users

        class Bot:
            def __init__(self) -> None:
                self.messages: list[str] = []

            async def send_message(self, user_id, text, reply_markup=None) -> None:
                self.messages.append(text)

        self.bot = Bot()
        self.runner = ReminderRunner(
            bot=self.bot,
            incubation_service=IncubationService(BatchRepository(database)),
            egg_service=EggService(EggRepository(database), FeedRepository(database), timezone_name="Europe/Moscow"),
            users=users,
            notifications=NotificationRepository(database),
            timezone="Europe/Moscow",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _run(self, moment: datetime) -> None:
        asyncio.run(self.runner._send_weekly_reports(moment))

    def test_sunday_evening_once(self) -> None:
        self._run(datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc))  # Sunday 19:00 Moscow: too early
        self._run(datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc))  # Saturday 21:00
        self.assertEqual(self.bot.messages, [])

        self._run(datetime(2026, 10, 18, 17, 1, tzinfo=timezone.utc))  # Sunday 20:01
        self._run(datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc))

        self.assertEqual(len(self.bot.messages), 1)
        self.assertIn("Итоги недели 12.10–18.10", self.bot.messages[0])

    def test_off_with_daily_summary(self) -> None:
        self.users.update_settings(1, notify_daily_summary=False)
        self._run(datetime(2026, 10, 18, 17, 1, tzinfo=timezone.utc))
        self.assertEqual(self.bot.messages, [])


if __name__ == "__main__":
    unittest.main()
