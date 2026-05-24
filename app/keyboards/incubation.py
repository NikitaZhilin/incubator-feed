from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.domain import PROFILES


def species_keyboard(prefix: str = "species") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=profile.title, callback_data=f"{prefix}:{code}")]
        for code, profile in PROFILES.items()
    ]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def date_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сегодня", callback_data="date_offset:0"),
                InlineKeyboardButton(text="Вчера", callback_data="date_offset:1"),
            ],
            [
                InlineKeyboardButton(text="3 дня назад", callback_data="date_offset:3"),
                InlineKeyboardButton(text="7 дней назад", callback_data="date_offset:7"),
            ],
            [InlineKeyboardButton(text="Ввести дату вручную", callback_data="date_manual")],
            [InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")],
        ]
    )


def skip_title_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оставить стандартное название", callback_data="title_skip")],
            [InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")],
        ]
    )


def number_adjust_keyboard(
    *,
    value: int,
    prefix: str,
    min_value: int = 0,
    max_value: int | None = None,
) -> InlineKeyboardMarkup:
    plus_values = (1, 5, 10)
    minus_values = (-1, -5, -10)
    rows = [
        [
            InlineKeyboardButton(text=f"+{step}", callback_data=f"num:{prefix}:{step}")
            for step in plus_values
        ],
        [
            InlineKeyboardButton(text=str(value), callback_data="num:noop"),
        ],
        [
            InlineKeyboardButton(text=str(step), callback_data=f"num:{prefix}:{step}")
            for step in minus_values
        ],
    ]
    if max_value is not None:
        rows.append(
            [InlineKeyboardButton(text=f"Максимум: {max_value}", callback_data=f"num:{prefix}:max")]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Готово", callback_data=f"num_done:{prefix}"),
            InlineKeyboardButton(text="Ввести вручную", callback_data=f"num_manual:{prefix}"),
        ]
    )
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def batch_actions_keyboard(batch_id: int, is_active: bool = True) -> InlineKeyboardMarkup:
    if is_active:
        rows = [
            [
                InlineKeyboardButton(text="Завершить вывод", callback_data=f"batch_complete:{batch_id}"),
                InlineKeyboardButton(text="Обновить", callback_data=f"batch_status:{batch_id}"),
            ],
            [
                InlineKeyboardButton(text="Редактировать", callback_data=f"batch_edit:{batch_id}"),
            ],
            [InlineKeyboardButton(text="В меню", callback_data="menu:home")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="Вернуть в активные", callback_data=f"batch_reopen:{batch_id}")],
            [InlineKeyboardButton(text="В меню", callback_data="menu:home")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_batch_keyboard(batch_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Яйца", callback_data=f"edit_field:{batch_id}:eggs"),
                InlineKeyboardButton(text="Дата", callback_data=f"edit_field:{batch_id}:date"),
            ],
            [
                InlineKeyboardButton(text="Название", callback_data=f"edit_field:{batch_id}:title"),
                InlineKeyboardButton(text="Заметка", callback_data=f"edit_field:{batch_id}:note"),
            ],
            [InlineKeyboardButton(text="Птица", callback_data=f"edit_field:{batch_id}:species")],
            [
                InlineKeyboardButton(text="Назад к партии", callback_data=f"batch_status:{batch_id}"),
                InlineKeyboardButton(text="В меню", callback_data="menu:home"),
            ],
        ]
    )


def edit_species_keyboard(batch_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=profile.title, callback_data=f"edit_species:{batch_id}:{code}")]
        for code, profile in PROFILES.items()
    ]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def guide_species_keyboard(prefix: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=profile.title, callback_data=f"{prefix}:{code}")]
        for code, profile in PROFILES.items()
    ]
    rows.append([InlineKeyboardButton(text="В меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
