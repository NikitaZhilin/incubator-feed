from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def feeds_menu_keyboard(feed_buttons: list[tuple[int, str]] | None = None) -> InlineKeyboardMarkup:
    rows = []
    for feed_id, name in feed_buttons or []:
        rows.append([InlineKeyboardButton(text=f"🌾 {name[:28]}", callback_data=f"feeds:view:{feed_id}")])
    rows.append(
        [
            InlineKeyboardButton(text="➕ Добавить корм", callback_data="stock:purchase"),
            InlineKeyboardButton(text="🧮 Смесь", callback_data="feeds:mix"),
        ]
    )
    rows.append([InlineKeyboardButton(text="📦 Склад", callback_data="stock:menu")])
    rows.append([InlineKeyboardButton(text="🐔 Поголовье и стада", callback_data="feeds:livestock")])
    rows.append([InlineKeyboardButton(text="📊 Расчеты", callback_data="feeds:stats")])
    rows.append([InlineKeyboardButton(text="❓ FAQ", callback_data="faq:feeds")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def feed_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🐔 Поголовье и стада", callback_data="feeds:livestock")],
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:feed_stats")],
            [InlineKeyboardButton(text="⬅️ К кормам", callback_data="feeds:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def livestock_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🐔 Поголовье", callback_data="feeds:groups")],
            [InlineKeyboardButton(text="🐓 Стада", callback_data="feeds:flocks")],
            [
                InlineKeyboardButton(text="➕ Добавить поголовье", callback_data="feeds:group_add"),
                InlineKeyboardButton(text="➕ Создать стадо", callback_data="feeds:flock_add"),
            ],
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:livestock")],
            [InlineKeyboardButton(text="⬅️ К кормам", callback_data="feeds:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


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


def stock_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="stock:menu")],
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
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:feed_card")],
            [InlineKeyboardButton(text="⬅️ К кормам", callback_data="feeds:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def feed_history_keyboard(feed_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:feed_history")],
            [InlineKeyboardButton(text="⬅️ Назад к корму", callback_data=f"feeds:view:{feed_id}")],
            [InlineKeyboardButton(text="🌾 К кормам", callback_data="feeds:menu")],
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
            [InlineKeyboardButton(text="⬅️ Назад к корму", callback_data=f"feeds:view:{feed_id}")],
        ]
    )


def bird_group_select_keyboard(
    groups,
    *,
    allow_skip: bool = True,
    prefix: str = "feeds:select_group",
    back_callback: str | None = None,
    back_text: str = "⬅️ Назад",
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{group.name} ({group.bird_count})", callback_data=f"{prefix}:{group.id}")]
        for group in groups
    ]
    if allow_skip:
        rows.append([InlineKeyboardButton(text="Без привязки", callback_data=f"{prefix}:none")])
    rows.append([InlineKeyboardButton(text="Создать поголовье", callback_data="feeds:group_add")])
    if back_callback:
        rows.append([InlineKeyboardButton(text=back_text, callback_data=back_callback)])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bird_groups_keyboard(groups=None) -> InlineKeyboardMarkup:
    rows = []
    for group in groups or []:
        rows.append([InlineKeyboardButton(text=f"🐔 {group.name[:30]}", callback_data=f"feeds:group_view:{group.id}")])
    rows.extend(
        [
            [InlineKeyboardButton(text="➕ Создать поголовье", callback_data="feeds:group_add")],
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:bird_groups")],
            [InlineKeyboardButton(text="⬅️ Поголовье и стада", callback_data="feeds:livestock")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bird_group_actions_keyboard(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Название", callback_data=f"feeds:group_edit:{group_id}:name"),
                InlineKeyboardButton(text="🔢 Количество", callback_data=f"feeds:group_edit:{group_id}:count"),
            ],
            [InlineKeyboardButton(text="🗑 Архивировать", callback_data=f"feeds:group_archive:{group_id}")],
            [InlineKeyboardButton(text="⬅️ К поголовью", callback_data="feeds:groups")],
        ]
    )


def flocks_keyboard(flocks=None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"🐔 {flock.name[:30]}", callback_data=f"feeds:flock_view:{flock.id}")]
        for flock in flocks or []
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text="➕ Создать стадо", callback_data="feeds:flock_add")],
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:flocks")],
            [InlineKeyboardButton(text="⬅️ Поголовье и стада", callback_data="feeds:livestock")],
            [InlineKeyboardButton(text="🌾 К кормам", callback_data="feeds:menu")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def flock_actions_keyboard(flock_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Изменить состав", callback_data=f"feeds:flock_members:{flock_id}")],
            [InlineKeyboardButton(text="🍽 Назначить смесь", callback_data=f"feeds:flock_assign:{flock_id}")],
            [InlineKeyboardButton(text="🗑 Архивировать", callback_data=f"feeds:flock_archive:{flock_id}")],
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:flock_card")],
            [InlineKeyboardButton(text="⬅️ К стадам", callback_data="feeds:flocks")],
        ]
    )


