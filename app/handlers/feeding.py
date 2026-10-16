"""«✅ Покормил»: mark a feeding with the usual home mix, in cups."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.keyboards.menu import feeding_done_keyboard
from app.services.feeding import (
    QUICK_CUPS,
    FeedingResult,
    FeedingService,
    format_cups,
    format_kg,
    parse_cups,
    parse_mix_text,
)


router = Router()


class FeedingFlow(StatesGroup):
    cups = State()
    mix = State()
    cup_size = State()


def cups_keyboard(last_cups: float | None) -> InlineKeyboardMarkup:
    quick = list(QUICK_CUPS)
    rows: list[list[InlineKeyboardButton]] = []
    if last_cups and last_cups not in quick:
        rows.append([
            InlineKeyboardButton(
                text=f"Как в прошлый раз: {format_cups(last_cups)}",
                callback_data=f"feeding:cups:{last_cups:g}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text=("✓ " if value == last_cups else "") + format_cups(value),
            callback_data=f"feeding:cups:{value:g}",
        )
        for value in quick
    ])
    rows.append([InlineKeyboardButton(text="✏️ Другое количество", callback_data="feeding:cups:manual")])
    rows.append([InlineKeyboardButton(text="Без количества (по норме)", callback_data="feeding:cups:none")])
    rows.append([InlineKeyboardButton(text="🥣 Состав смеси", callback_data="feeding:mix")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mix_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить состав", callback_data="feeding:mix_edit")],
            [InlineKeyboardButton(text="📏 Объём кружки", callback_data="feeding:cup_size")],
            [InlineKeyboardButton(text="✅ Покормил", callback_data="feeding:done")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )


def _num(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def format_mix(service: FeedingService, user_id: int) -> str:
    mix = service.get_mix(user_id)
    total = sum(part.parts for part in mix)
    lines = [f"🥣 Моя смесь для «Покормил» (кружка {_num(service.cup_liters(user_id))} л):", ""]
    lines.extend(f"- {part.name}: {_num(part.parts)} кр." for part in mix)
    lines.extend(
        [
            "",
            f"Всего в замесе: {_num(total)} кр.",
            f"1 кружка готовой смеси ≈ {format_kg(service.mix_kg_per_cup(user_id))}.",
        ]
    )
    return "\n".join(lines)


def format_feeding_done(service: FeedingService, user_id: int, result: FeedingResult) -> str:
    event = result.event
    at = service.format_time(event)
    if result.duplicate:
        return f"Уже отмечено в {at}. Повторное нажатие не считается."
    if event.cups:
        line = f"✅ Покормил в {at}: {format_cups(event.cups)} ≈ {format_kg(event.mix_kg or 0)} смеси."
        if event.daily_norm_kg > 0 and event.mix_kg:
            line += (
                f" Норма стада {format_kg(event.daily_norm_kg)} в день "
                f"(дали {event.mix_kg / event.daily_norm_kg:.0%})."
            )
        lines = [line]
        written = [item for item in result.ingredients if item.in_stock]
        counted = [item for item in result.ingredients if not item.in_stock]
        if written:
            lines.extend(["", "Списано со склада:"])
            for item in written:
                tail = f", осталось {format_kg(item.remaining_kg)}" if item.remaining_kg is not None else ""
                lines.append(f"- {item.name}: {format_kg(item.kg)}{tail}")
        if counted:
            lines.extend([
                "",
                "Нет на складе, только учёт: "
                + ", ".join(f"{item.name} {format_kg(item.kg)}" for item in counted),
            ])
    else:
        lines = [f"✅ Отмечено: покормили в {at}."]
        if event.daily_norm_kg > 0:
            lines.append(
                f"По норме стадо ({event.bird_count} птиц) съедает около {format_kg(event.daily_norm_kg)} в день."
            )
        else:
            lines.append("Добавьте поголовье в «Корма → Поголовье и стада», чтобы бот считал норму.")
    if result.feedings_today > 1:
        lines.append(f"Сегодня это {result.feedings_today}-е кормление.")
    week = service.week(user_id, today=event.fed_date)
    lines.extend([
        "",
        f"За 7 дней: кормили {week.fed_days} из {week.days} дн., ушло около {format_kg(week.estimated_kg)} смеси.",
    ])
    return "\n".join(lines)


async def _record(target: Message, service: FeedingService, user_id: int, cups: float | None) -> None:
    result = service.record(user_id, cups=cups)
    await target.answer(
        format_feeding_done(service, user_id, result),
        reply_markup=feeding_done_keyboard(result.event.id),
    )


@router.callback_query(F.data == "feeding:done")
async def feeding_done(callback: CallbackQuery, state: FSMContext, feeding_service: FeedingService) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        "Сколько кружек смеси дали?",
        reply_markup=cups_keyboard(feeding_service.last_cups(callback.from_user.id)),
    )


@router.callback_query(F.data.startswith("feeding:cups:"))
async def feeding_cups(callback: CallbackQuery, state: FSMContext, feeding_service: FeedingService) -> None:
    value = str(callback.data).rsplit(":", 1)[1]
    if value == "manual":
        await state.set_state(FeedingFlow.cups)
        await callback.answer()
        await callback.message.answer("Сколько кружек дали? Например: 3,5\n\nОтмена: /cancel")
        return
    cups = None
    if value != "none":
        try:
            cups = parse_cups(value)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
    await state.clear()
    await callback.answer("Отмечено ✅")
    await _record(callback.message, feeding_service, callback.from_user.id, cups)


@router.message(FeedingFlow.cups)
async def feeding_cups_text(message: Message, state: FSMContext, feeding_service: FeedingService) -> None:
    try:
        cups = parse_cups(message.text or "")
    except ValueError as exc:
        await message.answer(f"{exc}\n\nОтмена: /cancel")
        return
    await state.clear()
    await _record(message, feeding_service, message.from_user.id, cups)


@router.callback_query(F.data.startswith("feeding:undo:"))
async def feeding_undo(callback: CallbackQuery, feeding_service: FeedingService) -> None:
    raw_id = str(callback.data).rsplit(":", 1)[1]
    event = feeding_service.feeding.get(int(raw_id), callback.from_user.id) if raw_id.isdigit() else None
    if event is None or not feeding_service.undo(callback.from_user.id, event.id):
        await callback.answer("Эта отметка уже отменена.", show_alert=True)
        return
    await callback.answer("Отметка отменена")
    tail = " Ингредиенты возвращены на склад." if event.cups else ""
    await callback.message.answer(f"Отметка о кормлении в {feeding_service.format_time(event)} отменена.{tail}")


@router.callback_query(F.data == "feeding:mix")
async def feeding_mix(callback: CallbackQuery, state: FSMContext, feeding_service: FeedingService) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(format_mix(feeding_service, callback.from_user.id), reply_markup=mix_keyboard())


@router.callback_query(F.data == "feeding:mix_edit")
async def feeding_mix_edit(callback: CallbackQuery, state: FSMContext, feeding_service: FeedingService) -> None:
    await state.set_state(FeedingFlow.mix)
    await callback.answer()
    current = "\n".join(f"{part.name} {_num(part.parts)}" for part in feeding_service.get_mix(callback.from_user.id))
    await callback.message.answer(
        "Пришлите состав одним сообщением: ингредиент и сколько кружек кладёте в замес, каждый с новой строки.\n\n"
        f"Сейчас:\n{current}\n\nОтмена: /cancel"
    )


@router.message(FeedingFlow.mix)
async def feeding_mix_text(message: Message, state: FSMContext, feeding_service: FeedingService) -> None:
    try:
        parts = parse_mix_text(message.text or "")
    except ValueError as exc:
        await message.answer(f"{exc}\n\nОтмена: /cancel")
        return
    feeding_service.set_mix(message.from_user.id, parts)
    await state.clear()
    await message.answer(
        "Состав сохранён.\n\n" + format_mix(feeding_service, message.from_user.id),
        reply_markup=mix_keyboard(),
    )


@router.callback_query(F.data == "feeding:cup_size")
async def feeding_cup_size(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FeedingFlow.cup_size)
    await callback.answer()
    await callback.message.answer("Какой объём кружки в литрах? Например: 1 или 0,5\n\nОтмена: /cancel")


@router.message(FeedingFlow.cup_size)
async def feeding_cup_size_text(message: Message, state: FSMContext, feeding_service: FeedingService) -> None:
    raw = (message.text or "").strip().lower().replace(",", ".").removesuffix("л").strip()
    try:
        liters = float(raw)
        feeding_service.set_cup_liters(message.from_user.id, liters)
    except ValueError as exc:
        text = str(exc) if "Объём" in str(exc) else "Нужно число литров, например 1 или 0,5."
        await message.answer(f"{text}\n\nОтмена: /cancel")
        return
    await state.clear()
    await message.answer(
        "Объём кружки сохранён.\n\n" + format_mix(feeding_service, message.from_user.id),
        reply_markup=mix_keyboard(),
    )
