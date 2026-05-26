from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.eggs import EXCLUSION_REASON_LABELS


def eggs_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Добавить яйца", callback_data="eggs:add"),
                InlineKeyboardButton(text="📊 Расчеты", callback_data="eggs:stats"),
            ],
            [
                InlineKeyboardButton(text="📅 История", callback_data="eggs:history"),
                InlineKeyboardButton(text="🐔 Не несутся", callback_data="eggs:exclusions"),
            ],
            [InlineKeyboardButton(text="🌦 Город и погода", callback_data="eggs:weather")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def eggs_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К яйцам", callback_data="eggs:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def eggs_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="eggs:menu")],
        ]
    )


def egg_entry_date_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сегодня", callback_data="eggs:add_date:today"),
                InlineKeyboardButton(text="Вчера", callback_data="eggs:add_date:yesterday"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="eggs:menu")],
        ]
    )


def exclusion_reason_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label.capitalize(), callback_data=f"eggs:exclude_reason:{code}")]
            for code, label in EXCLUSION_REASON_LABELS.items()
        ]
        + [[InlineKeyboardButton(text="Отмена", callback_data="eggs:menu")]]
    )


def exclusions_keyboard(exclusions) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"✅ Снова несется #{item.id}",
                callback_data=f"eggs:exclude_finish:{item.id}",
            )
        ]
        for item in exclusions
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text="➕ Добавить исключение", callback_data="eggs:exclude")],
            [InlineKeyboardButton(text="⬅️ К яйцам", callback_data="eggs:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def weather_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить погоду", callback_data="eggs:weather_refresh")],
            [InlineKeyboardButton(text="✏️ Изменить город", callback_data="eggs:weather_city")],
            [InlineKeyboardButton(text="⬅️ К яйцам", callback_data="eggs:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )
