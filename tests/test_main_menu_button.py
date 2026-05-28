from types import SimpleNamespace
import unittest

from aiogram.types import MenuButtonCommands, MenuButtonWebApp

from app.main import configure_telegram_menu_button


class FakeBot:
    def __init__(self) -> None:
        self.menu_button = None

    async def set_chat_menu_button(self, *, menu_button):
        self.menu_button = menu_button


class TelegramMenuButtonTest(unittest.IsolatedAsyncioTestCase):
    async def test_https_miniapp_sets_webapp_menu_button(self) -> None:
        bot = FakeBot()
        config = SimpleNamespace(miniapp_open_url="https://incubator.example.test/?auth=secret")

        await configure_telegram_menu_button(bot, config)

        self.assertIsInstance(bot.menu_button, MenuButtonWebApp)
        self.assertEqual(bot.menu_button.text, "Открыть Mini App")
        self.assertEqual(bot.menu_button.web_app.url, "https://incubator.example.test/?auth=secret")

    async def test_without_miniapp_keeps_commands_menu_button(self) -> None:
        bot = FakeBot()
        config = SimpleNamespace(miniapp_open_url="")

        await configure_telegram_menu_button(bot, config)

        self.assertIsInstance(bot.menu_button, MenuButtonCommands)


if __name__ == "__main__":
    unittest.main()
