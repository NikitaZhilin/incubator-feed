from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


RELEASE_CALLBACK_PREFIX = "admin:rel:"
# Telegram callback_data is limited to 64 bytes.
MAX_CALLBACK_VERSION_LENGTH = 40


def release_callback(action: str, version: str) -> str:
    return f"{RELEASE_CALLBACK_PREFIX}{action}:{version[:MAX_CALLBACK_VERSION_LENGTH]}"


def parse_release_callback(data: str) -> tuple[str, str]:
    """Split 'admin:rel:<action>:<version>' into (action, version)."""
    payload = (data or "").removeprefix(RELEASE_CALLBACK_PREFIX)
    action, _, version = payload.partition(":")
    return action, version


def release_offer_keyboard(version: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📣 Разослать пользователям",
                    callback_data=release_callback("preview", version),
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить текст",
                    callback_data=release_callback("edit", version),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Не рассылать",
                    callback_data=release_callback("skip", version),
                )
            ],
        ]
    )


def release_confirm_keyboard(version: str, recipients: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ Отправить ({recipients})",
                    callback_data=release_callback("send", version),
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить текст",
                    callback_data=release_callback("edit", version),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Не рассылать",
                    callback_data=release_callback("skip", version),
                )
            ],
        ]
    )
