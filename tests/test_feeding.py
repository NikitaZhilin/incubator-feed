"""«Покормил»: one-tap feeding log with the usual mix."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.feeding import FeedingService, format_feeding_status
from app.services.feeds import FeedService
from app.services.stock import StockService
from app.storage.database import Database
from app.storage.repositories.feeding import FeedingRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.stock import StockRepository


# 09:00 Moscow on 16 October 2026.
MORNING = datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)


class FeedingServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "t.db")
        self.database.initialize()
        self.feeds = FeedRepository(self.database)
        groups = FeedService(self.feeds)
        groups.create_bird_group(user_id=1, name="Несушки", bird_count=14, role="hens")
        groups.create_bird_group(user_id=1, name="Петухи", bird_count=2, role="roosters")
        groups.create_bird_group(
            user_id=1, name="Цыплята", bird_count=8, group_kind="chicks", hatched_at=date(2026, 10, 6)
        )
        self.service = FeedingService(FeedingRepository(self.database), self.feeds)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_norm_uses_the_same_rates_as_the_bot(self) -> None:
        norm = self.service.daily_norm(1, on_date=date(2026, 10, 16))

        # 14 * 120 + 2 * 150 + 8 chicks aged 10 days * 25 g = 2180 g
        self.assertEqual(norm.bird_count, 24)
        self.assertAlmostEqual(norm.daily_kg, 2.18)

    def test_double_tap_counts_once(self) -> None:
        first = self.service.record(1, now=MORNING)
        second = self.service.record(1, now=MORNING + timedelta(seconds=20))
        evening = self.service.record(1, now=MORNING + timedelta(hours=9))

        self.assertFalse(first.duplicate)
        self.assertTrue(second.duplicate)
        self.assertEqual(second.event.id, first.event.id)
        self.assertEqual(evening.feedings_today, 2)

    def test_week_counts_days_and_norm_not_presses(self) -> None:
        for offset in (0, 1, 3):
            self.service.record(1, now=MORNING - timedelta(days=offset))
        self.service.record(1, now=MORNING + timedelta(hours=8))  # second feeding today

        week = self.service.week(1, today=date(2026, 10, 16))

        self.assertEqual(week.fed_days, 3)
        # Two days at 2.18 kg; three days ago the chicks were 7 days old (15 g each): 2.10 kg.
        self.assertAlmostEqual(week.estimated_kg, 2.18 + 2.18 + 2.10, places=2)

    def test_status_line_and_undo(self) -> None:
        result = self.service.record(1, now=MORNING)

        self.assertIn("✅ 09:00", format_feeding_status(self.service, 1, now=MORNING))
        self.assertTrue(self.service.undo(1, result.event.id))
        self.assertIn("ещё не отмечено", format_feeding_status(self.service, 1, now=MORNING))

    def test_evening_reminder_only_for_users_of_the_button(self) -> None:
        evening = datetime(2026, 10, 16, 17, 0, tzinfo=timezone.utc)  # 20:00 Moscow

        self.assertFalse(self.service.needs_evening_reminder(1, now=evening))

        self.service.record(1, now=MORNING - timedelta(days=1))
        self.assertTrue(self.service.needs_evening_reminder(1, now=evening))
        self.assertFalse(self.service.needs_evening_reminder(1, now=MORNING))

        self.service.record(1, now=MORNING)
        self.assertFalse(self.service.needs_evening_reminder(1, now=evening))

    def test_feeding_does_not_touch_the_warehouse(self) -> None:
        stock = StockService(StockRepository(self.database), self.feeds)
        mix = stock.add_purchase(user_id=1, name="Смесь для кур", kind="finished_mix", amount_kg=30)

        self.service.record(1, now=MORNING)

        self.assertEqual(len(stock.list_history(1)), 1)
        self.assertEqual(stock.estimate_item(mix.item).remaining_kg, 30)


if __name__ == "__main__":
    unittest.main()
