from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.handlers.common import cancel_any
from app.handlers.feeds import (
    ChangeFeed,
    EditFeed,
    NewFeed,
    feed_amount,
    feed_change_amount,
    feed_edit_value,
    feed_hens,
    feed_name_with_service,
    feed_roosters,
    feed_threshold,
)
from app.handlers.incubation import NewBatch, enter_eggs_count
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.users import UserRepository


class FakeUser:
    id = 1
    username = "tester"
    first_name = "Test"
    last_name = "User"


class FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.from_user = FakeUser()
        self.date = datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc)
        self.answers: list[tuple[str, object]] = []

    async def answer(self, text: str, reply_markup=None, **kwargs) -> None:
        self.answers.append((text, reply_markup))


class FakeState:
    def __init__(self) -> None:
        self.data: dict = {}
        self.state = None
        self.cleared = False

    async def clear(self) -> None:
        self.data = {}
        self.state = None
        self.cleared = True

    async def set_state(self, state) -> None:
        self.state = state
        self.cleared = False

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict:
        return dict(self.data)


class HandlerFsmTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.db")
        self.database.initialize()
        self.analytics = AnalyticsRepository(self.database)
        self.incubation = IncubationService(
            BatchRepository(self.database),
            ReminderRepository(self.database),
            UserRepository(self.database),
            self.analytics,
        )
        self.feed_service = FeedService(FeedRepository(self.database), self.analytics)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_invalid_egg_count_keeps_user_on_same_step_and_logs_error(self) -> None:
        state = FakeState()
        await state.set_state(NewBatch.eggs_count)
        message = FakeMessage("abc")

        await enter_eggs_count(message, state, self.incubation)

        self.assertEqual(state.state, NewBatch.eggs_count)
        self.assertIn("числом", message.answers[-1][0])
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT event_name FROM analytics_events WHERE event_name = 'scenario_error'"
            ).fetchone()
        self.assertIsNotNone(row)

    async def test_cancel_clears_state_and_returns_menu(self) -> None:
        state = FakeState()
        await state.set_state(NewFeed.amount)
        message = FakeMessage("/cancel")

        await cancel_any(message, state)

        self.assertTrue(state.cleared)
        self.assertIn("Главное меню", message.answers[-1][0])

    async def test_feed_creation_fsm_critical_path(self) -> None:
        state = FakeState()
        await state.set_state(NewFeed.name)

        await feed_name_with_service(FakeMessage("ПК-1"), state, self.feed_service, self.incubation)
        self.assertEqual(state.state, NewFeed.amount)
        await feed_amount(FakeMessage("25 кг"), state, self.incubation)
        self.assertEqual(state.state, NewFeed.hens)
        await feed_hens(FakeMessage("18"), state, self.incubation)
        self.assertEqual(state.state, NewFeed.roosters)
        await feed_roosters(FakeMessage("2"), state, self.incubation)
        self.assertEqual(state.state, NewFeed.hen_rate)
        await state.update_data(hen_daily_g=120, rooster_daily_g=150)
        await state.set_state(NewFeed.threshold)
        threshold_message = FakeMessage("5")

        await feed_threshold(threshold_message, state, self.feed_service, self.incubation)

        self.assertTrue(state.cleared)
        self.assertIn("Корм добавлен", threshold_message.answers[-1][0])
        self.assertEqual(len(self.feed_service.list_user_estimates(1)), 1)

    async def test_feed_creation_with_group_derives_roosters_from_group_total(self) -> None:
        group = self.feed_service.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=20,
            species="chicken",
        )
        state = FakeState()
        await state.update_data(
            name="Зерносмесь",
            bird_group_id=group.id,
            bird_count=group.bird_count,
        )
        await state.set_state(NewFeed.amount)

        await feed_amount(FakeMessage("30кг"), state, self.incubation)
        self.assertEqual(state.state, NewFeed.hens)

        hens_message = FakeMessage("18")
        await feed_hens(hens_message, state, self.incubation)

        self.assertEqual(state.state, NewFeed.hen_rate)
        self.assertEqual(state.data["hen_count"], 18)
        self.assertEqual(state.data["rooster_count"], 2)
        self.assertIn("Учту: кур/несушек 18, петухов 2", hens_message.answers[-1][0])

    async def test_feed_creation_with_only_roosters_skips_hen_rate(self) -> None:
        state = FakeState()
        await state.update_data(name="Зерносмесь", amount_kg=30, hen_count=0)
        await state.set_state(NewFeed.roosters)
        roosters_message = FakeMessage("3")

        await feed_roosters(roosters_message, state, self.incubation)

        self.assertEqual(state.state, NewFeed.rooster_rate)
        self.assertEqual(state.data["bird_count"], 3)
        self.assertIn("Кур/несушек нет", roosters_message.answers[-1][0])

    async def test_feed_restock_writeoff_and_edit_handlers(self) -> None:
        feed = self.feed_service.create_feed(
            user_id=1,
            name="ПК-1",
            amount_kg=10,
            bird_count=10,
            daily_per_bird_g=100,
            low_threshold_kg=2,
        )

        state = FakeState()
        await state.update_data(feed_id=feed.id, action="add")
        await state.set_state(ChangeFeed.amount)
        await feed_change_amount(FakeMessage("5"), state, self.feed_service)
        self.assertTrue(state.cleared)

        state = FakeState()
        await state.update_data(feed_id=feed.id, action="write_off")
        await state.set_state(ChangeFeed.amount)
        await feed_change_amount(FakeMessage("3"), state, self.feed_service)
        self.assertTrue(state.cleared)

        state = FakeState()
        await state.update_data(feed_id=feed.id, field="name")
        await state.set_state(EditFeed.value)
        await feed_edit_value(FakeMessage("ПК-2"), state, self.feed_service, self.incubation)

        self.assertEqual(self.feed_service.get_estimate(feed.id, 1).feed.name, "ПК-2")


if __name__ == "__main__":
    unittest.main()
