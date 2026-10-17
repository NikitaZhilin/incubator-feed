"""Light in winter, care calendar, grown chicks and the Excel export."""

from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.services.care import CareService, format_care_list
from app.services.feeds import FeedService
from app.services.insights import chick_age_text
from app.services.poultry_advisor import PoultryAdvisorService
from app.utils.dates import local_today


router = Router()


class CareFlow(StatesGroup):
    interval = State()


class GrowFlow(StatesGroup):
    hens = State()


HOME = [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")]


def _short(title: str) -> str:
    return title if len(title) <= 24 else title[:23] + "…"


def care_keyboard(tasks, *, settings: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for task in tasks:
        if settings:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"⏱ {_short(task.title)}: {task.interval_days} дн.",
                        callback_data=f"care:interval:{task.id}",
                    ),
                    InlineKeyboardButton(
                        text="⏸ Выкл" if task.is_active else "▶️ Вкл",
                        callback_data=f"care:toggle:{task.id}",
                    ),
                ]
            )
        elif task.is_active:
            rows.append(
                [
                    InlineKeyboardButton(text=f"✅ {_short(task.title)}", callback_data=f"care:done:{task.id}"),
                    InlineKeyboardButton(text="⏰ +3 дн.", callback_data=f"care:snooze:{task.id}"),
                ]
            )
    if settings:
        rows.append([InlineKeyboardButton(text="⬅️ К уходу", callback_data="care:menu")])
    else:
        rows.append([InlineKeyboardButton(text="⚙️ Сроки и включение", callback_data="care:settings")])
        rows.append([InlineKeyboardButton(text="❓ FAQ", callback_data="faq:care")])
        rows.append([InlineKeyboardButton(text="⬅️ К птицеводу", callback_data="advisor:menu")])
    rows.append(HOME)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def care_reminder_keyboard(tasks) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=f"✅ {_short(task.title)}", callback_data=f"care:done:{task.id}"),
            InlineKeyboardButton(text="⏰ +3 дн.", callback_data=f"care:snooze:{task.id}"),
        ]
        for task in tasks
    ]
    rows.append([InlineKeyboardButton(text="🗓 Весь календарь", callback_data="care:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- light ----------------------------------------------------------------------


@router.callback_query(F.data == "advisor:light")
async def advisor_light(callback: CallbackQuery, state: FSMContext, poultry_advisor_service: PoultryAdvisorService) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        poultry_advisor_service.build_light_advice(callback.from_user.id),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🌦 Город для расчёта", callback_data="eggs:weather")],
                [InlineKeyboardButton(text="⬅️ К птицеводу", callback_data="advisor:menu")],
                HOME,
            ]
        ),
    )


# --- care calendar ----------------------------------------------------------------


async def _show_care(target: Message, care_service: CareService, user_id: int, *, prefix: str = "") -> None:
    today = local_today()
    tasks = care_service.list(user_id, today=today)
    await target.answer(prefix + format_care_list(tasks, today), reply_markup=care_keyboard(tasks))


@router.callback_query(F.data == "care:menu")
async def care_menu(callback: CallbackQuery, state: FSMContext, care_service: CareService) -> None:
    await state.clear()
    await callback.answer()
    await _show_care(callback.message, care_service, callback.from_user.id)


@router.callback_query(F.data == "care:settings")
async def care_settings(callback: CallbackQuery, state: FSMContext, care_service: CareService) -> None:
    await state.clear()
    await callback.answer()
    tasks = care_service.list(callback.from_user.id, today=local_today())
    await callback.message.answer(
        "⚙️ Как часто напоминать. Нажмите на срок, чтобы изменить его, или выключите ненужное.",
        reply_markup=care_keyboard(tasks, settings=True),
    )


def _task_id(data: str) -> int | None:
    raw = str(data).rsplit(":", 1)[1]
    return int(raw) if raw.isdigit() else None


@router.callback_query(F.data.startswith("care:done:"))
async def care_done(callback: CallbackQuery, care_service: CareService) -> None:
    task_id = _task_id(callback.data)
    task = care_service.mark_done(callback.from_user.id, task_id, today=local_today()) if task_id else None
    if task is None:
        await callback.answer("Задача не найдена.", show_alert=True)
        return
    await callback.answer("Отмечено ✅")
    await _show_care(
        callback.message,
        care_service,
        callback.from_user.id,
        prefix=f"✅ {task.title}: сделано. Следующий раз — {task.next_due.strftime('%d.%m')}.\n\n",
    )


@router.callback_query(F.data.startswith("care:snooze:"))
async def care_snooze(callback: CallbackQuery, care_service: CareService) -> None:
    task_id = _task_id(callback.data)
    task = care_service.snooze(callback.from_user.id, task_id, today=local_today()) if task_id else None
    if task is None:
        await callback.answer("Задача не найдена.", show_alert=True)
        return
    await callback.answer(f"Напомню {task.next_due.strftime('%d.%m')}")


@router.callback_query(F.data.startswith("care:toggle:"))
async def care_toggle(callback: CallbackQuery, care_service: CareService) -> None:
    task_id = _task_id(callback.data)
    task = care_service.toggle(callback.from_user.id, task_id, today=local_today()) if task_id else None
    if task is None:
        await callback.answer("Задача не найдена.", show_alert=True)
        return
    await callback.answer("Включено" if task.is_active else "Выключено")
    tasks = care_service.list(callback.from_user.id, today=local_today())
    await callback.message.answer(
        f"«{task.title}»: {'напоминания включены' if task.is_active else 'напоминания выключены'}.",
        reply_markup=care_keyboard(tasks, settings=True),
    )


