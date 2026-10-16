"""Multi-day egg collection: «вчера не собрал, сегодня собираю за 2 дня»."""

from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from app.services.eggs import EggService
from app.storage.database import Database
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository


class MultiDayCollectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_dir.name) / "t.db")
        database.initialize()
        self.service = EggService(EggRepository(database), FeedRepository(database))
        self.today = self.service.current_date()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_two_days_split_with_extra_egg_today(self) -> None:
        distribution = self.service.preview_multi_day_distribution(1, 19, days=2, today=self.today)
        self.service.record_multi_day_collection(1, 19, distribution)

        self.assertEqual(
            self.service.history(1, days=2, today=self.today),
            [(self.today, 10), (self.today - timedelta(days=1), 9)],
        )

    def test_existing_records_are_reported(self) -> None:
        yesterday = self.today - timedelta(days=1)
        self.service.record_entry(1, 5, entry_date=yesterday)

        recorded = self.service.already_recorded(1, [self.today, yesterday])

        self.assertEqual(recorded, {yesterday: 5})

    def test_future_collection_date_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "в будущем"):
            self.service.preview_multi_day_distribution(
                1, 10, days=2, today=self.today + timedelta(days=3)
            )

    def test_typo_in_total_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "опечатку"):
            self.service.preview_multi_day_distribution(1, 15000, days=2, today=self.today)

    def test_auto_period_uses_recent_laying_rate(self) -> None:
        # Summer: 20 eggs a day long ago. Autumn: 8 a day in the last weeks.
        for offset in range(60):
            self.service.record_entry(1, 20, entry_date=self.today - timedelta(days=120 + offset))
        for offset in range(3, 13):
            self.service.record_entry(1, 8, entry_date=self.today - timedelta(days=offset))

        distribution = self.service.preview_multi_day_distribution(1, 24, today=self.today)

        # 24 eggs at 8 a day = 3 days; the all-time average (~17/day) would give 2.
        self.assertEqual(len(distribution), 3)
        self.assertEqual(sum(count for _, count in distribution), 24)


if __name__ == "__main__":
    unittest.main()
