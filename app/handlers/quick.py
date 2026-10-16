"""One-tap egg entry and the flock age screen."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.keyboards.eggs import eggs_menu_keyboard
from app.services.eggs import EggService
from app.services.farm_overview import eggs_recorded_on, flock_age_lines, usual_egg_counts
from app.services.feeds import FeedService


router = Router()

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
        reply_markup=eggs_menu_keyboard(),
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