@router.callback_query(F.data.startswith("care:interval:"))
async def care_interval(callback: CallbackQuery, state: FSMContext, care_service: CareService) -> None:
    task_id = _task_id(callback.data)
    task = care_service.get(callback.from_user.id, task_id) if task_id else None
    if task is None:
        await callback.answer("Задача не найдена.", show_alert=True)
        return
    await state.set_state(CareFlow.interval)
    await state.update_data(care_task_id=task.id)
    await callback.answer()
    await callback.message.answer(
        f"«{task.title}»: сейчас каждые {task.interval_days} дн. Как часто напоминать? Напишите число дней.\n\nОтмена: /cancel"
    )


@router.message(CareFlow.interval)
async def care_interval_text(message: Message, state: FSMContext, care_service: CareService) -> None:
    raw = (message.text or "").strip().lower().replace("дн", "").replace(".", "").strip()
    data = await state.get_data()
    try:
        if not raw.isdigit():
            raise ValueError("Нужно целое число дней, например 30.")
        task = care_service.set_interval(message.from_user.id, int(data.get("care_task_id") or 0), int(raw))
    except ValueError as exc:
        await message.answer(f"{exc}\n\nОтмена: /cancel")
        return
    await state.clear()
    if task is None:
        await message.answer("Задача не найдена.")
        return
    tasks = care_service.list(message.from_user.id, today=local_today())
    await message.answer(
        f"Сохранено: «{task.title}» каждые {task.interval_days} дн.", reply_markup=care_keyboard(tasks, settings=True)
    )


# --- grown chicks -------------------------------------------------------------------


@router.callback_query(F.data.startswith("chicks:grow:"))
async def chicks_grow(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    group_id = _task_id(callback.data)
    group = feed_service.get_bird_group(group_id, callback.from_user.id) if group_id else None
    if group is None or not group.is_active or group.group_kind != "chicks":
        await callback.answer("Группа цыплят не найдена.", show_alert=True)
        return
    await state.set_state(GrowFlow.hens)
    await state.update_data(grow_group_id=group.id)
    await callback.answer()
    age = f", им {chick_age_text(group, local_today())}" if group.hatched_at else ""
    await callback.message.answer(
        f"«{group.name}»: {group.bird_count} птиц{age}.\n\n"
        f"Сколько из них курочек? Остальные станут петухами. Напишите число от 0 до {group.bird_count}.\n\n"
        "Если пол пока не понятен — нажмите «Пока не различить»: будет одна взрослая смешанная группа, "
        "разделить её можно позже.\n\nОтмена: /cancel",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Пока не различить", callback_data=f"chicks:mixed:{group.id}")],
                [InlineKeyboardButton(text="Отмена", callback_data="ledger:cancel")],
            ]
        ),
    )


async def _grow(target: Message, state: FSMContext, feed_service: FeedService, user_id: int, group_id: int, hens) -> None:
    try:
        created = feed_service.grow_chicks(user_id=user_id, group_id=group_id, hens=hens)
    except ValueError as exc:
        await target.answer(f"{exc}\n\nОтмена: /cancel")
        return
    await state.clear()
    lines = ["Готово: цыплята переведены во взрослых."]
    lines.extend(f"- {group.name}: {group.bird_count}" for group in created)
    lines.append("")
    lines.append("Норма корма и учёт яиц пересчитаны. Если группа была в стаде, новые группы добавлены туда же.")
    await target.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🐔 Поголовье", callback_data="feeds:groups")], HOME]
        ),
    )


@router.callback_query(F.data.startswith("chicks:mixed:"))
async def chicks_mixed(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    group_id = _task_id(callback.data)
    await callback.answer()
    if group_id:
        await _grow(callback.message, state, feed_service, callback.from_user.id, group_id, None)


@router.message(GrowFlow.hens)
async def chicks_hens_text(message: Message, state: FSMContext, feed_service: FeedService) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно число курочек, например 6.\n\nОтмена: /cancel")
        return
    data = await state.get_data()
    await _grow(message, state, feed_service, message.from_user.id, int(data.get("grow_group_id") or 0), int(raw))


# --- excel export ----------------------------------------------------------------------


@router.callback_query(F.data == "export:xlsx")
async def export_xlsx(callback: CallbackQuery, state: FSMContext, config=None) -> None:
    from app.services.export import build_farm_workbook, export_filename
    from app.storage.database import Database

    await state.clear()
    if config is None:
        await callback.answer("Выгрузка сейчас недоступна.", show_alert=True)
        return
    await callback.answer("Готовлю файл…")
    payload = await asyncio.to_thread(
        build_farm_workbook, Database(config.db_path), callback.from_user.id, timezone_name=config.timezone
    )
    await callback.message.answer_document(
        BufferedInputFile(payload, filename=export_filename(local_today())),
        caption="📥 Все данные хозяйства: яйца, кормления, склад и цены, продажи, потери, поголовье, инкубация, уход. "
        "Каждый раздел — на своём листе.",
    )
