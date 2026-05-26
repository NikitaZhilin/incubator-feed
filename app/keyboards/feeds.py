from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def feeds_menu_keyboard(feed_buttons: list[tuple[int, str]] | None = None) -> InlineKeyboardMarkup:
    rows = []
    for feed_id, name in feed_buttons or []:
        rows.append([InlineKeyboardButton(text=f"🌾 {name[:28]}", callback_data=f"feeds:view:{feed_id}")])
    rows.append(
        [
            InlineKeyboardButton(text="➕ Добавить корм", callback_data="feeds:add"),
            InlineKeyboardButton(text="🧮 Смесь", callback_data="feeds:mix"),
        ]
    )
    rows.append([InlineKeyboardButton(text="📦 Склад", callback_data="stock:menu")])
    rows.append([InlineKeyboardButton(text="🐔 Поголовье", callback_data="feeds:groups")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def feed_rate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="80 г", callback_data="feed_rate:80"),
                InlineKeyboardButton(text="110 г", callback_data="feed_rate:110"),
                InlineKeyboardButton(text="120 г", callback_data="feed_rate:120"),
            ],
            [
                InlineKeyboardButton(text="150 г", callback_data="feed_rate:150"),
                InlineKeyboardButton(text="Ввести вручную", callback_data="feed_rate:manual"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")],
        ]
    )


def feed_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")],
        ]
    )


def grain_base_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Пшеница", callback_data=f"{prefix}:wheat"),
                InlineKeyboardButton(text="Зерносмесь", callback_data=f"{prefix}:layer_grain_mix"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")],
        ]
    )


def feed_actions_keyboard(feed_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Пополнить", callback_data=f"feeds:add_amount:{feed_id}"),
                InlineKeyboardButton(text="➖ Списать", callback_data=f"feeds:write_off:{feed_id}"),
            ],
            [
                InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"feeds:edit:{feed_id}"),
                InlineKeyboardButton(text="📜 История", callback_data=f"feeds:history:{feed_id}"),
            ],
            [InlineKeyboardButton(text="🔄 Задать остаток", callback_data=f"feeds:restock:{feed_id}")],
            [InlineKeyboardButton(text="🗑 Архивировать", callback_data=f"feeds:delete:{feed_id}")],
            [InlineKeyboardButton(text="🌾 К кормам", callback_data="feeds:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def feed_delete_confirm_keyboard(feed_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить", callback_data=f"feeds:delete_confirm:{feed_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"feeds:view:{feed_id}")],
        ]
    )


def feed_edit_keyboard(feed_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Название", callback_data=f"feeds:edit_field:{feed_id}:name"),
                InlineKeyboardButton(text="Куры", callback_data=f"feeds:edit_field:{feed_id}:hens"),
            ],
            [
                InlineKeyboardButton(text="Петухи", callback_data=f"feeds:edit_field:{feed_id}:roosters"),
                InlineKeyboardButton(text="Порог", callback_data=f"feeds:edit_field:{feed_id}:threshold"),
            ],
            [
                InlineKeyboardButton(text="Расход кур", callback_data=f"feeds:edit_field:{feed_id}:hen_rate"),
                InlineKeyboardButton(text="Расход петухов", callback_data=f"feeds:edit_field:{feed_id}:rooster_rate"),
            ],
            [InlineKeyboardButton(text="Поголовье", callback_data=f"feeds:edit_field:{feed_id}:group")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"feeds:view:{feed_id}")],
        ]
    )


def bird_group_select_keyboard(groups, *, allow_skip: bool = True, prefix: str = "feeds:select_group") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{group.name} ({group.bird_count})", callback_data=f"{prefix}:{group.id}")]
        for group in groups
    ]
    if allow_skip:
        rows.append([InlineKeyboardButton(text="Без привязки", callback_data=f"{prefix}:none")])
    rows.append([InlineKeyboardButton(text="Создать поголовье", callback_data="feeds:group_add")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bird_groups_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать поголовье", callback_data="feeds:group_add")],
            [InlineKeyboardButton(text="🌾 К кормам", callback_data="feeds:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def stock_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Добавить покупку", callback_data="stock:purchase"),
                InlineKeyboardButton(text="🧮 Сделать замес", callback_data="stock:mix"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Рационы", callback_data="stock:assignments"),
                InlineKeyboardButton(text="📋 История", callback_data="stock:history"),
            ],
            [InlineKeyboardButton(text="🔄 Задать фактический остаток", callback_data="stock:adjust")],
            [InlineKeyboardButton(text="🌾 К кормам", callback_data="feeds:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def stock_kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Ингредиент", callback_data="stock:kind:ingredient"),
                InlineKeyboardButton(text="Готовая смесь", callback_data="stock:kind:finished_mix"),
            ],
            [
                InlineKeyboardButton(text="Готовый корм", callback_data="stock:kind:commercial_feed"),
                InlineKeyboardButton(text="Другое", callback_data="stock:kind:other"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")],
        ]
    )


def stock_items_keyboard(items, *, prefix: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=item.name[:35], callback_data=f"{prefix}:{item.id}")]
        for item in items
    ]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stock_confirm_mix_keyboard(mix_count: float, grain_base: str = "wheat") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Создать замес",
                    callback_data=f"stock:mix_confirm:{grain_base}:{mix_count:g}",
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")],
        ]
    )


def stock_assign_groups_keyboard(groups) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{group.name} ({group.bird_count})", callback_data=f"stock:assign_group:{group.id}")]
        for group in groups
    ]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
