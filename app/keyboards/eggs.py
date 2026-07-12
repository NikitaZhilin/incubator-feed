from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.domain import EggEntry
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
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:eggs")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def eggs_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К яйцам", callback_data="eggs:menu")],
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:eggs")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def eggs_history_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Исправить запись", callback_data="eggs:edit_list")],
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:egg_history")],
            [InlineKeyboardButton(text="⬅️ К яйцам", callback_data="eggs:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def egg_entries_keyboard(entries: list[EggEntry]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{entry.entry_date.isoformat()} - {entry.eggs_count} шт.",
                callback_data=f"eggs:edit:{entry.id}",
            )
        ]
        for entry in entries
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text="⬅️ К истории", callback_data="eggs:history")],
            [InlineKeyboardButton(text="Отмена", callback_data="eggs:menu")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def egg_entry_edit_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Количество", callback_data=f"eggs:edit_count:{entry_id}"),
                InlineKeyboardButton(text="📅 Дата", callback_data=f"eggs:edit_date:{entry_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ К записям", callback_data="eggs:edit_list")],
            [InlineKeyboardButton(text="Отмена", callback_data="eggs:menu")],
        ]
    )


def eggs_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="eggs:menu")],
        ]
    )


def egg_entry_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Обычный сбор", callback_data="eggs:add_regular")],
            [InlineKeyboardButton(text="Сбор за несколько дней", callback_data="eggs:add_multi")],
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


def egg_multi_day_collection_date_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сегодня", callback_data="eggs:multi_date:today"),
                InlineKeyboardButton(text="Вчера", callback_data="eggs:multi_date:yesterday"),
            ],
            [InlineKeyboardButton(text="Ввести дату", callback_data="eggs:multi_date:manual")],
            [InlineKeyboardButton(text="Отмена", callback_data="eggs:menu")],
        ]
    )


def egg_multi_day_period_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Указать количество дней", callback_data="eggs:multi_days:manual")],
            [InlineKeyboardButton(text="Не помню период", callback_data="eggs:multi_days:auto")],
            [InlineKeyboardButton(text="Отмена", callback_data="eggs:menu")],
        ]
    )


def egg_multi_day_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Записать", callback_data="eggs:multi_days:confirm")],
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
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:egg_exclusions")],
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
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:egg_weather")],
            [InlineKeyboardButton(text="⬅️ К яйцам", callback_data="eggs:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )
