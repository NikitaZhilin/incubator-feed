from datetime import date, datetime, timedelta, timezone
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

    def test_feed_estimate_uses_separate_hen_and_rooster_rates(self) -> None:
        feed = self.service.create_feed(
            user_id=1,
            name="Layer mix",
            amount_kg=40,
            bird_count=12,
            daily_per_bird_g=120,
            low_threshold_kg=5,
            hen_count=10,
            rooster_count=2,
            hen_daily_g=115,
            rooster_daily_g=150,
        )

        estimate = self.service.estimate(feed, now=feed.created_at + timedelta(days=2))

        self.assertEqual(feed.bird_count, 12)
        self.assertEqual(feed.hen_count, 10)
        self.assertEqual(feed.rooster_count, 2)
        self.assertEqual(round(estimate.daily_usage_kg, 2), 1.45)
        self.assertEqual(round(estimate.remaining_kg, 1), 37.1)

    def test_feeds_and_flocks_are_isolated_by_telegram_user(self) -> None:
        group = self.service.create_bird_group(
            user_id=1,
            name="Основное стадо",
            bird_count=12,
            species="chicken",
        )
        feed = self.service.create_feed(
            user_id=1,
            name="Зерносмесь",
            amount_kg=40,
            bird_count=12,
            daily_per_bird_g=120,
            low_threshold_kg=5,
            bird_group_id=group.id,
            hen_count=10,
            rooster_count=2,
        )

        self.assertEqual([item.feed.id for item in self.service.list_user_estimates(1)], [feed.id])
        self.assertEqual(self.service.list_user_estimates(2), [])
        self.assertIsNone(self.service.get_estimate(feed.id, 2))
        self.assertEqual(self.service.list_bird_groups(2), [])

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
            hen_count=25,
            rooster_count=0,
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

    def test_changing_bird_group_syncs_feed_counts(self) -> None:
        first_group = self.service.create_bird_group(
            user_id=1,
            name="Молодки",
            bird_count=12,
            species="chicken",
        )
        second_group = self.service.create_bird_group(
            user_id=1,
            name="Основное стадо",
            bird_count=30,
            species="chicken",
        )
        feed = self.service.create_feed(
            user_id=1,
            name="Зерносмесь",
            amount_kg=50,
            bird_count=12,
            daily_per_bird_g=120,
            low_threshold_kg=5,
            bird_group_id=first_group.id,
            hen_count=10,
            rooster_count=2,
        )

        updated = self.service.update_feed(
            feed_id=feed.id,
            user_id=1,
            bird_group_id=second_group.id,
            bird_count=second_group.bird_count,
        )

        self.assertEqual(updated.bird_group_id, second_group.id)
        self.assertEqual(updated.bird_count, 30)
        self.assertEqual(updated.hen_count, 30)
        self.assertEqual(updated.rooster_count, 0)

    def test_chick_group_uses_age_based_feed_rate_with_reserve(self) -> None:
        group = self.service.create_bird_group(
            user_id=1,
            name="Цыплята май",
            bird_count=10,
            species="chicken",
            group_kind="chicks",
            hatched_at=date(2026, 5, 1),
            joined_at=date(2026, 6, 1),
            reserve_percent=10,
        )
        feed = self.service.create_feed(
            user_id=1,
            name="Старт для цыплят",
            amount_kg=10,
            bird_count=10,
            daily_per_bird_g=15,
            low_threshold_kg=2,
            bird_group_id=group.id,
            hen_count=10,
            rooster_count=0,
        )

        estimate = self.service.estimate(
            feed,
            now=datetime(2026, 5, 11, tzinfo=timezone.utc),
        )
        joined_estimate = self.service.estimate(
            feed,
            now=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )

        self.assertEqual(feed.bird_group_kind, "chicks")
        self.assertEqual(round(estimate.daily_usage_kg, 3), 0.275)
        self.assertEqual(joined_estimate.daily_usage_kg, 0)

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
