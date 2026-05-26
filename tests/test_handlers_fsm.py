from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.handlers.common import cancel_any
from app.handlers.feeds import (
    ChangeFeed,
    EditFeed,
    NewFeed,
    StockPurchaseFlow,
    feed_amount,
    feed_change_amount,
    feed_command,
    feed_edit_value,
    feed_hens,
    feed_name_with_service,
    feed_roosters,
    feed_threshold,
    feed_add,
    flock_assign_item,
    stock_mix_check_all,
    stock_mix_confirm,
    stock_mix_cycle_done,
    stock_mix_plan,
    stock_purchase_amount,
    stock_purchase_name,
)
from app.handlers.incubation import NewBatch, enter_eggs_count
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.services.stock import StockService
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.stock import StockRepository
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


class FakeCallback:
    def __init__(self, data: str = "") -> None:
        self.data = data
        self.from_user = FakeUser()
        self.message = FakeMessage()
        self.answered = False

    async def answer(self, *args, **kwargs) -> None:
        self.answered = True


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
        self.stock_service = StockService(
            StockRepository(self.database),
            FeedRepository(self.database),
            self.analytics,
        )

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

    async def test_stock_purchase_fsm_critical_path(self) -> None:
        state = FakeState()
        await state.set_state(StockPurchaseFlow.name)

        await stock_purchase_name(FakeMessage("Кукуруза"), state)
        self.assertEqual(state.state, StockPurchaseFlow.kind)
        await state.update_data(kind="ingredient")
        await state.set_state(StockPurchaseFlow.amount)
        amount_message = FakeMessage("2 мешка по 25")

        await stock_purchase_amount(amount_message, state, self.stock_service, self.incubation)

        self.assertTrue(state.cleared)
        self.assertIn("Покупка добавлена", amount_message.answers[-1][0])
        estimates = self.stock_service.list_estimates(1)
        self.assertEqual(estimates[0].remaining_kg, 50)

    async def test_feed_add_redirects_to_stock_purchase(self) -> None:
        state = FakeState()
        callback = FakeCallback("feeds:add")

        await feed_add(callback, state)

        self.assertEqual(state.state, StockPurchaseFlow.name)
        self.assertIn("позиции склада", callback.message.answers[-1][0])
        self.assertTrue(callback.answered)

    async def test_feed_command_redirects_to_stock_purchase(self) -> None:
        state = FakeState()
        message = FakeMessage("/feed")

        await feed_command(message, state)

        self.assertEqual(state.state, StockPurchaseFlow.name)
        self.assertIn("позиции склада", message.answers[-1][0])

    async def test_stale_mix_button_returns_actual_mix_dashboard(self) -> None:
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
            self.stock_service.add_purchase(
                user_id=1,
                name=name,
                kind="ingredient",
                amount_kg=1,
            )
        callback = FakeCallback("stock:mix_confirm:wheat:2")

        await stock_mix_confirm(callback, FakeState(), self.stock_service)

        self.assertIn("Остатки могли измениться", callback.message.answers[-1][0])
        self.assertIn("Актуальный расчет", callback.message.answers[-1][0])
        self.assertTrue(callback.answered)

    async def test_mix_plan_does_not_create_mix_until_confirmed(self) -> None:
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
            self.stock_service.add_purchase(
                user_id=1,
                name=name,
                kind="ingredient",
                amount_kg=100,
            )
        callback = FakeCallback("stock:mix_plan:wheat:2")
        state = FakeState()

        await stock_mix_plan(callback, state, self.stock_service)

        self.assertIn("Формула на 1 замес", callback.message.answers[-1][0])
        self.assertIn("Кукуруза: 3.5 части", callback.message.answers[-1][0])
        self.assertIn("Пшеница: 2.5 части", callback.message.answers[-1][0])
        self.assertIn("Текущий замес: 1 из 2", callback.message.answers[-1][0])
        self.assertEqual(
            [
                item.item.name
                for item in self.stock_service.list_estimates(1)
                if item.item.kind == "finished_mix"
            ],
            [],
        )
        self.assertTrue(callback.answered)

    async def test_mix_checklist_advances_one_cycle_at_a_time(self) -> None:
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
            self.stock_service.add_purchase(
                user_id=1,
                name=name,
                kind="ingredient",
                amount_kg=100,
            )
        state = FakeState()
        callback = FakeCallback("stock:mix_plan:wheat:2")

        await stock_mix_plan(callback, state, self.stock_service)
        await stock_mix_check_all(FakeCallback("stock:mix_check_all"), state, self.stock_service)
        done_callback = FakeCallback("stock:mix_cycle_done")

        await stock_mix_cycle_done(done_callback, state, self.stock_service)

        self.assertEqual(state.data["mix_current_cycle"], 2)
        self.assertEqual(state.data["mix_checked_indices"], [])
        self.assertIn("Текущий замес: 2 из 2", done_callback.message.answers[-1][0])

        await stock_mix_check_all(FakeCallback("stock:mix_check_all"), state, self.stock_service)
        confirm_callback = FakeCallback("stock:mix_confirm:wheat:2")

        await stock_mix_confirm(confirm_callback, state, self.stock_service)

        self.assertTrue(state.cleared)
        self.assertIn("Замес создан", confirm_callback.message.answers[-1][0])
        self.assertEqual(
            [
                item.item.name
                for item in self.stock_service.list_estimates(1)
                if item.item.kind == "finished_mix"
            ],
            ["Смесь для кур"],
        )

    async def test_flock_assign_item_sets_full_mix_without_percent_step(self) -> None:
        group = self.feed_service.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=10,
            species="chicken",
            role="hens",
        )
        flock = self.feed_service.create_flock(
            user_id=1,
            name="Основное стадо",
            member_group_ids=[group.id],
        )
        estimate = self.stock_service.add_purchase(
            user_id=1,
            name="Смесь для кур",
            kind="finished_mix",
            amount_kg=50,
        )
        state = FakeState()
        await state.update_data(flock_id=flock.id)
        callback = FakeCallback(f"feeds:flock_assign_item:{estimate.item.id}")

        await flock_assign_item(callback, state, self.stock_service)

        self.assertTrue(state.cleared)
        self.assertIn("Смесь назначена стаду", callback.message.answers[-1][0])
        self.assertTrue(callback.answered)


if __name__ == "__main__":
    unittest.main()
