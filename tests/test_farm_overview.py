"""One-tap egg entry, flock age and incubation results."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import tempfile
import unittest

from app.domain import IncubationBatch
from app.services.farm_overview import (
    eggs_recorded_on,
    eggs_recorded_recently,
    eggs_to_set_for,
    flock_age_lines,
    incubation_results_lines,
    usual_egg_counts,
)
from app.services.eggs import EggService
from app.services.feeds import FeedService
from app.storage.database import Database
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository


TODAY = date(2026, 10, 17)


class FarmOverviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "t.db")
        self.database.initialize()
        self.feeds = FeedRepository(self.database)
        self.feed_service = FeedService(self.feeds)
        self.eggs = EggRepository(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _egg(self, day: date, count: int) -> None:
        self.eggs.create_entry(
            user_id=1, entry_date=day, eggs_count=count,
            active_hens_count=12, total_hens_count=12, excluded_hens_count=0,
        )

    def test_usual_counts_from_median(self) -> None:
        for offset, count in zip(range(1, 8), (10, 11, 9, 11, 30, 11, 10)):
            self._egg(TODAY - timedelta(days=offset), count)

        self.assertEqual(usual_egg_counts(self.eggs, 1, today=TODAY), [10, 11, 12])
        self.assertTrue(eggs_recorded_recently(self.eggs, 1, today=TODAY))
        self.assertFalse(eggs_recorded_on(self.eggs, 1, TODAY))
        self.assertEqual(usual_egg_counts(self.eggs, 2, today=TODAY), [])

    def test_flock_age_and_replacement(self) -> None:
        self.feed_service.create_bird_group(
            user_id=1, name="Старые", bird_count=10, role="hens", hatched_at=date(2023, 5, 1)
        )
        self.feed_service.create_bird_group(
            user_id=1, name="Молодые", bird_count=8, role="hens", hatched_at=date(2025, 5, 1)
        )
        self.feed_service.create_bird_group(user_id=1, name="Петухи", bird_count=2, role="roosters")

        text = "\n".join(flock_age_lines(self.feed_service.list_bird_groups(1), today=TODAY))

        self.assertIn("«Старые»: 10 шт., возраст 3 года — несутся уже заметно меньше", text)
        self.assertIn("«Молодые»: 8 шт., возраст 1 год.", text)
        self.assertIn(f"заложите примерно {eggs_to_set_for(10)} яиц", text)
        self.assertIn("Без даты вывода: «Петухи»", text)
        self.assertEqual(eggs_to_set_for(10), 29)

    def test_incubation_results(self) -> None:
        batches = [
            IncubationBatch(1, 1, "chicken", 30, date(2026, 3, 1), "Весна", False, 24),
            IncubationBatch(2, 1, "chicken", 20, date(2026, 6, 1), "Лето", False, 9),
            IncubationBatch(3, 1, "quail", 40, date(2026, 7, 1), "Перепела", False, 30),
            IncubationBatch(4, 1, "chicken", 12, date(2026, 10, 1), "Идёт", True, None),
        ]

        text = "\n".join(incubation_results_lines(batches, {"chicken": "Куры", "quail": "Перепела"}))

        self.assertIn("Куры: 2 парт., заложено 50, вывелось 33 (66%)", text)
        self.assertIn("Перепела: 1 парт.", text)
        self.assertIn("Лучшая партия — «Весна» (80%), худшая — «Лето» (45%)", text)
        self.assertNotIn("Идёт", text)
        self.assertIn("пока нет", "\n".join(incubation_results_lines([], {})))


@unittest.skipUnless(importlib.util.find_spec("aiogram"), "aiogram is not installed")
class EggEntryReminderTest(FarmOverviewTest):
    def test_evening_reminder_once_and_quick_record(self) -> None:
        from app.handlers.quick import eggs_quick
        from app.keyboards.menu import main_menu_keyboard
        from app.services.incubation import IncubationService
        from app.services.reminders import ReminderRunner
        from app.storage.repositories.batches import BatchRepository
        from app.storage.repositories.notifications import NotificationRepository
        from app.storage.repositories.users import UserRepository

        self.feed_service.create_bird_group(user_id=1, name="Несушки", bird_count=12, role="hens")
        for offset in range(1, 5):
            self._egg(TODAY - timedelta(days=offset), 10)
        users = UserRepository(self.database)
        users.upsert(user_id=1, first_name="Никита")
        egg_service = EggService(self.eggs, self.feeds, timezone_name="Europe/Moscow")

        class Bot:
            def __init__(self) -> None:
                self.sent = []

            async def send_message(self, user_id, text, reply_markup=None) -> None:
                self.sent.append((text, reply_markup))

        bot = Bot()
        runner = ReminderRunner(
            bot=bot,
            incubation_service=IncubationService(BatchRepository(self.database)),
            egg_service=egg_service,
            users=users,
            notifications=NotificationRepository(self.database),
            timezone="Europe/Moscow",
        )
        evening = datetime(2026, 10, 17, 17, 5, tzinfo=timezone.utc)  # 20:05 Moscow
        asyncio.run(runner._send_egg_entry_reminders(evening - timedelta(hours=2)))  # 18:05: too early
        asyncio.run(runner._send_egg_entry_reminders(evening))
        asyncio.run(runner._send_egg_entry_reminders(evening + timedelta(minutes=30)))

        self.assertEqual(len(bot.sent), 1)
        callbacks = [b.callback_data for row in bot.sent[0][1].inline_keyboard for b in row]
        self.assertIn("eggs:quick:2026-10-17:10", callbacks)

        texts = [b.text for row in main_menu_keyboard({}).inline_keyboard for b in row]
        self.assertEqual(texts[:4], ["✅ Покормил", "🥚 Собрал яйца", "📤 Продал / отдал", "🗓 Уход"])


if __name__ == "__main__":
    unittest.main()
