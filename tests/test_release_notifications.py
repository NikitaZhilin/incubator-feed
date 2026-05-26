from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.release_notifications import (
    ReleaseNotificationService,
    build_release_notice,
    release_event_key,
)
from app.storage.database import Database
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.users import UserRepository


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, user_id: int, text: str, reply_markup=None) -> None:
        self.messages.append(
            {
                "user_id": user_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )


class ReleaseNotificationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.db")
        self.database.initialize()
        self.users = UserRepository(self.database)
        self.notifications = NotificationRepository(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_release_message_contains_version_notes_menu_hint_and_disclaimer(self) -> None:
        text = build_release_notice(
            "0.1.42-beta",
            "Добавлена ссылка на web-версию; Web-ключ теперь удобно копируется",
        )

        self.assertIn("Важное обновление бота: 0.1.42-beta.", text)
        self.assertIn("- Добавлена ссылка на web-версию", text)
        self.assertIn("- Web-ключ теперь удобно копируется", text)
        self.assertIn("Подробнее: Настройки -> О боте.", text)
        self.assertIn("Бот находится в тестировании", text)

    async def test_release_notice_is_sent_once_to_active_service_users(self) -> None:
        self.users.upsert(user_id=1, username="active")
        self.users.upsert(user_id=2, username="disabled")
        self.users.update_settings(user_id=2, notify_service=False)
        self.users.upsert(user_id=3, username="inactive")
        self.users.mark_inactive(3, "blocked")
        bot = FakeBot()
        service = ReleaseNotificationService(
            bot=bot,
            users=self.users,
            notifications=self.notifications,
        )
        now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)

        first = await service.send_release_notice(
            version="0.1.42-beta",
            notes="Добавлена ссылка на web-версию",
            now=now,
        )
        second = await service.send_release_notice(
            version="0.1.42-beta",
            notes="Добавлена ссылка на web-версию",
            now=now,
        )

        self.assertEqual(first.sent, 1)
        self.assertEqual(first.skipped, 2)
        self.assertEqual(first.failed, 0)
        self.assertEqual(second.sent, 0)
        self.assertEqual(second.skipped, 3)
        self.assertEqual([message["user_id"] for message in bot.messages], [1])
        self.assertIsNotNone(bot.messages[0]["reply_markup"])
        self.assertTrue(
            self.notifications.was_sent(
                release_event_key("0.1.42-beta", 1)
            )
        )


if __name__ == "__main__":
    unittest.main()
