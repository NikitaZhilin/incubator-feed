"""🧺 Хранение яиц: places, recount, moving eggs between places."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.services.egg_storage import AGE_CHOICES, DEFAULT_PLACES, TRAY_SIZE, storage_lines
from app.services.eggs import EggService


router = Router()


class StorageFlow(StatesGroup):
    recount = State()
    move_count = State()
    place_name = State()
    place_capacity = State()


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows]
    )


BACK = ("⬅️ К хранению", "storage:menu")
HOME = ("🏠 Главное меню", "menu:home")
CANCEL = ("Отмена", "storage:menu")


def storage_keyboard() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("🔢 Пересчитать", "storage:recount"), ("↔️ Перенести", "storage:move")],
            [("➕ Место", "storage:add"), ("⚙️ Места", "storage:places")],
            [("📤 Продал / отдал", "ledger:out")],
            [("❓ FAQ", "faq:egg_storage"), ("⬅️ К яйцам", "eggs:menu")],
            [HOME],
        ]
    )


def _storage_text(egg_service: EggService, user_id: int) -> str:
    today = egg_service.current_date()
    lines = ["🧺 Хранение яиц", ""]
    lines.extend(storage_lines(egg_service.storage, user_id, today=today, detailed=True))
    lines.extend(
        [
            "",
            "Новый сбор раскладывается сам: сначала в первое место до его вместимости, остальное — дальше по списку.",
            "Продажа и «съели» берут самые старые яйца. Если в учёте не сходится — «🔢 Пересчитать».",
        ]
    )
    return "\n".join(lines)


async def _show(target: Message, egg_service: EggService, user_id: int, prefix: str = "") -> None:
    await target.answer(prefix + _storage_text(egg_service, user_id), reply_markup=storage_keyboard())


@router.callback_query(F.data == "storage:menu")
async def storage_menu(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    await state.clear()
    await callback.answer()
    if not egg_service.storage.enabled(callback.from_user.id):
        default = " + ".join(f"{name} ({cap})" if cap else name for name, cap in DEFAULT_PLACES)
        await callback.message.answer(
            "🧺 Хранение яиц\n\n"
            "Бот будет знать, сколько яиц лежит в каждом месте и сколько им дней: новый сбор раскладывается сам "
            "(сначала дверца холодильника, когда она полна — лотки), продажа и «съели» берут самые старые.\n\n"
            f"Начать с мест «{default}»? Потом можно добавить свои, например «Полка в кладовке».",
            reply_markup=_kb(
                [
                    [("✅ Да, дверца + лотки", "storage:setup")],
                    [("➕ Создать своё место", "storage:add")],
                    [("❓ FAQ", "faq:egg_storage"), ("⬅️ К яйцам", "eggs:menu")],
                ]
            ),
        )
        return
    await _show(callback.message, egg_service, callback.from_user.id)


@router.callback_query(F.data == "storage:setup")
async def storage_setup(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    await state.clear()
    egg_service.storage.setup_default(callback.from_user.id)
    await callback.answer("Готово")
    await callback.message.answer(
        "Места созданы. Теперь внесите, сколько яиц лежит сейчас: «🔢 Пересчитать» → место → число.",
        reply_markup=storage_keyboard(),
    )


# --- recount ------------------------------------------------------------------------


def _places_rows(egg_service: EggService, user_id: int, prefix: str, *, skip: int | None = None) -> list:
    return [
        [(f"{s.place.name} ({s.total})", f"{prefix}:{s.place.id}")]
        for s in egg_service.storage.contents(user_id)
        if s.place.id != skip
    ]


@router.callback_query(F.data == "storage:recount")
async def storage_recount(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    await state.clear()
    await callback.answer()
    rows = _places_rows(egg_service, callback.from_user.id, "storage:recount_place")
    if not rows:
        await callback.message.answer("Сначала создайте место хранения.", reply_markup=storage_keyboard())
        return
    await callback.message.answer("Где пересчитать?", reply_markup=_kb([*rows, [CANCEL]]))


@router.callback_query(F.data.startswith("storage:recount_place:"))
async def storage_recount_place(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    place = egg_service.storage.get_place(callback.from_user.id, int(raw)) if raw.isdigit() else None
    if place is None:
        await callback.answer("Место не найдено.", show_alert=True)
        return
    await state.set_state(StorageFlow.recount)
    await state.update_data(storage_place=place.id)
    await callback.answer()
    await callback.message.answer(
        f"Сколько яиц сейчас лежит в «{place.name}»? Напишите число (0 — пусто).\n\nОтмена: /cancel"
    )


@router.message(StorageFlow.recount)
async def storage_recount_text(message: Message, state: FSMContext, egg_service: EggService) -> None:
    raw = (message.text or "").strip().lower().replace("шт", "").strip()
    if not raw.isdigit():
        await message.answer("Нужно число яиц, например 30.\n\nОтмена: /cancel")
        return
    data = await state.get_data()
    place_id = int(data.get("storage_place") or 0)
    stock = next((s for s in egg_service.storage.contents(message.from_user.id) if s.place.id == place_id), None)
    if stock is None:
        await state.clear()
        await message.answer("Место не найдено.", reply_markup=storage_keyboard())
        return
    actual = int(raw)
    if actual > stock.total:
        # More than the bot knows: ask how old the extra eggs are.
        await state.update_data(storage_actual=actual)
        rows = [[(label, f"storage:age:{code}")] for code, (label, _) in AGE_CHOICES.items()]
        await message.answer(
            f"В учёте {stock.total}, на деле {actual}: +{actual - stock.total}. Сколько дней этим яйцам примерно?",
            reply_markup=_kb([*rows, [CANCEL]]),
        )
        return
    await _apply_recount(message, state, egg_service, message.from_user.id, place_id, actual, "fresh")


@router.callback_query(StorageFlow.recount, F.data.startswith("storage:age:"))
async def storage_recount_age(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    age = str(callback.data).rsplit(":", 1)[1]
    data = await state.get_data()
    await callback.answer()
    await _apply_recount(
        callback.message,
        state,
        egg_service,
        callback.from_user.id,
        int(data.get("storage_place") or 0),
        int(data.get("storage_actual") or 0),
        age,
    )


async def _apply_recount(target: Message, state: FSMContext, egg_service: EggService, user_id: int, place_id: int, actual: int, age: str) -> None:
    try:
        diff = egg_service.storage.recount(user_id, place_id, actual, today=egg_service.current_date(), age=age)
    except ValueError as exc:
        await state.clear()
        await target.answer(str(exc), reply_markup=storage_keyboard())
        return
    await state.clear()
    if diff == 0:
        prefix = "Совпало с учётом.\n\n"
    elif diff < 0:
        prefix = f"Убрал {-diff} самых старых яиц (съели или продали без записи?).\n\n"
    else:
        prefix = f"Добавил {diff} яиц.\n\n"
    await _show(target, egg_service, user_id, prefix)


# --- move ---------------------------------------------------------------------------------


@router.callback_query(F.data == "storage:move")
async def storage_move(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    await state.clear()
    await callback.answer()
    stocks = egg_service.storage.contents(callback.from_user.id)
    if len(stocks) < 2:
        await callback.message.answer("Для переноса нужно хотя бы два места.", reply_markup=storage_keyboard())
        return
    rows = [[(f"{s.place.name} ({s.total})", f"storage:move_from:{s.place.id}")] for s in stocks if s.total > 0]
    if not rows:
        await callback.message.answer("В хранении пока нет яиц.", reply_markup=storage_keyboard())
        return
    await callback.message.answer("Откуда переносите?", reply_markup=_kb([*rows, [CANCEL]]))


@router.callback_query(F.data.startswith("storage:move_from:"))
async def storage_move_from(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    if not raw.isdigit():
        await callback.answer("Место не найдено.", show_alert=True)
        return
    await state.update_data(move_from=int(raw))
    await callback.answer()
    rows = _places_rows(egg_service, callback.from_user.id, "storage:move_to", skip=int(raw))
    await callback.message.answer("Куда?", reply_markup=_kb([*rows, [CANCEL]]))


@router.callback_query(F.data.startswith("storage:move_to:"))
async def storage_move_to(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    data = await state.get_data()
    if not raw.isdigit() or "move_from" not in data:
        await callback.answer("Начните перенос заново.", show_alert=True)
        return
    await state.update_data(move_to=int(raw))
    await state.set_state(StorageFlow.move_count)
    source = next((s for s in egg_service.storage.contents(callback.from_user.id) if s.place.id == data["move_from"]), None)
    await callback.answer()
    quick = [(f"Все ({source.total})", f"storage:move_n:{source.total}")] if source and source.total else []
    if source and source.total >= TRAY_SIZE:
        quick.insert(0, (f"Лоток ({TRAY_SIZE})", f"storage:move_n:{TRAY_SIZE}"))
    await callback.message.answer(
        "Сколько яиц переносите? Нажмите или напишите число.\n\nОтмена: /cancel",
        reply_markup=_kb([quick, [CANCEL]] if quick else [[CANCEL]]),
    )


async def _apply_move(target: Message, state: FSMContext, egg_service: EggService, user_id: int, count: int) -> None:
    data = await state.get_data()
    try:
        moved = egg_service.storage.move(user_id, int(data.get("move_from") or 0), int(data.get("move_to") or 0), count)
    except ValueError as exc:
        await target.answer(f"{exc}\n\nОтмена: /cancel")
        return
    await state.clear()
    await _show(target, egg_service, user_id, f"Перенесено {moved} яиц (самые старые).\n\n")


@router.callback_query(StorageFlow.move_count, F.data.startswith("storage:move_n:"))
async def storage_move_button(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    await callback.answer()
    await _apply_move(callback.message, state, egg_service, callback.from_user.id, int(raw) if raw.isdigit() else 0)


@router.message(StorageFlow.move_count)
async def storage_move_text(message: Message, state: FSMContext, egg_service: EggService) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно число яиц.\n\nОтмена: /cancel")
        return
    await _apply_move(message, state, egg_service, message.from_user.id, int(raw))


# --- places -----------------------------------------------------------------------------------


@router.callback_query(F.data == "storage:add")
async def storage_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StorageFlow.place_name)
    await callback.answer()
    await callback.message.answer("Как назвать место? Например: «Полка в кладовке», «На инкубацию».\n\nОтмена: /cancel")


@router.message(StorageFlow.place_name)
async def storage_add_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Название — хотя бы 2 буквы.\n\nОтмена: /cancel")
        return
    await state.update_data(place_name=name)
    await state.set_state(StorageFlow.place_capacity)
    await message.answer(
        "Сколько яиц туда помещается? Напишите число или 0, если без ограничения.\n"
        "Новый сбор сначала заполняет первые места до вместимости, остальное идёт в последнее.\n\nОтмена: /cancel"
    )


@router.message(StorageFlow.place_capacity)
async def storage_add_capacity(message: Message, state: FSMContext, egg_service: EggService) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно число, например 24, или 0.\n\nОтмена: /cancel")
        return
    data = await state.get_data()
    try:
        place = egg_service.storage.add_place(message.from_user.id, str(data.get("place_name") or ""), int(raw) or None)
    except ValueError as exc:
        await message.answer(f"{exc}\n\nОтмена: /cancel")
        return
    await state.clear()
    await _show(message, egg_service, message.from_user.id, f"Место «{place.name}» добавлено.\n\n")


@router.callback_query(F.data == "storage:places")
async def storage_places(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    await state.clear()
    await callback.answer()
    stocks = egg_service.storage.contents(callback.from_user.id)
    lines = ["⚙️ Места хранения (в этом порядке заполняются новым сбором):", ""]
    lines.extend(
        f"{i}. {s.place.name} — " + (f"до {s.place.capacity}" if s.place.capacity else "без ограничения") + f", сейчас {s.total}"
        for i, s in enumerate(stocks, 1)
    )
    lines.extend(["", "Удалить можно только пустое место."])
    rows = [[(f"🗑 {s.place.name}", f"storage:remove:{s.place.id}")] for s in stocks if s.total == 0]
    await callback.message.answer("\n".join(lines), reply_markup=_kb([*rows, [BACK], [HOME]]))


@router.callback_query(F.data.startswith("storage:remove:"))
async def storage_remove(callback: CallbackQuery, egg_service: EggService) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    try:
        removed = egg_service.storage.remove_place(callback.from_user.id, int(raw)) if raw.isdigit() else False
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Удалено" if removed else "Место не найдено")
    await _show(callback.message, egg_service, callback.from_user.id)
