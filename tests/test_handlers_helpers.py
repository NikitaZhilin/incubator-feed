import unittest
from pathlib import Path

from app.config import AppConfig
from app.handlers.common import build_share_text
from app.handlers.incubation import _adjust_number
from app.handlers.settings import format_about_bot


class HandlerHelpersTest(unittest.TestCase):
    def test_share_text_explains_isolated_accounts(self) -> None:
        text = build_share_text("test_incubator_bot")

        self.assertIn("https://t.me/test_incubator_bot?start=share", text)
        self.assertIn("Каждый Telegram-аккаунт работает изолированно", text)

    def test_adjust_number_respects_minimum(self) -> None:
        self.assertEqual(_adjust_number(1, "-10", min_value=1), 1)

    def test_adjust_number_respects_maximum(self) -> None:
        self.assertEqual(_adjust_number(8, "+10", min_value=0, max_value=10), 10)

    def test_adjust_number_supports_max_action(self) -> None:
        self.assertEqual(_adjust_number(3, "max", min_value=0, max_value=12), 12)

    def test_about_bot_contains_version_links_and_release_notes(self) -> None:
        config = AppConfig(
            bot_token="123:test",
            db_path=Path("test.db"),
            log_file=Path("bot.log"),
            backup_dir=Path("backups"),
            admin_ids=frozenset(),
            environment="dev",
            log_level=20,
            reminder_interval_seconds=60,
            min_free_disk_mb=512,
            release_version="0.1.42-beta",
            release_notes="Исправлен расчет смеси; Добавлен экран версии",
            release_notice_enabled=False,
            release_channel="beta",
            release_importance="minor",
            github_url="https://github.com/example/project",
            changelog_url="https://github.com/example/project/blob/main/CHANGELOG.md",
        )

        text = format_about_bot(config)

        self.assertIn("Версия: 0.1.42-beta", text)
        self.assertIn("Канал: beta", text)
        self.assertIn("https://github.com/example/project", text)
        self.assertIn("- Исправлен расчет смеси", text)
        self.assertIn("Бот находится в тестировании", text)


if __name__ == "__main__":
    unittest.main()
