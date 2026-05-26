from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.release_notifications import (
    AdminStartupNotificationService,
    ReleaseNotificationService,
    admin_startup_event_key,
    build_admin_startup_notice,
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
            importance="major",
        )

        self.assertIn("Важное обновление бота: 0.1.42-beta.", text)
        self.assertIn("- Добавлена ссылка на web-версию", text)
        self.assertIn("- Web-ключ теперь удобно копируется", text)
        self.assertIn("Подробнее: Настройки -> О боте.", text)
        self.assertIn("Главное меню открыто ниже.", text)
        self.assertIn("Бот находится в тестировании", text)

    def test_medium_release_message_is_short_without_change_details(self) -> None:
        text = build_release_notice(
            "0.1.43-beta",
            "Эта строка не должна попасть в короткое сообщение",
            importance="medium",
        )

        self.assertIn("Бот обновлен до версии 0.1.43-beta и перезапущен.", text)
        self.assertIn("Спасибо за терпение", text)
        self.assertIn("Главное меню открыто ниже", text)
        self.assertIn("Настройки -> О боте", text)
        self.assertNotIn("Эта строка", text)

    def test_admin_startup_message_is_short_and_admin_only_worded(self) -> None:
        text = build_admin_startup_notice(
            version="0.1.23-beta",
            started_at=datetime(2026, 5, 26, 23, 18, tzinfo=timezone.utc),
            timezone_name="Europe/Moscow",
            commit="abcdef1234567890",
        )

        self.assertIn("Служебное уведомление", text)
        self.assertIn("Обновление выкатилось, бот перезапущен и доступен.", text)
        self.assertIn("Версия: 0.1.23-beta", text)
        self.assertIn("Коммит: abcdef123456", text)
        self.assertIn("Запуск: 27.05.2026 02:18 (Europe/Moscow)", text)
        self.assertIn("только для администраторов", text)
        self.assertNotIn("Технические изменения", text)
        self.assertNotIn("Пользовательские релизные сообщения", text)

    async def test_release_notice_is_sent_once_to_active_service_users(self) -> None:
        self.users.upsert(user_id=1, username="active")
        self.users.update_settings(user_id=1, notify_feed=False)
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
            importance="major",
            now=now,
        )
        second = await service.send_release_notice(
            version="0.1.42-beta",
            notes="Добавлена ссылка на web-версию",
            importance="major",
            now=now,
        )

        self.assertEqual(first.sent, 1)
        self.assertEqual(first.skipped, 2)
        self.assertEqual(first.failed, 0)
        self.assertEqual(second.sent, 0)
        self.assertEqual(second.skipped, 3)
        self.assertEqual([message["user_id"] for message in bot.messages], [1])
        self.assertIsNotNone(bot.messages[0]["reply_markup"])
        menu_texts = [
            button.text
            for row in bot.messages[0]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertNotIn("🌾 Корма", menu_texts)
        self.assertIn("🥚 Инкубация", menu_texts)
        self.assertTrue(
            self.notifications.was_sent(
                release_event_key("0.1.42-beta", 1)
            )
        )

    async def test_admin_startup_notice_is_sent_once_per_deploy_to_admins_only(self) -> None:
        bot = FakeBot()
        service = AdminStartupNotificationService(
            bot=bot,
            admin_ids=frozenset({2, 1}),
            notifications=self.notifications,
        )
        started_at = datetime(2026, 5, 26, 23, 18, tzinfo=timezone.utc)

        first = await service.send_startup_notice(
            version="0.1.23-beta",
            started_at=started_at,
            timezone_name="Europe/Moscow",
            mode="once_per_deploy",
            deployment_id="abcdef123456",
            commit="abcdef123456",
            now=started_at,
        )
        second = await service.send_startup_notice(
            version="0.1.23-beta",
            started_at=started_at,
            timezone_name="Europe/Moscow",
            mode="once_per_deploy",
            deployment_id="abcdef123456",
            commit="abcdef123456",
            now=started_at,
        )
        third = await service.send_startup_notice(
            version="0.1.23-beta",
            started_at=started_at,
            timezone_name="Europe/Moscow",
            mode="once_per_deploy",
            deployment_id="fedcba654321",
            commit="fedcba654321",
            now=started_at,
        )

        self.assertEqual(first.sent, 2)
        self.assertEqual(first.skipped, 0)
        self.assertEqual(first.failed, 0)
        self.assertEqual(second.sent, 0)
        self.assertEqual(second.skipped, 2)
        self.assertEqual(third.sent, 2)
        self.assertEqual([message["user_id"] for message in bot.messages], [1, 2, 1, 2])
        self.assertTrue(
            self.notifications.was_sent(
                admin_startup_event_key("0.1.23-beta", 1, "abcdef123456")
            )
        )


if __name__ == "__main__":
    unittest.main()
