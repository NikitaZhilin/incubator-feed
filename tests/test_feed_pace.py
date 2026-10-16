"""Feeding in cups: the summary and «Птицевод» count ingredient days, not finished mix."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import tempfile
import unittest

from app.services.eggs import EggService
from app.services.feeding import FeedingService, pace_lines
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.services.poultry_advisor import PoultryAdvisorService
from app.services.stock import StockService
from app.storage.database import Database
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeding import FeedingRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.stock import StockRepository


TODAY = date(2026, 10, 16)
# 09:00 Moscow.
MORNING = datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)


class FeedPaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "t.db")
        self.database.initialize()
        self.feeds = FeedRepository(self.database)
        FeedService(self.feeds).create_bird_group(user_id=1, name="Несушки", bird_count=14, role="hens")
        self.stock = StockService(StockRepository(self.database), self.feeds)
        self.service = FeedingService(FeedingRepository(self.database), self.feeds, stock=self.stock)
        # 1-litre cup; corn 4 of 6 parts, compound feed 2 of 6.
        self.service.set_mix(1, _mix("Кукуруза 4\nКомбикорм 2"))
        self.stock.add_purchase(user_id=1, name="Кукуруза", kind="ingredient", amount_kg=40)
        self.stock.add_purchase(user_id=1, name="Комбикорм", kind="commercial_feed", amount_kg=5)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _advisor(self, feeding_service) -> PoultryAdvisorService:
        return PoultryAdvisorService(
            incubation_service=IncubationService(BatchRepository(self.database)),
            feed_service=FeedService(self.feeds),
            egg_service=EggService(EggRepository(self.database), self.feeds, timezone_name="Europe/Moscow"),
            stock_service=self.stock,
            timezone_name="Europe/Moscow",
            feeding_service=feeding_service,
        )

    def _feed_days(self, days: int, cups: float = 3.0) -> None:
        for offset in range(days):
            self.service.record(1, cups=cups, now=MORNING - timedelta(days=offset))

    def test_no_pace_without_cups(self) -> None:
        self.service.record(1, now=MORNING)  # by norm, no cups

        self.assertIsNone(self.service.pace(1, today=TODAY))

    def test_pace_per_ingredient_from_actual_days(self) -> None:
        self._feed_days(3)

        pace = self.service.pace(1, today=TODAY)
        by_name = {item.name: item for item in pace.ingredients}

        per_cup = self.service.mix_kg_per_cup(1)
        corn, feed = by_name["Кукуруза"], by_name["Комбикорм"]

        # 3 cups a day; only 3 days observed, so the average is over 3 days, not 7.
        self.assertEqual(pace.observed_days, 3)
        self.assertAlmostEqual(pace.daily_kg, 3 * per_cup, places=2)
        self.assertAlmostEqual(corn.per_day_kg + feed.per_day_kg, pace.daily_kg, places=2)
        # Three days of compound feed are already written off from 5 kg.
        self.assertAlmostEqual(feed.remaining_kg, 5 - 3 * feed.per_day_kg, places=2)
        self.assertEqual(feed.days_left, int(feed.remaining_kg // feed.per_day_kg))
        self.assertLessEqual(feed.days_left, 7)
        self.assertGreater(corn.days_left, 7)
        self.assertEqual([item.name for item in pace.soon_out], ["Комбикорм"])

    def test_summary_lines_warn_about_ingredient_not_finished_mix(self) -> None:
        self._feed_days(3)

        text = "\n".join(pace_lines(self.service.pace(1, today=TODAY)))

        self.assertIn("Кормите своей смесью", text)
        self.assertIn("Комбикорм — на ", text)
        self.assertIn("кукуруза", text)
        self.assertNotIn("готов", text.lower())

    def test_advisor_does_not_ask_for_finished_mix_when_feeding_by_cups(self) -> None:
        self._feed_days(3)
        advisor = self._advisor(self.service)
        local = MORNING.astimezone(advisor._timezone())

        plan = advisor.build_today_plan(1, local_now=local, now_utc=MORNING)
        timing = advisor.build_mix_timing_advice(1, local_now=local, now_utc=MORNING)
        feed = advisor.build_feed_advice(1, now_utc=MORNING)
        summary = advisor.build_daily_summary_advice_lines(1, local_now=local, now_utc=MORNING)

        for text in (plan, timing, feed, "\n".join(summary)):
            self.assertNotIn("Готовой смеси нет", text)
            self.assertNotIn("готовой смеси нет", text)
            self.assertNotIn("без назначенной смеси", text)
        self.assertIn("Корм (своя смесь)", plan)
        self.assertIn("Комбикорм — на ", timing)
        self.assertIn("комбикорм хватит на ", summary[0])

    def test_advisor_without_cups_keeps_finished_mix_advice(self) -> None:
        advisor = self._advisor(self.service)
        local = MORNING.astimezone(advisor._timezone())

        plan = advisor.build_today_plan(1, local_now=local, now_utc=MORNING)

        self.assertIn("Корма и смесь:", plan)
        self.assertIn("Остаток готовой смеси", plan)


@unittest.skipUnless(importlib.util.find_spec("aiogram"), "aiogram is not installed")
class DailySummaryPaceTest(FeedPaceTest):
    def test_daily_summary_shows_ingredient_days(self) -> None:
        from app.services.reminders import ReminderRunner

        self._feed_days(3)
        runner = ReminderRunner(
            bot=object(),
            incubation_service=IncubationService(BatchRepository(self.database)),
            stock_service=self.stock,
            feeding_service=self.service,
            timezone="Europe/Moscow",
        )
        local = MORNING.astimezone(self.service._local(MORNING).tzinfo)

        text = runner.build_daily_summary_message(user_id=1, local_now=local, now=MORNING)

        self.assertIn("Корм (своя смесь):", text)
        self.assertIn("Комбикорм — на ", text)
        self.assertNotIn("Готовая смесь:", text)
        self.assertNotIn("Критично", text)


class BuyReminderStageTest(unittest.TestCase):
    def test_stages(self) -> None:
        from app.services.feeding import IngredientPace, buy_reminder_stage

        def stage(days):
            return buy_reminder_stage(IngredientPace("Премикс", 0.1, 1.0, days, 1))

        self.assertIsNone(stage(None))
        self.assertIsNone(stage(6))
        self.assertEqual(stage(5), 5)
        self.assertEqual(stage(3), 5)
        self.assertEqual(stage(2), 2)
        self.assertEqual(stage(0), 2)


@unittest.skipUnless(importlib.util.find_spec("aiogram"), "aiogram is not installed")
class BuyReminderRunnerTest(FeedPaceTest):
    class Bot:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def send_message(self, user_id, text, reply_markup=None) -> None:
            self.messages.append(text)

    def _runner(self, bot):
        from app.services.reminders import ReminderRunner
        from app.storage.repositories.notifications import NotificationRepository
        from app.storage.repositories.users import UserRepository

        users = UserRepository(self.database)
        users.upsert(user_id=1, first_name="Никита")
        return ReminderRunner(
            bot=bot,
            incubation_service=IncubationService(BatchRepository(self.database)),
            stock_service=self.stock,
            feeding_service=self.service,
            users=users,
            notifications=NotificationRepository(self.database),
            timezone="Europe/Moscow",
        )

    def test_reminds_once_ahead_and_again_after_new_purchase(self) -> None:
        import asyncio

        self._feed_days(3)
        bot = self.Bot()
        runner = self._runner(bot)

        asyncio.run(runner._send_buy_reminders(MORNING + timedelta(minutes=5)))
        asyncio.run(runner._send_buy_reminders(MORNING + timedelta(hours=2)))

        self.assertEqual(len(bot.messages), 1)
        self.assertIn("Пора докупить", bot.messages[0])
        self.assertIn("Комбикорм: закончится через", bot.messages[0])
        self.assertNotIn("Кукуруза", bot.messages[0])
        self.assertIn("сколько вы реально даёте", bot.messages[0])

        # A small top-up is still short: a new purchase restarts the reminders.
        self.stock.add_purchase(user_id=1, name="Комбикорм", kind="commercial_feed", amount_kg=0.1)
        asyncio.run(runner._send_buy_reminders(MORNING + timedelta(hours=3)))

        self.assertEqual(len(bot.messages), 2)

    def test_no_reminder_before_notification_time_or_when_feed_section_off(self) -> None:
        import asyncio
        from app.storage.repositories.users import UserRepository

        self._feed_days(3)
        bot = self.Bot()
        runner = self._runner(bot)

        asyncio.run(runner._send_buy_reminders(MORNING - timedelta(hours=2)))  # 07:00
        UserRepository(self.database).update_settings(1, notify_feed=False)
        asyncio.run(runner._send_buy_reminders(MORNING + timedelta(hours=1)))

        self.assertEqual(bot.messages, [])


def _mix(text: str):
    from app.services.feeding import parse_mix_text

    return parse_mix_text(text)


if __name__ == "__main__":
    unittest.main()
