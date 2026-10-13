from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.config import AppConfig
from app.handlers.admin import (
    AdminReleaseNotes,
    admin_release_action,
    admin_release_notes_input,
)
from app.keyboards.admin import parse_release_callback, release_callback
from app.services.admin import AdminService
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.users import UserRepository


ADMIN_ID = 100
VERSION = "0.1.50-beta"


class FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.username = "admin"
        self.first_name = "Admin"
        self.last_name = ""


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, user_id: int, text: str, reply_markup=None, **kwargs) -> None:
        self.messages.append((user_id, text))


class FakeMessage:
    def __init__(self, text: str = "", user_id: int = ADMIN_ID) -> None:
        self.text = text
        self.from_user = FakeUser(user_id)
        self.date = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        self.answers: list[tuple[str, object]] = []
        self.edits: list[tuple[str, object]] = []

    async def answer(self, text: str, reply_markup=None, **kwargs) -> None:
        self.answers.append((text, reply_markup))

    async def edit_text(self, text: str, reply_markup=None, **kwargs) -> None:
        self.edits.append((text, reply_markup))


class FakeCallback:
    def __init__(self, data: str, bot: FakeBot, user_id: int = ADMIN_ID) -> None:
        self.data = data
        self.from_user = FakeUser(user_id)
        self.message = FakeMessage()
        self.bot = bot
        self.alerts: list[str] = []

    async def answer(self, text: str = "", show_alert: bool = False, **kwargs) -> None:
        if show_alert:
            self.alerts.append(text)


class FakeState:
    def __init__(self) -> None:
        self.data: dict = {}
        self.state = None

    async def clear(self) -> None:
        self.data = {}
        self.state = None

    async def set_state(self, state) -> None:
        self.state = state

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict:
        return dict(self.data)


class AdminReleaseHandlersTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.database = Database(root / "test.db")
        self.database.initialize()
        self.users = UserRepository(self.database)
        self.notifications = NotificationRepository(self.database)
        config = AppConfig(
            bot_token="test",
            db_path=root / "test.db",
            log_file=root / "bot.log",
            backup_dir=root,
            admin_ids=frozenset({ADMIN_ID}),
            environment="test",
            log_level=20,
            reminder_interval_seconds=60,
            min_free_disk_mb=1,
            release_version=VERSION,
            release_notes="Из CHANGELOG",
            release_notice_enabled=False,
            release_channel="beta",
            release_importance="minor",
            github_url="",
            changelog_url="",
        )
        self.admin_service = AdminService(
            database=self.database,
            users=self.users,
            notifications=self.notifications,
            analytics=AnalyticsRepository(self.database),
            config=config,
        )
        self.users.upsert(user_id=1, username="u1")
        self.users.upsert(user_id=2, username="u2")
        self.bot = FakeBot()
        self.state = FakeState()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def _press(self, action: str, *, version: str = VERSION, user_id: int = ADMIN_ID) -> FakeCallback:
        callback = FakeCallback(release_callback(action, version), self.bot, user_id=user_id)
        await admin_release_action(callback, self.state, self.admin_service)
        return callback

    async def test_non_admin_is_rejected(self) -> None:
        callback = await self._press("send", user_id=1)

        self.assertEqual(callback.alerts, ["Недоступно"])
        self.assertEqual(self.bot.messages, [])

    async def test_old_version_button_is_rejected(self) -> None:
        callback = await self._press("send", version="0.1.1-beta")

        self.assertIn("прошлой версии", callback.alerts[0])
        self.assertEqual(self.bot.messages, [])

    async def test_preview_shows_notes_and_confirm_button(self) -> None:
        callback = await self._press("preview")

        text, keyboard = callback.message.edits[-1]
        self.assertIn("- Из CHANGELOG", text)
        self.assertIn("Получателей: 2", text)
        first_button = keyboard.inline_keyboard[0][0]
        self.assertEqual(parse_release_callback(first_button.callback_data)[0], "send")
        self.assertEqual(self.bot.messages, [])

    async def test_skip_sends_nothing(self) -> None:
        callback = await self._press("skip")

        self.assertIn("не отправлялось", callback.message.edits[-1][0])
        self.assertEqual(self.bot.messages, [])

    async def test_send_broadcasts_once(self) -> None:
        first = await self._press("send")
        await self._press("send")

        self.assertEqual(sorted(user_id for user_id, _ in self.bot.messages), [1, 2])
        self.assertIn("Из CHANGELOG", self.bot.messages[0][1])
        self.assertIn("Отправлено: 2", first.message.edits[-1][0])

    async def test_edited_notes_replace_changelog_text(self) -> None:
        await self._press("edit")
        self.assertEqual(self.state.state, AdminReleaseNotes.waiting_text)

        message = FakeMessage("Понятный пункт для людей")
        await admin_release_notes_input(message, self.state, self.admin_service)
        self.assertIsNone(self.state.state)
        self.assertIn("- Понятный пункт для людей", message.answers[-1][0])

        await self._press("send")
        self.assertIn("Понятный пункт для людей", self.bot.messages[0][1])
        self.assertNotIn("Из CHANGELOG", self.bot.messages[0][1])
