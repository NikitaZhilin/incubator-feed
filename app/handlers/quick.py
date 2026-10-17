"""One-tap egg entry and the flock age screen."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.keyboards.eggs import eggs_menu_keyboard
from app.services.eggs import EggService
from app.services.farm_overview import eggs_recorded_on, flock_age_lines, usual_egg_counts
from app.services.feeds import FeedService


router = Router()


class BatchLossFlow(StatesGroup):
    numbers = State()


class EggNoteFlow(StatesGroup):
    note = State()

DOUBLE_TAP_SECONDS = 90


def quick_eggs_keyboard(counts: list[int], day: date, *, other_callback: str) -> InlineKeyboardMarkup:
    rows = []
    if counts:
        rows.append(
            [
                InlineKeyboardButton(text=f"{count} шт.", callback_data=f"eggs:quick:{day.isoformat()}:{count}")
                for count in counts
            ]
        )
    rows.append([InlineKeyboardButton(text="✏️ Другое число", callback_data=other_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recorded_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    """After a collection is recorded: add a note, or go back to eggs."""
    base = eggs_menu_keyboard()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Заметка к сбору", callback_data=f"eggs:note:{entry_id}")],
            *base.inline_keyboard,
        ]
    )


def collected_keyboard(counts: list[int], today: date) -> InlineKeyboardMarkup:
    markup = quick_eggs_keyboard(counts, today, other_callback="eggs:add_date:today")
    markup.inline_keyboard.extend(
        [
            [InlineKeyboardButton(text="📅 За вчера", callback_data="eggs:add_date:yesterday")],
            [InlineKeyboardButton(text="🗂 За несколько дней", callback_data="eggs:add_multi")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )
    return markup


@router.callback_query(F.data == "eggs:collected")
async def eggs_collected(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    await state.clear()
    await callback.answer()
    today = egg_service.current_date()
    counts = usual_egg_counts(egg_service.eggs, callback.from_user.id, today=today)
    already = " Сегодня уже есть запись — новая добавится к ней." if eggs_recorded_on(
        egg_service.eggs, callback.from_user.id, today
    ) else ""
    await callback.message.answer(
        f"🥚 Сколько яиц собрали сегодня?{already}", reply_markup=collected_keyboard(counts, today)
    )


@router.callback_query(F.data.startswith("eggs:quick:"))
async def eggs_quick(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    parts = str(callback.data).split(":")
    try:
        day = date.fromisoformat(parts[2])
        count = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("Не понял число.", show_alert=True)
        return
    today = egg_service.current_date()
    if day > today or day < today - timedelta(days=7):
        await callback.answer("Эта кнопка устарела: запишите сбор через «🥚 Яйца».", show_alert=True)
        return
    now = datetime.now(timezone.utc)
    for entry in egg_service.list_entries(callback.from_user.id, limit=5):
        created = entry.created_at if entry.created_at.tzinfo else entry.created_at.replace(tzinfo=timezone.utc)
        if entry.entry_date == day and entry.eggs_count == count and (now - created).total_seconds() < DOUBLE_TAP_SECONDS:
            await callback.answer("Уже записано", show_alert=False)
            return
    await state.clear()
    try:
        entry = egg_service.record_today(callback.from_user.id, count, today=day)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Записано ✅")
    total = egg_service.eggs.sum_between(callback.from_user.id, start_date=day, end_date=day)
    when = "сегодня" if day == today else day.strftime("%d.%m")
    tail = f" Всего за {when}: {total}." if total != entry.eggs_count else ""
    await callback.message.answer(
        f"🥚 Записано {when}: {entry.eggs_count} яиц.{tail}\n"
        f"Несушек в расчёте: {entry.active_hens_count} из {entry.total_hens_count}.",
        reply_markup=recorded_keyboard(entry.id),
    )


@router.callback_query(F.data == "advisor:flock_age")
async def flock_age(callback: CallbackQuery, state: FSMContext, feed_service: FeedService, egg_service: EggService) -> None:
    await state.clear()
    await callback.answer()
    today = egg_service.current_date()
    lines = ["🐔 Возраст стада и замена", ""]
    lines.extend(flock_age_lines(feed_service.list_bird_groups(callback.from_user.id), today=today))
    lines.extend(
        [
            "",
            "Куры лучше всего несутся первые 1–2 года, дальше яиц каждый год меньше. "
            "Обновлять часть стада каждый год — самый ровный способ держать яйценоскость.",
        ]
    )
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🐔 Поголовье", callback_data="feeds:groups")],
                [InlineKeyboardButton(text="🥚 Новая партия в инкубатор", callback_data="menu:new")],
                [InlineKeyboardButton(text="⬅️ К птицеводу", callback_data="advisor:menu")],
            ]
        ),
    )


# --- why eggs did not hatch ---------------------------------------------------------------


@router.callback_query(F.data.startswith("batch_losses:"))
async def batch_losses_start(callback: CallbackQuery, state: FSMContext, incubation_service) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    batch = incubation_service.get_batch(int(raw), callback.from_user.id) if raw.isdigit() else None
    if batch is None or batch.is_active or batch.hatched_count is None:
        await callback.answer("Сначала завершите вывод партии.", show_alert=True)
        return
    await state.set_state(BatchLossFlow.numbers)
    await state.update_data(loss_batch_id=batch.id)
    await callback.answer()
    left = batch.eggs_count - batch.hatched_count
    await callback.message.answer(
        f"«{batch.title}»: заложено {batch.eggs_count}, вывелось {batch.hatched_count}, не вывелось {left}.\n\n"
        "Напишите три числа через пробел:\n"
        "1) неоплод — на овоскопе яйцо светлое, зародыша не было;\n"
        "2) замершие — зародыш погиб во время инкубации;\n"
        "3) не вылупились — птенец сформировался, но не вывелся.\n\n"
        "Например: 3 2 1. Если чего-то не знаете — пишите 0.\n\nОтмена: /cancel"
    )


@router.message(BatchLossFlow.numbers)
async def batch_losses_text(message: Message, state: FSMContext, incubation_service) -> None:
    from app.services.farm_overview import losses_lines, load_batch_losses, parse_batch_losses, save_batch_losses

    data = await state.get_data()
    batch = incubation_service.get_batch(int(data.get("loss_batch_id") or 0), message.from_user.id)
    try:
        losses = parse_batch_losses(message.text or "")
        if batch is None:
            raise ValueError("Партия не найдена.")
        save_batch_losses(incubation_service.batches.database, user_id=message.from_user.id, batch=batch, losses=losses)
    except ValueError as exc:
        await message.answer(f"{exc}\n\nОтмена: /cancel")
        return
    await state.clear()
    lines = [f"Сохранено для «{batch.title}»: неоплод {losses.infertile}, замершие {losses.dead_embryo}, не вылупились {losses.not_hatched}."]
    lines.extend(
        losses_lines(
            incubation_service.batches.list_all_for_user(message.from_user.id),
            load_batch_losses(incubation_service.batches.database, message.from_user.id),
        )
    )
    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📊 Статистика инкубации", callback_data="menu:stats")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
            ]
        ),
    )


# --- note to a collection ------------------------------------------------------------------


@router.callback_query(F.data.startswith("eggs:note:"))
async def egg_note_start(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    entry = egg_service.get_entry(callback.from_user.id, int(raw)) if raw.isdigit() else None
    if entry is None:
        await callback.answer("Запись не найдена.", show_alert=True)
        return
    await state.set_state(EggNoteFlow.note)
    await state.update_data(note_entry_id=entry.id)
    await callback.answer()
    current = f"\nСейчас: {entry.note}" if entry.note else ""
    await callback.message.answer(
        f"Заметка к сбору {entry.entry_date.strftime('%d.%m')} ({entry.eggs_count} шт.). "
        f"Например: «2 битых», «мелкие», «грязные».{current}\n\nЧтобы удалить заметку, отправьте 0.\nОтмена: /cancel"
    )


@router.message(EggNoteFlow.note)
async def egg_note_text(message: Message, state: FSMContext, egg_service: EggService) -> None:
    text = (message.text or "").strip()
    note = "" if text in {"0", "-"} else text[:200]
    data = await state.get_data()
    try:
        entry = egg_service.update_entry(
            user_id=message.from_user.id, entry_id=int(data.get("note_entry_id") or 0), note=note
        )
    except ValueError as exc:
        await state.clear()
        await message.answer(str(exc), reply_markup=eggs_menu_keyboard())
        return
    await state.clear()
    await message.answer(
        f"Заметка {'сохранена' if note else 'удалена'}: {entry.entry_date.strftime('%d.%m')}, {entry.eggs_count} шт."
        + (f" — {note}" if note else ""),
        reply_markup=eggs_menu_keyboard(),
    )
