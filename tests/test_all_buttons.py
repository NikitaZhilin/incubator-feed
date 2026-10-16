"""Press every reachable bot button on a seeded database.

The real dispatcher, routers and services run against a fake Telegram session.
Starting from the bot commands, every inline button that appears is pressed in
the dialog state it was shown in (as a user would press it right away). The
test fails if a press raises, is left unanswered (spinning button), lands in
the "stale button" fallback, or produces something Telegram would reject
(message longer than 4096 characters, callback_data longer than 64 bytes,
alert longer than 200 characters).

A readable report is written to button_report.txt for CI annotations.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import time
import typing
import unittest

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message, Update, User

from app.config import AppConfig
from app.handlers import register_handlers
from app.handlers.fallback import STALE_BUTTON_TEXT
from app.middlewares.callbacks import StaleCallbackMiddleware
from app.middlewares.users import UserTrackingMiddleware
from app.services.admin import AdminService
from app.services.eggs import EggService
from app.services.feeding import FeedingService
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.services.poultry_advisor import PoultryAdvisorService
from app.services.stock import StockService
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeding import FeedingRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.stock import StockRepository
from app.storage.repositories.users import UserRepository


USER_ID = 1001
BOT_TOKEN = "42:TEST"
MAX_PRESSES = 2500
REPORT_PATH = Path(__file__).resolve().parent.parent / "button_report.txt"

COMMANDS = (
    "/start", "/menu", "/help", "/today", "/batches", "/stats", "/history", "/profiles",
    "/calendar", "/care", "/remind", "/new", "/edit", "/settings", "/farm", "/timezone",
    "/units", "/disclaimer", "/feed", "/advisor", "/version", "/my_id", "/share", "/admin",
    "/cancel",
)


class FakeSession(BaseSession):
    """Answers every Bot API call successfully and records it."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self._message_id = 1000

    async def close(self) -> None:
        return None

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout=None):
        self.requests.append(method)
        returning = method.__returning__
        options = typing.get_args(returning) or (returning,)
        if Message in options:
            self._message_id += 1
            payload = {
                "message_id": self._message_id,
                "date": int(time.time()),
                "chat": {"id": USER_ID, "type": "private"},
                "from": {"id": 42, "is_bot": True, "first_name": "bot", "username": "test_bot"},
                "text": str(getattr(method, "text", None) or getattr(method, "caption", None) or "ok"),
            }
            markup = getattr(method, "reply_markup", None)
            if isinstance(markup, InlineKeyboardMarkup):
                payload["reply_markup"] = markup.model_dump(exclude_none=True)
            return Message.model_validate(payload, context={"bot": bot})
        if User in options:
            return User(id=42, is_bot=True, first_name="bot", username="test_bot")
        if bool in options:
            return True
        origin = typing.get_origin(returning)
        if origin in (list, tuple):
            return []
        return True


def _seed(database: Database) -> None:
    today = date.today()
    users = UserRepository(database)
    users.upsert(user_id=USER_ID, username="farmer", first_name="Farmer")
    users.update_settings(USER_ID, farm_name="Ферма <тест> & Ко")

    feeds = FeedRepository(database)
    feed_service = FeedService(feeds)
    stock = StockService(StockRepository(database), feeds)
    feed_service.before_ration_change = stock.checkpoint_user
    hens = feed_service.create_bird_group(
        user_id=USER_ID, name="Несушки <А>", bird_count=12, species="chicken", role="hens"
    )
    roosters = feed_service.create_bird_group(
        user_id=USER_ID, name="Петухи", bird_count=2, species="chicken", role="roosters"
    )
    feed_service.create_bird_group(
        user_id=USER_ID,
        name="Цыплята",
        bird_count=8,
        species="chicken",
        group_kind="chicks",
        hatched_at=today - timedelta(days=10),
    )
    flock = feed_service.create_flock(
        user_id=USER_ID, name="Основное & стадо", member_group_ids=[hens.id, roosters.id]
    )
    for name, kg in (
        ("Кукуруза", 40), ("Пшеница", 30), ("Ячмень", 15), ("Комбикорм", 20),
        ("Мясокостная мука", 5), ("Рыбная мука", 3), ("Ракушка", 6), ("Премикс", 1),
    ):
        stock.add_purchase(user_id=USER_ID, name=name, kind="ingredient", amount_kg=kg)
    mix = stock.add_purchase(user_id=USER_ID, name="Смесь для кур", kind="finished_mix", amount_kg=10)
    stock.assign_flock_feed(user_id=USER_ID, flock_id=flock.id, stock_item_id=mix.item.id)
    stock.produce_mix(user_id=USER_ID, mix_count=1)
    feed_service.create_feed(
        user_id=USER_ID, name="Корм <старый>", amount_kg=25, bird_count=12,
        daily_per_bird_g=120, low_threshold_kg=5,
    )

    eggs = EggService(EggRepository(database), feeds)
    for offset, count in enumerate((9, 10, 8, 11)):
        eggs.record_entry(USER_ID, count, entry_date=today - timedelta(days=offset), note="заметка & <x>")
    eggs.create_exclusion(user_id=USER_ID, hens_count=1, reason="broody")

    incubation = IncubationService(BatchRepository(database), ReminderRepository(database), users)
    incubation.create_batch(
        user_id=USER_ID, species="chicken", eggs_count=20, start_date=today - timedelta(days=5),
        title="Партия <1> & яйца",
    )
    done = incubation.create_batch(
        user_id=USER_ID, species="duck", eggs_count=10, start_date=today - timedelta(days=40)
    )
    incubation.complete_batch(
        batch_id=done.id, user_id=USER_ID, hatched_count=7, completed_at=today - timedelta(days=10)
    )


class AllButtonsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.database = Database(root / "bot.db")
        self.database.initialize()
        _seed(self.database)

        users = UserRepository(self.database)
        analytics = AnalyticsRepository(self.database)
        notifications = NotificationRepository(self.database)
        feeds = FeedRepository(self.database)
        incubation = IncubationService(BatchRepository(self.database), ReminderRepository(self.database), users, analytics)
        feed_service = FeedService(feeds, analytics)
        egg_service = EggService(EggRepository(self.database), feeds, None, timezone_name="Europe/Moscow")
        stock_service = StockService(StockRepository(self.database), feeds, analytics)
        feed_service.before_ration_change = stock_service.checkpoint_user
        config = AppConfig(
            bot_token=BOT_TOKEN,
            db_path=root / "bot.db",
            log_file=root / "bot.log",
            backup_dir=root,
            admin_ids=frozenset({USER_ID}),
            environment="test",
            log_level=20,
            reminder_interval_seconds=60,
            min_free_disk_mb=1,
            release_version="0.1.99-beta",
            release_notes="Первый пункт; Второй пункт",
            release_notice_enabled=False,
            release_channel="beta",
            release_importance="minor",
            github_url="https://github.com/example/project",
            changelog_url="https://github.com/example/project/blob/main/docs/CHANGELOG.md",
            web_public_url="https://example.sslip.io",
            web_link_token="token",
        )
        self.session = FakeSession()
        self.bot = Bot(token=BOT_TOKEN, session=self.session)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.dp["incubation_service"] = incubation
        self.dp["feed_service"] = feed_service
        self.dp["egg_service"] = egg_service
        self.dp["stock_service"] = stock_service
        self.dp["feeding_service"] = FeedingService(
            FeedingRepository(self.database), feeds, stock=stock_service, timezone_name="Europe/Moscow"
        )
        from app.services.ledger import LedgerService

        from app.services.care import CareService

        self.dp["care_service"] = CareService(self.database)
        self.dp["ledger_service"] = LedgerService(
            self.database, feed_service, feeding_service=self.dp["feeding_service"], stock_service=stock_service
        )
        self.dp["poultry_advisor_service"] = PoultryAdvisorService(
            incubation_service=incubation,
            feed_service=feed_service,
            egg_service=egg_service,
            stock_service=stock_service,
        )
        self.dp["admin_service"] = AdminService(
            database=self.database, users=users, notifications=notifications,
            analytics=analytics, config=config,
        )
        self.dp["analytics"] = analytics
        self.dp["config"] = config
        self.dp.message.middleware(UserTrackingMiddleware())
        self.dp.callback_query.middleware(StaleCallbackMiddleware())
        self.dp.callback_query.middleware(UserTrackingMiddleware())
        register_handlers(self.dp)
        self.key = StorageKey(bot_id=self.bot.id, chat_id=USER_ID, user_id=USER_ID)
        self.update_id = 0

    async def asyncTearDown(self) -> None:
        # Routers are module-level objects: detach them so other tests can attach again.
        for router in list(self.dp.sub_routers):
            router._parent_router = None
        self.dp.sub_routers.clear()
        self.temp_dir.cleanup()

    # --- helpers -------------------------------------------------------------

    def _user(self) -> dict:
        return {"id": USER_ID, "is_bot": False, "first_name": "Farmer", "username": "farmer"}

    async def _snapshot(self) -> tuple:
        storage = self.dp.storage
        return await storage.get_state(self.key), dict(await storage.get_data(self.key))

    async def _restore(self, snapshot: tuple) -> None:
        state, data = snapshot
        await self.dp.storage.set_state(self.key, state)
        await self.dp.storage.set_data(self.key, dict(data))

    def _critical_count(self) -> int:
        with self.database.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM critical_errors").fetchone()[0])

    def _last_critical(self) -> str:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT message, traceback FROM critical_errors ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return ""
        tb = (row[1] or "").strip().splitlines()
        where = next((line.strip() for line in reversed(tb) if line.strip().startswith("File ")), "")
        return f"{row[0]} @ {where}"

    async def _feed(self, payload: dict) -> list[TelegramMethod]:
        self.update_id += 1
        payload = {"update_id": self.update_id, **payload}
        before = len(self.session.requests)
        update = Update.model_validate(payload, context={"bot": self.bot})
        await self.dp.feed_update(self.bot, update)
        return self.session.requests[before:]

    async def _send_command(self, text: str) -> list[TelegramMethod]:
        command = text.split()[0]
        return await self._feed(
            {
                "message": {
                    "message_id": self.update_id + 1,
                    "date": int(time.time()),
                    "chat": {"id": USER_ID, "type": "private"},
                    "from": self._user(),
                    "text": text,
                    "entities": [{"type": "bot_command", "offset": 0, "length": len(command)}],
                }
            }
        )

    async def _press(self, data: str) -> tuple[str, list[TelegramMethod]]:
        callback_id = f"cb{self.update_id + 1}"
        requests = await self._feed(
            {
                "callback_query": {
                    "id": callback_id,
                    "from": self._user(),
                    "chat_instance": "test",
                    "data": data,
                    "message": {
                        "message_id": 5,
                        "date": int(time.time()),
                        "chat": {"id": USER_ID, "type": "private"},
                        "from": {"id": 42, "is_bot": True, "first_name": "bot"},
                        "text": "предыдущее сообщение",
                    },
                }
            }
        )
        return callback_id, requests

    # --- the crawl -------------------------------------------------------------

    async def test_every_reachable_button_works(self) -> None:
        problems: dict[str, list[str]] = {
            "errors": [], "unanswered": [], "stale": [], "telegram_limits": [],
        }
        queue: deque[tuple[str, tuple, str]] = deque()
        seen: set[str] = set()

        async def harvest(requests: list[TelegramMethod], origin: str) -> None:
            snapshot = await self._snapshot()
            for method in requests:
                text = getattr(method, "text", None)
                if isinstance(text, str) and len(text) > 4096:
                    problems["telegram_limits"].append(f"{origin}: сообщение {len(text)} символов")
                markup = getattr(method, "reply_markup", None)
                if not isinstance(markup, InlineKeyboardMarkup):
                    continue
                for row in markup.inline_keyboard:
                    for button in row:
                        if not button.text:
                            problems["telegram_limits"].append(f"{origin}: кнопка без текста")
                        data = button.callback_data
                        if data is None:
                            continue
                        if len(data.encode("utf-8")) > 64:
                            problems["telegram_limits"].append(f"{origin}: callback_data > 64 байт: {data}")
                        if data not in seen:
                            seen.add(data)
                            queue.append((data, snapshot, origin))

        for command in COMMANDS:
            await self.dp.storage.set_state(self.key, None)
            errors_before = self._critical_count()
            requests = await self._send_command(command)
            if self._critical_count() > errors_before:
                problems["errors"].append(f"{command}: {self._last_critical()}")
            await harvest(requests, command)

        presses = 0
        while queue and presses < MAX_PRESSES:
            data, snapshot, origin = queue.popleft()
            presses += 1
            await self._restore(snapshot)
            errors_before = self._critical_count()
            callback_id, requests = await self._press(data)
            label = f"{data} (из {origin})"
            if self._critical_count() > errors_before:
                problems["errors"].append(f"{label}: {self._last_critical()}")
            answers = [
                method for method in requests
                if isinstance(method, AnswerCallbackQuery) and method.callback_query_id == callback_id
            ]
            if not answers:
                problems["unanswered"].append(label)
            for answer in answers:
                if answer.text == STALE_BUTTON_TEXT:
                    problems["stale"].append(label)
                if answer.text and len(answer.text) > 200:
                    problems["telegram_limits"].append(f"{label}: всплывающий текст {len(answer.text)} символов")
            await harvest(requests, data)

        lines = [f"Нажато кнопок: {presses}, уникальных callback_data: {len(seen)}"]
        for name, items in problems.items():
            if items:
                lines.append(f"{name} ({len(items)}): " + " | ".join(items[:40]))
        with REPORT_PATH.open("a", encoding="utf-8") as report:
            report.write("Бот: " + "\n".join(lines) + "\n")

        self.assertGreater(presses, 100, "обход кнопок почти ничего не нажал")
        failures = {name: items for name, items in problems.items() if items}
        self.assertEqual(failures, {}, "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
