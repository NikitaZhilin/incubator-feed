from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def advisor_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 План на сегодня", callback_data="advisor:today")],
            [
                InlineKeyboardButton(text="🌾 Корма и замес", callback_data="advisor:feed"),
                InlineKeyboardButton(text="🧮 Когда замес", callback_data="advisor:mix_timing"),
            ],
            [
                InlineKeyboardButton(text="🥚 Мало яиц", callback_data="advisor:eggs_drop"),
                InlineKeyboardButton(text="🥚 Инкубация сегодня", callback_data="advisor:incubation_today"),
            ],
            [InlineKeyboardButton(text="🩺 Проблема с птицей", callback_data="advisor:health")],
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:poultry_advisor")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def advisor_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К птицеводу", callback_data="advisor:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def advisor_feed_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🧮 Когда замес", callback_data="advisor:mix_timing"),
                InlineKeyboardButton(text="📊 Расчеты кормов", callback_data="feeds:stats"),
            ],
            [InlineKeyboardButton(text="⬅️ К птицеводу", callback_data="advisor:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def advisor_health_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Есть красные флаги", callback_data="advisor:health:red_flags")],
            [InlineKeyboardButton(text="Нет красных флагов", callback_data="advisor:health:no_red_flags")],
            [InlineKeyboardButton(text="⬅️ К птицеводу", callback_data="advisor:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )
