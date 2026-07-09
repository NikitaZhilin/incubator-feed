from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.handlers import poultry_advisor as poultry_advisor_handlers
from app.services.eggs import EggService
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.services.poultry_advisor import PoultryAdvisorService
from app.services.stock import StockService
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.stock import StockRepository
from app.storage.repositories.users import UserRepository


class PoultryAdvisorServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.db")
        self.database.initialize()
        self.users = UserRepository(self.database)
        self.analytics = AnalyticsRepository(self.database)
        self.feed_repository = FeedRepository(self.database)
        self.feed_service = FeedService(self.feed_repository, self.analytics)
        self.egg_service = EggService(EggRepository(self.database), self.feed_repository, timezone_name="Europe/Moscow")
        self.incubation_service = IncubationService(
            BatchRepository(self.database),
            ReminderRepository(self.database),
            self.users,
            self.analytics,
        )
        self.stock_service = StockService(StockRepository(self.database), self.feed_repository, self.analytics)
        self.advisor = PoultryAdvisorService(
            incubation_service=self.incubation_service,
            feed_service=self.feed_service,
            egg_service=self.egg_service,
            stock_service=self.stock_service,
            timezone_name="Europe/Moscow",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_today_plan_without_data_explains_first_steps(self) -> None:
        now = datetime.now(timezone.utc)

        text = self.advisor.build_today_plan(1, local_now=now, now_utc=now)

        self.assertIn("План птицевода", text)
        self.assertIn("Записать сбор яиц", text)
        self.assertIn("Стада не созданы", text)
        self.assertIn("Готовой смеси", text)

    def test_today_plan_includes_feed_eggs_and_incubation(self) -> None:
        user_id = 10
        now = datetime.now(timezone.utc)
        today = now.astimezone(timezone.utc).date()
        group = self.feed_service.create_bird_group(
            user_id=user_id,
            name="Несушки",
            bird_count=10,
            species="chicken",
            role="hens",
        )
        flock = self.feed_service.create_flock(
            user_id=user_id,
            name="Основное",
            member_group_ids=[group.id],
        )
        mix = self.stock_service.add_purchase(
            user_id=user_id,
            name="Смесь для кур",
            kind="finished_mix",
            amount_kg=2,
        )
        self.stock_service.assign_flock_feed(
            user_id=user_id,
            flock_id=flock.id,
            stock_item_id=mix.item.id,
        )
        self.egg_service.record_entry(user_id=user_id, eggs_count=6, entry_date=today)
        self.incubation_service.create_batch(
            user_id=user_id,
            species="chicken",
            eggs_count=12,
            start_date=today - timedelta(days=5),
            title="Куры июль",
        )

        text = self.advisor.build_today_plan(user_id, local_now=now, now_utc=now)

        self.assertIn("Сбор за сегодня уже записан: 6 шт.", text)
        self.assertIn("Срочно", text)
        self.assertIn("Куры июль", text)

    def test_feed_advice_requires_flock_when_no_flocks(self) -> None:
        text = self.advisor.build_feed_advice(1)

        self.assertIn("Сначала создайте стадо", text)

    def test_feed_advice_lists_missing_ingredients(self) -> None:
        user_id = 11
        group = self.feed_service.create_bird_group(
            user_id=user_id,
            name="Несушки",
            bird_count=8,
            species="chicken",
            role="hens",
        )
        flock = self.feed_service.create_flock(user_id=user_id, name="Основное", member_group_ids=[group.id])
        mix = self.stock_service.add_purchase(
            user_id=user_id,
            name="Смесь для кур",
            kind="finished_mix",
            amount_kg=10,
        )
        self.stock_service.assign_flock_feed(
            user_id=user_id,
            flock_id=flock.id,
            stock_item_id=mix.item.id,
        )

        text = self.advisor.build_feed_advice(user_id)

        self.assertIn("Основное", text)
        self.assertIn("не хватает", text)
        self.assertIn("Кукуруза", text)

    def test_mix_timing_says_now_when_no_finished_mix_left(self) -> None:
        user_id = 12
        group = self.feed_service.create_bird_group(
            user_id=user_id,
            name="Несушки",
            bird_count=8,
            species="chicken",
            role="hens",
        )
        flock = self.feed_service.create_flock(user_id=user_id, name="Основное", member_group_ids=[group.id])
        mix = self.stock_service.add_purchase(
            user_id=user_id,
            name="Смесь для кур",
            kind="finished_mix",
            amount_kg=0.1,
        )
        self.stock_service.assign_flock_feed(
            user_id=user_id,
            flock_id=flock.id,
            stock_item_id=mix.item.id,
        )
        future = datetime.now(timezone.utc) + timedelta(days=1)

        text = self.advisor.build_mix_timing_advice(user_id, now_utc=future, local_now=future)

        self.assertIn("Замес нужен сейчас", text)

    def test_egg_drop_detects_week_vs_month_drop(self) -> None:
        user_id = 13
        today = date(2026, 7, 9)
        self.feed_service.create_bird_group(
            user_id=user_id,
            name="Несушки",
            bird_count=10,
            species="chicken",
            role="hens",
        )
        for offset in range(29, 6, -1):
            self.egg_service.record_entry(user_id=user_id, eggs_count=8, entry_date=today - timedelta(days=offset))
        for offset in range(6, -1, -1):
            self.egg_service.record_entry(user_id=user_id, eggs_count=2, entry_date=today - timedelta(days=offset))
        self.egg_service.create_exclusion(
            user_id=user_id,
            hens_count=1,
            reason="molting",
            started_at=today - timedelta(days=2),
            expected_until=today + timedelta(days=5),
        )

        text = self.advisor.build_egg_drop_advice(user_id, today=today)

        self.assertIn("Есть просадка", text)
        self.assertIn("линька", text)
        self.assertIn("Проверки на сегодня", text)

    def test_egg_drop_requires_hens(self) -> None:
        text = self.advisor.build_egg_drop_advice(1, today=date(2026, 7, 9))

        self.assertIn("нет групп с ролью", text)

    def test_incubation_today_includes_batch_day_and_stage(self) -> None:
        user_id = 14
        today = date(2026, 7, 9)
        self.incubation_service.create_batch(
            user_id=user_id,
            species="chicken",
            eggs_count=10,
            start_date=today - timedelta(days=18),
            title="Куры тест",
        )

        text = self.advisor.build_incubation_today_advice(user_id, today=today)

        self.assertIn("Куры тест", text)
        self.assertIn("день", text)
        self.assertIn("не переворачивайте", text.lower())

    def test_incubation_today_uses_supplied_date_for_batch_day(self) -> None:
        user_id = 15
        today = date.today() - timedelta(days=1)
        self.incubation_service.create_batch(
            user_id=user_id,
            species="chicken",
            eggs_count=10,
            start_date=today - timedelta(days=8),
            title="Локальная дата",
        )

        text = self.advisor.build_incubation_today_advice(user_id, today=today)

        self.assertIn("\u0434\u0435\u043d\u044c 9", text)
        self.assertNotIn("\u0434\u0435\u043d\u044c 10", text)

    def test_health_red_flags_response_is_safe(self) -> None:
        text = self.advisor.build_health_red_flags_advice()

        self.assertIn("Изолировать", text)
        self.assertIn("ветеринар", text)
        self.assertIn("не назначаю лекарства", text)
        self.assertNotIn("мг/кг", text)

    def test_daily_summary_advice_respects_disabled_setting(self) -> None:
        now = datetime.now(timezone.utc)

        lines = self.advisor.build_daily_summary_advice_lines(
            1,
            local_now=now,
            now_utc=now,
            settings={"notify_poultry_advisor": False},
        )

        self.assertEqual(lines, [])


class PoultryAdvisorHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_incubation_today_uses_user_local_date(self) -> None:
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 9, 11, 30, tzinfo=timezone.utc)

        class FakeState:
            def __init__(self) -> None:
                self.cleared = False

            async def clear(self) -> None:
                self.cleared = True

        class FakeMessage:
            def __init__(self) -> None:
                self.answers = []

            async def answer(self, text, reply_markup=None) -> None:
                self.answers.append((text, reply_markup))

        class FakeCallback:
            def __init__(self) -> None:
                self.from_user = SimpleNamespace(id=42)
                self.message = FakeMessage()
                self.answered = False

            async def answer(self) -> None:
                self.answered = True

        class FakeAdvisor:
            def __init__(self) -> None:
                self.received_user_id = None
                self.received_today = None

            def build_incubation_today_advice(self, user_id, *, today=None) -> str:
                self.received_user_id = user_id
                self.received_today = today
                return f"today={today}"

        class FakeIncubationService:
            def get_user_settings(self, user_id):
                return {"timezone": "Pacific/Kiritimati"}

        callback = FakeCallback()
        state = FakeState()
        advisor = FakeAdvisor()

        with patch.object(poultry_advisor_handlers, "datetime", FixedDateTime):
            await poultry_advisor_handlers.advisor_incubation_today(
                callback,
                state,
                advisor,
                FakeIncubationService(),
            )

        self.assertTrue(state.cleared)
        self.assertTrue(callback.answered)
        self.assertEqual(advisor.received_user_id, 42)
        self.assertEqual(advisor.received_today, date(2026, 7, 10))
        self.assertEqual(callback.message.answers[0][0], "today=2026-07-10")


if __name__ == "__main__":
    unittest.main()
