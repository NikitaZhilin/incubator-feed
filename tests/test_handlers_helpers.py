import unittest
from pathlib import Path

from app.config import AppConfig
from app.handlers.common import build_share_text
from app.handlers.incubation import _adjust_number
from app.handlers.settings import (
    _format_sections,
    _format_settings,
    _parse_notification_time,
    format_about_bot,
)
from app.keyboards.menu import incubation_menu_keyboard, main_menu_keyboard, settings_keyboard


def _keyboard_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


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

    def test_settings_summary_is_russian_and_command_free(self) -> None:
        text = _format_settings(
            {
                "farm_name": "",
                "timezone": "Europe/Moscow",
                "notification_time": "09:00",
                "units": "metric",
            }
        )

        self.assertIn("Хозяйство: не указано", text)
        self.assertIn("Единицы: кг и граммы", text)
        self.assertNotIn("metric", text)
        self.assertNotIn("Команды:", text)

    def test_sections_summary_explains_hidden_menu_buttons(self) -> None:
        text = _format_sections(
            {
                "notify_incubation": False,
                "notify_feed": True,
                "notify_post_hatch_care": False,
                "notify_service": True,
            }
        )

        self.assertIn("пропадает из главного меню", text)
        self.assertIn("Инкубация: выключено", text)
        self.assertIn("Системные сообщения: включено", text)
        self.assertNotIn("Сервисные", text)

    def test_settings_keyboard_moves_toggles_deeper(self) -> None:
        texts = _keyboard_texts(settings_keyboard())

        self.assertIn("🧩 Разделы и уведомления", texts)
        self.assertIn("🏷 Название хозяйства", texts)
        self.assertNotIn("Инкубация вкл/выкл", texts)

    def test_main_menu_hides_disabled_sections(self) -> None:
        keyboard = main_menu_keyboard(
            {
                "notify_feed": False,
                "notify_incubation": True,
            }
        )
        texts = _keyboard_texts(keyboard)

        self.assertNotIn("🌾 Корма", texts)
        self.assertIn("🥚 Инкубация", texts)
        self.assertIn("⚙️ Настройки", texts)

    def test_incubation_menu_hides_post_hatch_care_when_disabled(self) -> None:
        keyboard = incubation_menu_keyboard({"notify_post_hatch_care": False})
        texts = _keyboard_texts(keyboard)

        self.assertNotIn("После вывода", texts)
        self.assertIn("Режимы", texts)

    def test_parse_notification_time_normalizes_and_validates(self) -> None:
        self.assertEqual(_parse_notification_time("9:05"), "09:05")
        with self.assertRaises(ValueError):
            _parse_notification_time("24:00")


if __name__ == "__main__":
    unittest.main()
