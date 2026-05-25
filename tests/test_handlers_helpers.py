import unittest

from app.handlers.common import build_share_text
from app.handlers.incubation import _adjust_number


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


if __name__ == "__main__":
    unittest.main()