def flock_member_select_keyboard(groups, selected_ids: set[int], *, flock_id: int | None = None) -> InlineKeyboardMarkup:
    rows = []
    for group in groups:
        mark = "✅" if group.id in selected_ids else "⬜"
        prefix = "feeds:flock_member_toggle" if flock_id is not None else "feeds:flock_new_toggle"
        callback = f"{prefix}:{flock_id}:{group.id}" if flock_id is not None else f"{prefix}:{group.id}"
        rows.append([InlineKeyboardButton(text=f"{mark} {group.name[:28]}", callback_data=callback)])
    done_callback = f"feeds:flock_members_done:{flock_id}" if flock_id is not None else "feeds:flock_new_done"
    rows.append([InlineKeyboardButton(text="Готово", callback_data=done_callback)])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="feeds:flocks")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:stock")],
            [InlineKeyboardButton(text="⬅️ К кормам", callback_data="feeds:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def stock_history_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:stock_history")],
            [InlineKeyboardButton(text="⬅️ К складу", callback_data="stock:menu")],
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
            [InlineKeyboardButton(text="Отмена", callback_data="stock:menu")],
        ]
    )


def stock_items_keyboard(
    items,
    *,
    prefix: str,
    back_callback: str | None = None,
    back_text: str = "⬅️ К складу",
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=item.name[:35], callback_data=f"{prefix}:{item.id}")]
        for item in items
    ]
    if back_callback:
        rows.append([InlineKeyboardButton(text=back_text, callback_data=back_callback)])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="stock:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stock_mix_checklist_keyboard(
    plan,
    checked_indices: set[int] | None = None,
    *,
    current_cycle: int = 1,
    total_cycles: int | None = None,
) -> InlineKeyboardMarkup:
    checked = checked_indices or set()
    total = total_cycles or int(plan.mix_count)
    rows = []
    for index, ingredient in enumerate(plan.ingredients):
        mark = "✅" if index in checked else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {ingredient.name[:22]}: {_format_mix_parts(ingredient.parts)}",
                    callback_data=f"stock:mix_toggle:{index}",
                )
            ]
        )
    if plan.can_produce:
        if len(checked) >= len(plan.ingredients):
            if current_cycle < total:
                rows.append([InlineKeyboardButton(text=f"✅ Замес {current_cycle} готов", callback_data="stock:mix_cycle_done")])
            else:
                rows.append(
                    [
                        InlineKeyboardButton(
                            text="✅ Замес готов, обновить склад",
                            callback_data=f"stock:mix_confirm:{plan.grain_base_code}:{plan.mix_count:g}",
                        )
                    ]
                )
        else:
            rows.append([InlineKeyboardButton(text="Отметить все ингредиенты", callback_data="stock:mix_check_all")])
    rows.append([InlineKeyboardButton(text="⬅️ К смеси", callback_data="stock:mix")])
    rows.append([InlineKeyboardButton(text="📦 К складу", callback_data="stock:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stock_mix_mode_keyboard(plan) -> InlineKeyboardMarkup:
    total = int(plan.mix_count)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сделать сейчас", callback_data="stock:mix_mode:now")],
            [InlineKeyboardButton(text=_already_fed_mix_button_text(total), callback_data="stock:mix_mode:already_fed")],
            [InlineKeyboardButton(text="⬅️ К смеси", callback_data="stock:mix")],
            [InlineKeyboardButton(text="📦 К складу", callback_data="stock:menu")],
        ]
    )


def stock_mix_entry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сделать новый замес сейчас", callback_data="stock:mix_flow:now")],
            [
                InlineKeyboardButton(
                    text="Записать прошлый замес как уже скормленный",
                    callback_data="stock:mix_flow:already_fed",
                )
            ],
            [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:mix")],
            [
                InlineKeyboardButton(text="⬅️ К складу", callback_data="stock:menu"),
                InlineKeyboardButton(text="🌾 К кормам", callback_data="feeds:menu"),
            ],
        ]
    )


