"""Losses, eggs leaving the house, prices and the cost of an egg."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.feeding import FeedingService, parse_mix_text
from app.services.feeds import FeedService
from app.services.ledger import LedgerService, format_cost_report, parse_count, parse_rub
from app.services.stock import StockService
from app.storage.database import Database
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeding import FeedingRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.stock import StockRepository


TODAY = date(2026, 10, 16)
MORNING = datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)


class LedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "t.db")
        self.database.initialize()
        feeds = FeedRepository(self.database)
        self.feed_service = FeedService(feeds)
        self.stock = StockService(StockRepository(self.database), feeds)
        self.feed_service.before_ration_change = self.stock.checkpoint_user
        self.hens = self.feed_service.create_bird_group(user_id=1, name="Несушки", bird_count=14, role="hens")
        self.roosters = self.feed_service.create_bird_group(
            user_id=1, name="Петухи", bird_count=1, role="roosters"
        )
        self.feeding = FeedingService(FeedingRepository(self.database), feeds, stock=self.stock)
        self.service = LedgerService(
            self.database, self.feed_service, feeding_service=self.feeding, stock_service=self.stock
        )
        self.eggs = EggRepository(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _egg(self, day: date, count: int) -> None:
        self.eggs.create_entry(
            user_id=1, entry_date=day, eggs_count=count,
            active_hens_count=14, total_hens_count=14, excluded_hens_count=0,
        )

    def test_loss_reduces_flock_and_undo_restores(self) -> None:
        loss = self.service.record_loss(
            user_id=1, bird_group_id=self.hens.id, count=2, reason="died", occurred_on=TODAY
        )

        self.assertEqual(self.feed_service.get_bird_group(self.hens.id, 1).bird_count, 12)
        self.assertEqual(self.service.loss_summary(1, today=TODAY).total, 2)

        self.service.undo_loss(1, loss.id)

        self.assertEqual(self.feed_service.get_bird_group(self.hens.id, 1).bird_count, 14)
        self.assertEqual(self.service.recent_losses(1), [])

    def test_losing_whole_group_archives_it_and_undo_brings_it_back(self) -> None:
        loss = self.service.record_loss(
            user_id=1, bird_group_id=self.roosters.id, count=1, reason="predator", occurred_on=TODAY
        )
        self.assertFalse(self.feed_service.get_bird_group(self.roosters.id, 1).is_active)

        self.service.undo_loss(1, loss.id)

        group = self.feed_service.get_bird_group(self.roosters.id, 1)
        self.assertTrue(group.is_active)
        self.assertEqual(group.bird_count, 1)

    def test_loss_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.service.record_loss(user_id=1, bird_group_id=self.hens.id, count=15, reason="died", occurred_on=TODAY)
        with self.assertRaises(ValueError):
            self.service.record_loss(user_id=1, bird_group_id=self.hens.id, count=1, reason="??", occurred_on=TODAY)
        with self.assertRaises(ValueError):
            self.service.record_loss(user_id=2, bird_group_id=self.hens.id, count=1, reason="died", occurred_on=TODAY)

    def test_losses_rising(self) -> None:
        self.service.record_loss(
            user_id=1, bird_group_id=self.hens.id, count=1, reason="died", occurred_on=TODAY - timedelta(days=40)
        )
        self.service.record_loss(user_id=1, bird_group_id=self.hens.id, count=3, reason="died", occurred_on=TODAY)

        summary = self.service.loss_summary(1, today=TODAY)

        self.assertEqual((summary.total, summary.previous_total), (3, 1))
        self.assertTrue(summary.rising)

    def test_eggs_out_balance_and_revenue(self) -> None:
        for offset in range(5):
            self._egg(TODAY - timedelta(days=offset), 10)
        self.service.record_outflow(
            user_id=1, kind="sold", eggs_count=20, amount_rub=300, occurred_on=TODAY - timedelta(days=3)
        )
        given = self.service.record_outflow(
            user_id=1, kind="given", eggs_count=5, amount_rub=99, occurred_on=TODAY
        )

        balance = self.service.egg_balance(1, today=TODAY)
        summary = self.service.outflow_summary(1, start_date=TODAY - timedelta(days=6), end_date=TODAY)

        # Counting starts from the first record: 4 days * 10 eggs - 25 gone.
        self.assertEqual((balance.collected, balance.gone, balance.at_home), (40, 25, 15))
        self.assertEqual((summary.sold, summary.revenue_rub, summary.given), (20, 300, 5))
        self.assertIsNone(given.amount_rub)  # only sales have money

        self.service.undo_outflow(1, given.id)
        self.assertEqual(self.service.egg_balance(1, today=TODAY).at_home, 20)

    def test_cost_of_cup_and_egg(self) -> None:
        self.feeding.set_mix(1, parse_mix_text("Кукуруза 4\nКомбикорм 2"))
        corn = self.stock.add_purchase(user_id=1, name="Кукуруза", kind="ingredient", amount_kg=50)
        feed = self.stock.add_purchase(user_id=1, name="Комбикорм", kind="commercial_feed", amount_kg=25)
        repo = StockRepository(self.database)
        self.service.set_purchase_price(1, repo.last_purchase_id(corn.item.id, 1), 1000)  # 20 ₽/kg
        self.service.set_purchase_price(1, repo.last_purchase_id(feed.item.id, 1), 1000)  # 40 ₽/kg
        for offset in range(3):
            self.feeding.record(1, cups=3, now=MORNING - timedelta(days=offset))
            self._egg(TODAY - timedelta(days=offset), 10)

        report = self.service.cost_report(1, today=TODAY, days=30)
        per_cup = {part.name: kg for part, kg in self.feeding.split_cups(1, 1)}
        expected_cup = per_cup["Кукуруза"] * 20 + per_cup["Комбикорм"] * 40

        self.assertAlmostEqual(report.cup_cost_rub, expected_cup, places=1)
        self.assertAlmostEqual(report.feed_cost_rub, expected_cup * 9, places=0)
        self.assertEqual(report.eggs, 30)
        self.assertAlmostEqual(report.per_egg_rub, report.feed_cost_rub / 30, places=2)
        text = "\n".join(format_cost_report(report))
        self.assertIn("Кружка смеси стоит", text)
        self.assertIn("Корм на одно яйцо", text)
        self.assertNotIn("Нет цены", text)

    def test_cost_report_lists_unpriced(self) -> None:
        self.feeding.set_mix(1, parse_mix_text("Кукуруза 4\nПремикс 1"))
        self.stock.add_purchase(user_id=1, name="Кукуруза", kind="ingredient", amount_kg=50)
        self.feeding.record(1, cups=3, now=MORNING)

        report = self.service.cost_report(1, today=TODAY)

        self.assertIsNone(report.cup_cost_rub)
        self.assertIn("Кукуруза", report.unpriced_names)

    def test_parsers(self) -> None:
        self.assertEqual(parse_rub("1 250,50 ₽"), 1250.5)
        self.assertEqual(parse_rub("300р"), 300)
        self.assertEqual(parse_count("12 шт", limit=100, what="яиц"), 12)
        with self.assertRaises(ValueError):
            parse_rub("много")
        with self.assertRaises(ValueError):
            parse_count("0", limit=10, what="птиц")



class WeeklyReportTest(LedgerTest):
    def test_report_has_eggs_feed_money_losses(self) -> None:
        from app.services.weekly_report import build_weekly_report

        self.feeding.set_mix(1, parse_mix_text("Кукуруза 4\nКомбикорм 2"))
        corn = self.stock.add_purchase(user_id=1, name="Кукуруза", kind="ingredient", amount_kg=50)
        self.stock.add_purchase(user_id=1, name="Комбикорм", kind="commercial_feed", amount_kg=3)
        self.service.set_purchase_price(1, StockRepository(self.database).last_purchase_id(corn.item.id, 1), 1000)
        for offset in range(7):
            self._egg(TODAY - timedelta(days=offset), 10)
            self._egg(TODAY - timedelta(days=offset + 7), 8)
            self.feeding.record(1, cups=3, now=MORNING - timedelta(days=offset))
        self.service.record_outflow(user_id=1, kind="sold", eggs_count=30, amount_rub=450, occurred_on=TODAY)
        self.service.record_loss(user_id=1, bird_group_id=self.hens.id, count=1, reason="died", occurred_on=TODAY)

        text = build_weekly_report(
            user_id=1, today=TODAY, eggs=self.eggs, feeding_service=self.feeding, ledger_service=self.service
        )

        self.assertIn("Собрано 70 (▲ 25% к прошлой неделе: 56)", text)
        self.assertIn("Кормили 7 из 7 дней", text)
        self.assertIn("На десяток яиц", text)
        self.assertIn("Продано 30 яиц на 450 ₽", text)
        self.assertIn("Корм за неделю", text)
        self.assertIn("«Несушки» −1", text)
        self.assertIn("Скоро закончится: Комбикорм", text)

    def test_report_without_feeding_or_sales(self) -> None:
        from app.services.weekly_report import build_weekly_report

        self._egg(TODAY, 5)
        text = build_weekly_report(user_id=1, today=TODAY, eggs=self.eggs, feeding_service=self.feeding, ledger_service=self.service)

        self.assertIn("Сбор записан за 1 из 7 дней", text)
        self.assertIn("Отметок «✅ Покормил» за неделю нет", text)
        self.assertNotIn("Деньги", text)


if __name__ == "__main__":
    unittest.main()
