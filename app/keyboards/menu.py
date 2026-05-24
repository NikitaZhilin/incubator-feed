from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🥚 Инкубация", callback_data="menu:incubation"),
                InlineKeyboardButton(text="🌾 Корма", callback_data="feeds:menu"),
            ],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings:menu")],
        ]
    )


def incubation_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Добавить партию", callback_data="menu:new"),
                InlineKeyboardButton(text="Активные партии", callback_data="menu:batches"),
            ],
            [
                InlineKeyboardButton(text="План на сегодня", callback_data="menu:today"),
                InlineKeyboardButton(text="Календарь работ", callback_data="menu:calendar"),
            ],
            [
                InlineKeyboardButton(text="После вывода", callback_data="menu:care"),
                InlineKeyboardButton(text="Режимы", callback_data="menu:profiles"),
            ],
            [
                InlineKeyboardButton(text="История", callback_data="menu:history"),
                InlineKeyboardButton(text="Статистика", callback_data="menu:stats"),
            ],
            [InlineKeyboardButton(text="Напоминания", callback_data="menu:reminders")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="В меню", callback_data="menu:home")],
        ]
    )


def back_to_incubation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🥚 В инкубацию", callback_data="menu:incubation")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Инкубация вкл/выкл", callback_data="settings:toggle:notify_incubation"),
                InlineKeyboardButton(text="Корма вкл/выкл", callback_data="settings:toggle:notify_feed"),
            ],
            [
                InlineKeyboardButton(text="Уход вкл/выкл", callback_data="settings:toggle:notify_post_hatch_care"),
                InlineKeyboardButton(text="Сервис вкл/выкл", callback_data="settings:toggle:notify_service"),
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )
