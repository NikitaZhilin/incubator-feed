from collections.abc import Awaitable, Callable
import logging
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import TelegramObject


logger = logging.getLogger(__name__)


class StaleCallbackMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramBadRequest as exc:
            message = str(exc).lower()
            stale_markers = (
                "query is too old",
                "response timeout expired",
                "query id is invalid",
            )
            if any(marker in message for marker in stale_markers):
                logger.info("Ignored stale callback answer: %s", exc)
                return None
            raise
