import unittest

from app.handlers.incubation import _adjust_number


class HandlerHelpersTest(unittest.TestCase):
    def test_adjust_number_respects_minimum(self) -> None:
        self.assertEqual(_adjust_number(1, "-10", min_value=1), 1)

    def test_adjust_number_respects_maximum(self) -> None:
        self.assertEqual(_adjust_number(8, "+10", min_value=0, max_value=10), 10)

    def test_adjust_number_supports_max_action(self) -> None:
        self.assertEqual(_adjust_number(3, "max", min_value=0, max_value=12), 12)


if __name__ == "__main__":
    unittest.main()
