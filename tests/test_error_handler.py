from types import SimpleNamespace
import unittest

from app.handlers.errors import CALLBACK_ERROR_TEXT, MESSAGE_ERROR_TEXT, on_handler_error


class FakeCallback:
    def __init__(self) -> None:
        self.answers: list[tuple[str, bool]] = []

    async def answer(self, text: str = "", show_alert: bool = False, **kwargs) -> None:
        self.answers.append((text, show_alert))


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)


class FakeAnalytics:
    def __init__(self) -> None:
        self.errors: list[tuple[str, BaseException]] = []

    def log_critical(self, source: str, exc: BaseException) -> None:
        self.errors.append((source, exc))


class ErrorHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_broken_button_gets_alert_and_is_logged(self) -> None:
        callback = FakeCallback()
        analytics = FakeAnalytics()
        event = SimpleNamespace(
            update=SimpleNamespace(callback_query=callback, message=None),
            exception=ValueError("invalid literal for int()"),
        )

        handled = await on_handler_error(event, analytics=analytics)

        self.assertTrue(handled)
        self.assertEqual(callback.answers, [(CALLBACK_ERROR_TEXT, True)])
        self.assertEqual(analytics.errors[0][0], "handler")

    async def test_failing_message_gets_reply(self) -> None:
        message = FakeMessage()
        event = SimpleNamespace(
            update=SimpleNamespace(callback_query=None, message=message),
            exception=RuntimeError("boom"),
        )

        await on_handler_error(event)

        self.assertEqual(message.answers, [MESSAGE_ERROR_TEXT])

    async def test_reply_failure_does_not_raise(self) -> None:
        class BrokenMessage:
            async def answer(self, *args, **kwargs) -> None:
                raise RuntimeError("network down")

        event = SimpleNamespace(
            update=SimpleNamespace(callback_query=None, message=BrokenMessage()),
            exception=RuntimeError("boom"),
        )

        self.assertTrue(await on_handler_error(event))


if __name__ == "__main__":
    unittest.main()
