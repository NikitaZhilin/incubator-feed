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

    def test_mix_can_use_layer_grain_mix_instead_of_wheat(self) -> None:
        for name in [
            "Кукуруза",
            "Зерносмесь",
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

        default_plan = self.service.plan_mix(user_id=1, mix_count=3)
        best_plan = self.service.best_available_mix_plan(user_id=1)
        grain_mix_plan = self.service.produce_mix(
            user_id=1,
            mix_count=3,
            grain_base="layer_grain_mix",
        )
        estimates = {item.item.name: item for item in self.service.list_estimates(1)}

        self.assertFalse(default_plan.can_produce)
        self.assertEqual(best_plan.grain_base_code, "layer_grain_mix")
        self.assertGreaterEqual(int(best_plan.max_mix_count), 3)
        self.assertTrue(grain_mix_plan.can_produce)
        self.assertEqual(grain_mix_plan.grain_base_label, "Зерносмесь")
        self.assertLess(estimates["Зерносмесь"].remaining_kg, 100)
        self.assertNotIn("Пшеница", estimates)

    def test_mix_matches_common_stock_aliases(self) -> None:
        purchases = {
            "кукуруза дроблёная": 60,
            "зерносмесь": 40,
            "ячмень": 40,
            "комбикорм щигровский": 25,
            "Мясокостная мука": 5,
            "Рыбная мука": 5,
            "ракушка дроблёная мелкая": 10,
            "премикс": 3,
        }
        for name, amount in purchases.items():
            self.service.add_purchase(
                user_id=1,
                name=name,
                kind="ingredient",
                amount_kg=amount,
            )

        plan = self.service.best_available_mix_plan(user_id=1)

        self.assertEqual(plan.grain_base_code, "layer_grain_mix")
        self.assertTrue(plan.can_produce)
        self.assertGreaterEqual(int(plan.max_mix_count), 9)
        self.assertFalse([item for item in plan.ingredients if item.missing_kg > 0])

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

    def test_flock_assignment_uses_hens_roosters_and_chicks_after_join_date(self) -> None:
        hens = self.feeds.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=20,
            species="chicken",
            role="hens",
        )
        roosters = self.feeds.create_bird_group(
            user_id=1,
            name="Петухи",
            bird_count=2,
            species="chicken",
            role="roosters",
        )
        chicks = self.feeds.create_bird_group(
            user_id=1,
            name="Цыплята май",
            bird_count=10,
            species="chicken",
            group_kind="chicks",
            role="chicks",
            hatched_at=date(2026, 5, 1),
            joined_at=date(2026, 6, 1),
        )
        flock = self.feeds.create_flock(user_id=1, name="Основное стадо")
        for group in (hens, roosters, chicks):
            self.feeds.add_flock_member(user_id=1, flock_id=flock.id, bird_group_id=group.id)
        estimate = self.service.add_purchase(
            user_id=1,
            name="Смесь для кур",
            kind="finished_mix",
            amount_kg=100,
        )
        self.service.assign_flock_feed(
            user_id=1,
            flock_id=flock.id,
            stock_item_id=estimate.item.id,
            share_percent=100,
        )

        before_join = self.service.estimate_item(
            estimate.item,
            now=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )
        after_join = self.service.estimate_item(
            estimate.item,
            now=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )
        reports = self.service.list_flock_reports(
            1,
            now=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )

        self.assertEqual(round(before_join.daily_usage_kg, 2), 2.7)
        self.assertEqual(round(after_join.daily_usage_kg, 2), 3.4)
        self.assertEqual(len(reports), 1)
        self.assertEqual(round(reports[0].daily_usage_kg, 2), 3.4)

    def test_archived_flock_stops_consuming_assigned_feed(self) -> None:
        group = self.feeds.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=10,
            species="chicken",
            role="hens",
        )
        flock = self.feeds.create_flock(user_id=1, name="Основное стадо")
        self.feeds.add_flock_member(user_id=1, flock_id=flock.id, bird_group_id=group.id)
        estimate = self.service.add_purchase(
            user_id=1,
            name="Смесь для кур",
            kind="finished_mix",
            amount_kg=50,
        )
        self.service.assign_flock_feed(
            user_id=1,
            flock_id=flock.id,
            stock_item_id=estimate.item.id,
            share_percent=100,
        )

        self.assertGreater(self.service.estimate_item(estimate.item).daily_usage_kg, 0)

        self.feeds.archive_flock(flock.id, 1)

        self.assertEqual(self.service.estimate_item(estimate.item).daily_usage_kg, 0)

    def test_flock_feed_share_cannot_exceed_full_ration(self) -> None:
        group = self.feeds.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=10,
            species="chicken",
            role="hens",
        )
        flock = self.feeds.create_flock(user_id=1, name="Основное стадо")
        self.feeds.add_flock_member(user_id=1, flock_id=flock.id, bird_group_id=group.id)
        first = self.service.add_purchase(
            user_id=1,
            name="Смесь 1",
            kind="finished_mix",
            amount_kg=50,
        )
        second = self.service.add_purchase(
            user_id=1,
            name="Смесь 2",
            kind="finished_mix",
            amount_kg=50,
        )

        self.service.assign_flock_feed(
            user_id=1,
            flock_id=flock.id,
            stock_item_id=first.item.id,
            share_percent=70,
        )

        with self.assertRaises(ValueError):
            self.service.assign_flock_feed(
                user_id=1,
                flock_id=flock.id,
                stock_item_id=second.item.id,
                share_percent=40,
            )

    def test_flock_assignment_replaces_direct_group_assignment(self) -> None:
        group = self.feeds.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=10,
            species="chicken",
            role="hens",
        )
        direct = self.service.add_purchase(
            user_id=1,
            name="Прямой корм",
            kind="finished_mix",
            amount_kg=50,
        )
        flock_feed = self.service.add_purchase(
            user_id=1,
            name="Общий корм стада",
            kind="finished_mix",
            amount_kg=50,
        )
        self.service.assign_feed(
            user_id=1,
            bird_group_id=group.id,
            stock_item_id=direct.item.id,
            daily_per_bird_g=120,
        )
        flock = self.feeds.create_flock(user_id=1, name="Основное стадо")
        self.feeds.add_flock_member(user_id=1, flock_id=flock.id, bird_group_id=group.id)

        self.service.assign_flock_feed(
            user_id=1,
            flock_id=flock.id,
            stock_item_id=flock_feed.item.id,
            share_percent=100,
        )

        self.assertEqual(self.service.estimate_item(direct.item).daily_usage_kg, 0)
        self.assertGreater(self.service.estimate_item(flock_feed.item).daily_usage_kg, 0)

    def test_flock_assignment_accepts_only_finished_mix(self) -> None:
        group = self.feeds.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=10,
            species="chicken",
            role="hens",
        )
        flock = self.feeds.create_flock(user_id=1, name="Основное стадо")
        self.feeds.add_flock_member(user_id=1, flock_id=flock.id, bird_group_id=group.id)
        ingredient = self.service.add_purchase(
            user_id=1,
            name="Кукуруза",
            kind="ingredient",
            amount_kg=50,
        )

        with self.assertRaises(ValueError):
            self.service.assign_flock_feed(
                user_id=1,
                flock_id=flock.id,
                stock_item_id=ingredient.item.id,
                share_percent=100,
            )

    def test_flock_report_includes_possible_mix_production_from_ingredients(self) -> None:
        group = self.feeds.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=10,
            species="chicken",
            role="hens",
        )
        flock = self.feeds.create_flock(user_id=1, name="Основное стадо")
        self.feeds.add_flock_member(user_id=1, flock_id=flock.id, bird_group_id=group.id)
        finished_mix = self.service.add_purchase(
            user_id=1,
            name="Смесь для кур",
            kind="finished_mix",
            amount_kg=10,
        )
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
        self.service.assign_flock_feed(
            user_id=1,
            flock_id=flock.id,
            stock_item_id=finished_mix.item.id,
            share_percent=100,
        )

        usage = self.service.list_flock_reports(1)[0].assignments[0]

        self.assertGreater(usage.producible_mix_count, 0)
        self.assertGreater(usage.producible_mix_kg, 0)
        self.assertGreater(usage.total_days_left, usage.days_left)


if __name__ == "__main__":
    unittest.main()
