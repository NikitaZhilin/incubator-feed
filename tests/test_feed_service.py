from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.feeds import FeedService
from app.storage.database import Database
from app.storage.repositories.feeds import FeedRepository


class FeedServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_dir.name) / "test.db")
        database.initialize()
        self.service = FeedService(FeedRepository(database))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_feed_estimate(self) -> None:
        feed = self.service.create_feed(
            user_id=1,
            name="ПК-1",
            amount_kg=40,
            bird_count=20,
            daily_per_bird_g=120,
            low_threshold_kg=5,
        )
        estimate = self.service.estimate(
            feed,
            now=feed.created_at + timedelta(days=3),
        )

        self.assertEqual(estimate.daily_usage_kg, 2.4)
        self.assertEqual(round(estimate.remaining_kg, 1), 32.8)
        self.assertEqual(estimate.days_left, 13)

    def test_due_purchase_reminder(self) -> None:
        feed = self.service.create_feed(
            user_id=1,
            name="Финиш",
            amount_kg=5,
            bird_count=10,
            daily_per_bird_g=100,
            low_threshold_kg=5,
        )

        due = self.service.list_due_purchase_reminders(datetime.now())
        self.assertEqual([item.feed.id for item in due], [feed.id])

        self.service.mark_purchase_reminded(feed.id, datetime.now())
        self.assertEqual(self.service.list_due_purchase_reminders(datetime.now()), [])

    def test_restock_resets_purchase_reminder(self) -> None:
        feed = self.service.create_feed(
            user_id=1,
            name="Зерносмесь",
            amount_kg=5,
            bird_count=10,
            daily_per_bird_g=100,
            low_threshold_kg=5,
        )
        self.service.mark_purchase_reminded(feed.id, datetime.now())

        updated = self.service.restock_feed(
            feed_id=feed.id,
            user_id=1,
            amount_kg=30,
        )

        self.assertIsNotNone(updated)
        self.assertEqual(updated.amount_kg, 30)
        self.assertIsNone(updated.purchase_reminded_at)
        self.assertEqual(self.service.list_due_purchase_reminders(datetime.now()), [])

    def test_feed_transactions_track_restock_and_writeoff(self) -> None:
        feed = self.service.create_feed(
            user_id=1,
            name="ПК-1",
            amount_kg=10,
            bird_count=10,
            daily_per_bird_g=100,
            low_threshold_kg=2,
        )

        self.service.add_feed_amount(feed_id=feed.id, user_id=1, amount_kg=5)
        self.service.write_off_feed(feed_id=feed.id, user_id=1, amount_kg=3)
        transactions = self.service.list_transactions(feed.id, 1)

        self.assertEqual([item.type for item in transactions[:2]], ["write_off", "restock"])
        self.assertEqual(transactions[0].balance_after_kg, 12)

    def test_bird_group_can_be_linked_and_changed(self) -> None:
        group = self.service.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=25,
            species="chicken",
        )

        feed = self.service.create_feed(
            user_id=1,
            name="ПК-1",
            amount_kg=50,
            bird_count=1,
            daily_per_bird_g=120,
            low_threshold_kg=5,
            bird_group_id=group.id,
        )

        self.assertEqual(feed.bird_group_id, group.id)
        self.assertEqual(feed.bird_count, 25)
        self.assertEqual(feed.bird_group_name, "Несушки")

        updated = self.service.update_feed(
            feed_id=feed.id,
            user_id=1,
            clear_bird_group=True,
        )

        self.assertIsNone(updated.bird_group_id)

    def test_invalid_non_finite_numbers_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.create_feed(
                user_id=1,
                name="ПК",
                amount_kg=float("nan"),
                bird_count=10,
                daily_per_bird_g=100,
                low_threshold_kg=5,
            )

    def test_feed_timestamps_are_timezone_safe(self) -> None:
        feed = self.service.create_feed(
            user_id=1,
            name="ПК-1",
            amount_kg=40,
            bird_count=20,
            daily_per_bird_g=120,
            low_threshold_kg=5,
        )

        aware_estimate = self.service.estimate(
            feed,
            now=datetime(2026, 5, 23, tzinfo=timezone.utc),
        )
        naive_estimate = self.service.estimate(
            feed,
            now=datetime(2026, 5, 23),
        )

        self.assertIsNotNone(feed.created_at.tzinfo)
        self.assertGreaterEqual(aware_estimate.remaining_kg, 0)
        self.assertGreaterEqual(naive_estimate.remaining_kg, 0)


if __name__ == "__main__":
    unittest.main()
