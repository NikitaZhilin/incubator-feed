from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.stock import StockService
from app.storage.database import Database
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.stock import StockRepository


class StockServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.db")
        self.database.initialize()
        self.feeds = FeedRepository(self.database)
        self.service = StockService(StockRepository(self.database), self.feeds)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_purchase_creates_stock_item_and_estimate(self) -> None:
        estimate = self.service.add_purchase(
            user_id=1,
            name="Кукуруза",
            kind="ingredient",
            amount_kg=50,
        )

        self.assertEqual(estimate.item.name, "Кукуруза")
        self.assertEqual(estimate.remaining_kg, 50)
        self.assertEqual(self.service.list_estimates(2), [])

    def test_mix_consumes_ingredients_and_adds_finished_mix(self) -> None:
        for name in [
            "Кукуруза",
            "Пшеница",
            "Ячмень",
            "Комбикорм",
            "Мясокостная мука",
            "Рыбная мука",
            "Ракушка",
            "Премикс",
        ]:
            self.service.add_purchase(
                user_id=1,
                name=name,
                kind="ingredient",
                amount_kg=100,
            )

        plan = self.service.produce_mix(user_id=1, mix_count=3)
        estimates = {item.item.name: item for item in self.service.list_estimates(1)}

        self.assertTrue(plan.can_produce)
        self.assertGreater(estimates["Смесь для кур"].remaining_kg, 20)
        self.assertLess(estimates["Кукуруза"].remaining_kg, 100)

    def test_mix_reports_missing_ingredients(self) -> None:
        self.service.add_purchase(
            user_id=1,
            name="Кукуруза",
            kind="ingredient",
            amount_kg=1,
        )

        plan = self.service.plan_mix(user_id=1, mix_count=3)

        self.assertFalse(plan.can_produce)
        self.assertGreater(
            sum(item.missing_kg for item in plan.ingredients),
            0,
        )

    def test_finished_mix_decreases_dynamically_by_assignment(self) -> None:
        group = self.feeds.create_bird_group(
            user_id=1,
            name="Основное стадо",
            bird_count=10,
            species="chicken",
        )
        estimate = self.service.add_purchase(
            user_id=1,
            name="Смесь для кур",
            kind="finished_mix",
            amount_kg=20,
        )
        self.service.assign_feed(
            user_id=1,
            bird_group_id=group.id,
            stock_item_id=estimate.item.id,
            daily_per_bird_g=120,
        )

        later = self.service.estimate_item(
            estimate.item,
            now=estimate.item.created_at + timedelta(days=2),
        )

        self.assertEqual(round(later.daily_usage_kg, 1), 1.2)
        self.assertEqual(round(later.remaining_kg, 1), 17.6)

    def test_adjustment_resets_dynamic_baseline(self) -> None:
        group = self.feeds.create_bird_group(
            user_id=1,
            name="Основное стадо",
            bird_count=10,
            species="chicken",
        )
        estimate = self.service.add_purchase(
            user_id=1,
            name="Смесь для кур",
            kind="finished_mix",
            amount_kg=20,
        )
        self.service.assign_feed(
            user_id=1,
            bird_group_id=group.id,
            stock_item_id=estimate.item.id,
            daily_per_bird_g=120,
        )

        adjusted = self.service.adjust_stock(
            user_id=1,
            stock_item_id=estimate.item.id,
            amount_kg=10,
        )

        self.assertEqual(adjusted.remaining_kg, 10)

    def test_chick_assignment_stops_after_join_date(self) -> None:
        group = self.feeds.create_bird_group(
            user_id=1,
            name="Цыплята май",
            bird_count=10,
            species="chicken",
            group_kind="chicks",
            hatched_at=date(2026, 5, 1),
            joined_at=date(2026, 6, 1),
            reserve_percent=10,
        )
        estimate = self.service.add_purchase(
            user_id=1,
            name="Старт для цыплят",
            kind="commercial_feed",
            amount_kg=20,
        )
        self.service.assign_feed(
            user_id=1,
            bird_group_id=group.id,
            stock_item_id=estimate.item.id,
        )

        before = self.service.estimate_item(
            estimate.item,
            now=datetime(2026, 5, 11, tzinfo=timezone.utc),
        )
        after = self.service.estimate_item(
            estimate.item,
            now=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )

        self.assertEqual(round(before.daily_usage_kg, 3), 0.275)
        self.assertEqual(after.daily_usage_kg, 0)


if __name__ == "__main__":
    unittest.main()
