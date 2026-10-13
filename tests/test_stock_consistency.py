"""Regression tests for stock/feed arithmetic found during the logic audit."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app.services.feeds as feeds_service_module
import app.services.stock as stock_service_module
import app.storage.repositories.feeds as feeds_repo_module
import app.storage.repositories.stock as stock_repo_module
from app.services.feeds import FeedService
from app.services.stock import StockService
from app.storage.database import Database
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.stock import StockRepository

USER = 1
START = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


def frozen_clock(moment: datetime):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    modules = (feeds_service_module, stock_service_module, feeds_repo_module, stock_repo_module)
    patches = [patch.object(module, "datetime", Frozen) for module in modules]

    class Clock:
        def __enter__(self):
            for item in patches:
                item.start()

        def __exit__(self, *exc):
            for item in patches:
                item.stop()

    return Clock()


class StockConsistencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_dir.name) / "test.db")
        database.initialize()
        self.feeds = FeedRepository(database)
        self.stock = StockService(StockRepository(database), self.feeds)
        self.feed_service = FeedService(self.feeds, before_ration_change=self.stock.checkpoint_user)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _flock_with_mix(self, hens: int = 10):
        with frozen_clock(START):
            group = self.feed_service.create_bird_group(
                user_id=USER, name="Несушки", bird_count=hens, role="hens"
            )
            flock = self.feed_service.create_flock(
                user_id=USER, name="Стадо", member_group_ids=[group.id]
            )
            item = self.stock.add_purchase(
                user_id=USER, name="Смесь для кур", kind="finished_mix", amount_kg=30
            ).item
            self.stock.assign_flock_feed(user_id=USER, flock_id=flock.id, stock_item_id=item.id)
        return group, flock, item

    def test_changing_ration_keeps_eaten_feed(self) -> None:
        _, flock, item = self._flock_with_mix()
        day10 = START + timedelta(days=10)
        with frozen_clock(day10):
            self.stock.assign_flock_feed(
                user_id=USER, flock_id=flock.id, stock_item_id=item.id, reserve_percent=10
            )
        remaining = self.stock.estimate_item(item, now=day10 + timedelta(minutes=1)).remaining_kg
        self.assertAlmostEqual(remaining, 18.0, delta=0.05)

    def test_changing_bird_count_is_not_applied_retroactively(self) -> None:
        group, _, item = self._flock_with_mix()
        day10 = START + timedelta(days=10)
        with frozen_clock(day10):
            self.feed_service.update_bird_group(group_id=group.id, user_id=USER, bird_count=20)
        remaining = self.stock.estimate_item(item, now=day10 + timedelta(minutes=1)).remaining_kg
        self.assertAlmostEqual(remaining, 18.0, delta=0.05)
        later = self.stock.estimate_item(item, now=day10 + timedelta(days=5)).remaining_kg
        self.assertAlmostEqual(later, 18.0 - 5 * 2.4, delta=0.05)

    def test_group_cannot_join_two_flocks(self) -> None:
        group, _, _ = self._flock_with_mix()
        with self.assertRaises(ValueError):
            self.feed_service.create_flock(user_id=USER, name="Другое", member_group_ids=[group.id])

    def test_finished_mix_is_not_used_as_grain_ingredient(self) -> None:
        self.stock.add_purchase(user_id=USER, name="Смесь для кур", kind="finished_mix", amount_kg=50)

        plan = self.stock.plan_mix(user_id=USER, mix_count=1, grain_base="layer_grain_mix")

        grain = [item for item in plan.ingredients if "Зерновая" in item.name][0]
        self.assertIsNone(grain.stock_item_id)
        self.assertEqual(grain.available_kg, 0)

    def test_cyrillic_names_are_matched_case_insensitively(self) -> None:
        self.stock.add_purchase(user_id=USER, name="Пшеница", kind="ingredient", amount_kg=20)
        self.stock.add_purchase(user_id=USER, name="пшеница", kind="ingredient", amount_kg=10)

        estimates = self.stock.list_estimates(USER)

        self.assertEqual(len(estimates), 1)
        self.assertAlmostEqual(estimates[0].remaining_kg, 30.0)

    def test_legacy_feed_restock_adds_to_estimated_remaining(self) -> None:
        with frozen_clock(START):
            feed = self.feed_service.create_feed(
                user_id=USER, name="Комбикорм", amount_kg=50, bird_count=10,
                daily_per_bird_g=120, low_threshold_kg=5,
            )
        day20 = START + timedelta(days=20)
        with frozen_clock(day20):
            self.feed_service.add_feed_amount(feed_id=feed.id, user_id=USER, amount_kg=25)
        feed = self.feeds.get(feed.id, USER)
        self.assertAlmostEqual(FeedService.estimate(feed, now=day20).remaining_kg, 51.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