def stock_mix_unavailable_keyboard(plan, *, record_mode: str | None = None) -> InlineKeyboardMarkup:
    total = int(plan.mix_count)
    rows = []
    if record_mode != "now":
        rows.append(
            [
                InlineKeyboardButton(
                    text=_already_fed_mix_button_text(total),
                    callback_data=f"stock:mix_fed_start:{plan.grain_base_code}:{plan.mix_count:g}",
                )
            ]
        )
    base_keyboard = stock_mix_quick_keyboard(
        plan.grain_base_code,
        int(plan.max_mix_count),
        record_mode=record_mode or "now",
    )
    rows.extend(base_keyboard.inline_keyboard)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stock_mix_fed_date_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сегодня", callback_data="stock:mix_fed_date:today"),
                InlineKeyboardButton(text="7 дней назад", callback_data="stock:mix_fed_date:week_ago"),
            ],
            [InlineKeyboardButton(text="Без даты / не помню", callback_data="stock:mix_fed_date:unknown")],
            [InlineKeyboardButton(text="Ввести дату", callback_data="stock:mix_fed_date:manual")],
            [InlineKeyboardButton(text="⬅️ К смеси", callback_data="stock:mix")],
        ]
    )


def _already_fed_mix_button_text(total_cycles: int) -> str:
    if total_cycles == 1:
        return "🕘 Записать как уже скормленный"
    return "🕘 Записать как уже скормленные"


def _format_mix_parts(parts: float) -> str:
    unit = "часть" if parts == 1 else "части"
    return f"{parts:g} {unit}"


def stock_mix_quick_keyboard(
    grain_base: str,
    max_mix_count: int,
    *,
    record_mode: str = "now",
) -> InlineKeyboardMarkup:
    rows = []
    available_limit = max_mix_count
    if record_mode == "already_fed":
        available_limit = max(max_mix_count, 9)
    quick_limit = min(available_limit, 9)
    for start in range(1, quick_limit + 1, 3):
        rows.append(
            [
                InlineKeyboardButton(
                    text=_mix_quick_button_text(count, record_mode=record_mode),
                    callback_data=f"stock:mix_plan:{grain_base}:{count}",
                )
                for count in range(start, min(start + 3, quick_limit + 1))
            ]
        )
    if available_limit > quick_limit:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_mix_quick_button_text(available_limit, record_mode=record_mode, maximum=True),
                    callback_data=f"stock:mix_plan:{grain_base}:{available_limit}",
                )
            ]
        )
    wheat_label = "✓ Пшеница" if grain_base == "wheat" else "Пшеница"
    layer_grain_label = "✓ Зерносмесь" if grain_base == "layer_grain_mix" else "Зерносмесь"
    rows.append(
        [
            InlineKeyboardButton(text=wheat_label, callback_data="stock:mix_grain:wheat"),
            InlineKeyboardButton(text=layer_grain_label, callback_data="stock:mix_grain:layer_grain_mix"),
        ]
    )
    rows.append([InlineKeyboardButton(text="Ввести количество", callback_data=f"stock:mix_manual:{grain_base}")])
    rows.append([InlineKeyboardButton(text="❓ FAQ", callback_data="faq:mix")])
    rows.append([InlineKeyboardButton(text="⬅️ К выбору режима", callback_data="stock:mix")])
    rows.append(
        [
            InlineKeyboardButton(text="⬅️ К складу", callback_data="stock:menu"),
            InlineKeyboardButton(text="🌾 К кормам", callback_data="feeds:menu"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mix_quick_button_text(count: int, *, record_mode: str, maximum: bool = False) -> str:
    if record_mode == "already_fed":
        if maximum:
            return f"Списать максимум ({count})"
        return f"Списать {count} {_mix_cycle_word(count)}"
    if maximum:
        return f"Сделать максимум ({count})"
    return f"Сделать {count} {_mix_cycle_word(count)}"


def _mix_cycle_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "замес"
    if count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}:
        return "замеса"
    return "замесов"


def stock_assign_groups_keyboard(groups) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{group.name} ({group.bird_count})", callback_data=f"stock:assign_group:{group.id}")]
        for group in groups
    ]
    rows.append([InlineKeyboardButton(text="⬅️ К складу", callback_data="stock:menu")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="stock:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
