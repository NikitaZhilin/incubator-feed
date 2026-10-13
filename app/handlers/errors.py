"""Last-resort handler for exceptions raised while processing an update.

Without it a failing button keeps spinning forever and a failing command gets no
reply at all. Here the user always gets a short answer and the error is logged.
"""

import logging

from aiogram.exceptions import TelegramBadRequest


logger = logging.getLogger(__name__)

CALLBACK_ERROR_TEXT = (
    "Не получилось выполнить действие. "
    "Возможно, кнопка устарела: откройте меню заново."
)
MESSAGE_ERROR_TEXT = "Что-то пошло не так. Попробуйте ещё раз или отправьте /cancel."


async def on_handler_error(event, analytics=None) -> bool:
    exc = event.exception
    update = event.update
    callback = getattr(update, "callback_query", None)
    message = getattr(update, "message", None)

    if _is_harmless(exc):
        if callback is not None:
            await _safe(callback.answer())
        return True

    logger.error("Unhandled error while processing update", exc_info=exc)
    if analytics is not None:
        try:
            analytics.log_critical("handler", exc)
        except Exception:
            logger.exception("Failed to record handler error")

    if callback is not None:
        await _safe(callback.answer(CALLBACK_ERROR_TEXT, show_alert=True))
    elif message is not None:
        await _safe(message.answer(MESSAGE_ERROR_TEXT))
    return True


def _is_harmless(exc: BaseException) -> bool:
    # Pressing a button that would re-render identical content.
    return isinstance(exc, TelegramBadRequest) and "message is not modified" in str(exc).lower()


async def _safe(awaitable) -> None:
    try:
        await awaitable
    except Exception:
        logger.debug("Failed to send error reply", exc_info=True)
