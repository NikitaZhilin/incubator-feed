from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard(settings: dict | None = None, *, web_url: str = "") -> InlineKeyboardMarkup:
    feature_row: list[InlineKeyboardButton] = []
    if _enabled(settings, "notify_feed"):
        feature_row.append(InlineKeyboardButton(text="🌾 Корма", callback_data="feeds:menu"))
    if _enabled(settings, "notify_incubation"):
        feature_row.append(InlineKeyboardButton(text="🥚 Инкубация", callback_data="menu:incubation"))
    if _enabled(settings, "notify_eggs"):
        feature_row.append(InlineKeyboardButton(text="🥚 Яйца", callback_data="eggs:menu"))

    rows: list[list[InlineKeyboardButton]] = []
    if feature_row:
        rows.append(feature_row)
    rows.extend(
        [
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:main")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings:menu")],
        ]
    )
    rows.append([_web_button(web_url)])
    rows.append([InlineKeyboardButton(text="🔗 Поделиться ботом", callback_data="menu:share")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def incubation_menu_keyboard(settings: dict | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Добавить партию", callback_data="menu:new"),
            InlineKeyboardButton(text="Активные партии", callback_data="menu:batches"),
        ],
        [
            InlineKeyboardButton(text="План на сегодня", callback_data="menu:today"),
            InlineKeyboardButton(text="Календарь работ", callback_data="menu:calendar"),
        ],
        [
            InlineKeyboardButton(text="Режимы", callback_data="menu:profiles"),
        ],
        [
            InlineKeyboardButton(text="История", callback_data="menu:history"),
            InlineKeyboardButton(text="Статистика", callback_data="menu:stats"),
        ],
        [InlineKeyboardButton(text="Напоминания", callback_data="menu:reminders")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:incubation")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
    ]
    if _enabled(settings, "notify_post_hatch_care"):
        rows[2].insert(0, InlineKeyboardButton(text="После вывода", callback_data="menu:care"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def back_to_incubation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🥚 В инкубацию", callback_data="menu:incubation")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def settings_keyboard(*, web_url: str = "") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🏷 Название хозяйства", callback_data="settings:edit:farm_name")],
        [
            InlineKeyboardButton(text="🕘 Часовой пояс", callback_data="settings:edit:timezone"),
            InlineKeyboardButton(text="🔔 Время уведомлений", callback_data="settings:edit:notification_time"),
        ],
        [InlineKeyboardButton(text="🧩 Разделы и уведомления", callback_data="settings:sections")],
        [InlineKeyboardButton(text="ℹ️ О боте", callback_data="settings:about")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:settings")],
    ]
    rows.append([_web_button(web_url)])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_sections_keyboard(settings: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🥚 Инкубация: {_status_label(settings, 'notify_incubation')}",
                    callback_data="settings:toggle:notify_incubation",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🌾 Корма: {_status_label(settings, 'notify_feed')}",
                    callback_data="settings:toggle:notify_feed",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🥚 Яйца: {_status_label(settings, 'notify_eggs')}",
                    callback_data="settings:toggle:notify_eggs",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🐣 Уход после вывода: {_status_label(settings, 'notify_post_hatch_care')}",
                    callback_data="settings:toggle:notify_post_hatch_care",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔔 Системные сообщения: {_status_label(settings, 'notify_service')}",
                    callback_data="settings:toggle:notify_service",
                )
            ],
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:settings_sections")],
            [InlineKeyboardButton(text="⬅️ Настройки", callback_data="settings:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def settings_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Настройки", callback_data="settings:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def about_bot_keyboard(*, github_url: str, changelog_url: str, web_url: str = "") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📦 GitHub", url=github_url),
            InlineKeyboardButton(text="📝 История изменений", url=changelog_url),
        ],
    ]
    rows.append([_web_button(web_url)])
    rows.extend(
        [
            [InlineKeyboardButton(text="⬅️ Настройки", callback_data="settings:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _enabled(settings: dict | None, field: str) -> bool:
    if settings is None:
        return True
    return bool(settings.get(field, True))


def _web_button(web_url: str) -> InlineKeyboardButton:
    if web_url:
        return InlineKeyboardButton(text="🌐 Открыть сайт", url=web_url)
    return InlineKeyboardButton(text="🌐 Открыть сайт", callback_data="menu:web")


def _status_label(settings: dict, field: str) -> str:
    return "включено" if _enabled(settings, field) else "выключено"
