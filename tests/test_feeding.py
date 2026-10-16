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


class FeedingCupsTest(unittest.TestCase):
    """«даю около 3-4 кружек смеси: зерносмесь+комбикорм+кукуруза+рыбная мука+ракушка+премикс»."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "t.db")
        self.database.initialize()
        feeds = FeedRepository(self.database)
        FeedService(feeds).create_bird_group(user_id=1, name="Несушки", bird_count=14, role="hens")
        self.stock = StockService(StockRepository(self.database), feeds)
        self.stock.add_purchase(user_id=1, name="Кукуруза дроблёная", kind="ingredient", amount_kg=40)
        self.stock.add_purchase(user_id=1, name="Зерносмесь", kind="ingredient", amount_kg=25)
        self.stock.add_purchase(user_id=1, name="Премикс", kind="ingredient", amount_kg=1)
        self.service = FeedingService(FeedingRepository(self.database), feeds, stock=self.stock)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _remaining(self, name: str) -> float:
        item = next(e for e in self.stock.list_estimates(1) if e.item.name == name)
        return round(item.remaining_kg, 3)

    def test_default_mix_is_the_owners_usual_mix(self) -> None:
        names = [part.name for part in self.service.get_mix(1)]

        self.assertEqual(
            names,
            ["Кукуруза", "Зерновая смесь для кур несушек", "Комбикорм", "Ракушка", "Рыбная мука", "Премикс"],
        )

    def test_cups_are_split_by_composition_and_density(self) -> None:
        split = dict((part.name, kg) for part, kg in self.service.split_cups(1, 3.5))

        # 8.3 cups per batch; corn is 3.5 of them, 0.72 kg per litre.
        self.assertAlmostEqual(split["Кукуруза"], 3.5 * 3.5 / 8.3 * 0.72, places=3)
        self.assertAlmostEqual(split["Премикс"], 3.5 * 0.1 / 8.3 * 0.75, places=3)
        self.assertAlmostEqual(sum(split.values()), 2.49, places=2)

    def test_feeding_writes_off_only_what_is_in_stock(self) -> None:
        result = self.service.record(1, cups=3.5, now=MORNING)
        given = {item.name: item for item in result.ingredients}

        self.assertAlmostEqual(result.event.mix_kg, 2.49, places=2)
        self.assertTrue(given["Кукуруза"].in_stock)
        self.assertFalse(given["Рыбная мука"].in_stock)
        self.assertAlmostEqual(self._remaining("Кукуруза дроблёная"), 40 - given["Кукуруза"].kg, places=3)
        self.assertAlmostEqual(self._remaining("Зерносмесь"), 25 - given["Зерновая смесь для кур несушек"].kg, places=3)
        self.assertEqual(self.service.last_cups(1), 3.5)

    def test_undo_returns_ingredients_to_stock(self) -> None:
        result = self.service.record(1, cups=4, now=MORNING)

        self.service.undo(1, result.event.id)

        self.assertAlmostEqual(self._remaining("Кукуруза дроблёная"), 40, places=3)
        self.assertAlmostEqual(self._remaining("Премикс"), 1, places=3)
        self.assertEqual(self.service.today(1, now=MORNING), [])

    def test_week_counts_given_amount_instead_of_norm(self) -> None:
        self.service.record(1, cups=3, now=MORNING - timedelta(days=1))
        self.service.record(1, now=MORNING - timedelta(days=2))  # plain tap: norm 14 * 120 g

        week = self.service.week(1, today=date(2026, 10, 16))
        corn = next(row for row in self.service.ingredients_week(1, today=date(2026, 10, 16)) if row["name"] == "Кукуруза")

        self.assertEqual(week.fed_days, 2)
        self.assertEqual(week.measured_days, 1)
        self.assertAlmostEqual(week.estimated_kg, round(self.service.mix_kg_per_cup(1) * 3 + 1.68, 2), places=1)
        self.assertGreater(corn["used_kg"], 0)
        self.assertIsNotNone(corn["days_left"])

    def test_mix_can_be_edited_with_text(self) -> None:
        from app.services.feeding import parse_mix_text

        parts = parse_mix_text("Кукуруза 4\nЗерносмесь 3,5; Комбикорм - 2\nРакушка: 0.5")
        mix = self.service.set_mix(1, parts)

        self.assertEqual([(p.name, p.parts) for p in mix][:2], [("Кукуруза", 4.0), ("Зерновая смесь для кур несушек", 3.5)])
        with self.assertRaises(ValueError):
            parse_mix_text("кукуруза много")

    def test_cups_parsing(self) -> None:
        from app.services.feeding import parse_cups

        self.assertEqual(parse_cups("3,5"), 3.5)
        self.assertEqual(parse_cups("4 кружки"), 4.0)
        with self.assertRaises(ValueError):
            parse_cups("0")
