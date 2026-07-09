from datetime import date, datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import AppConfig
from app.domain import PROFILES, get_profile
from app.keyboards.incubation import (
    batch_actions_keyboard,
    date_choice_keyboard,
    edit_batch_back_keyboard,
    edit_batch_keyboard,
    edit_species_keyboard,
    guide_species_keyboard,
    number_adjust_keyboard,
    skip_title_keyboard,
    species_keyboard,
)
from app.keyboards.menu import (
    incubation_menu_keyboard,
    main_menu_keyboard,
    back_to_incubation_keyboard,
)
from app.services.guides import incubation_calendar, post_hatch_care
from app.services.incubation import IncubationService, to_user_local_time
from app.utils.dates import DATE_FORMAT_HINT, parse_user_date


router = Router()


class NewBatch(StatesGroup):
    species = State()
    eggs_count = State()
    start_date = State()
    title = State()


class CompleteBatch(StatesGroup):
    hatched_count = State()


class EditBatch(StatesGroup):
    value = State()
    eggs_count = State()


@router.callback_query(F.data == "num:noop")
async def noop_number_button(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    await state.clear()
    await message.answer(
        "Действие отменено.",
        reply_markup=incubation_menu_keyboard(incubation_service.get_user_settings(message.from_user.id)),
    )


@router.callback_query(StateFilter("*"), F.data == "flow:cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext, incubation_service: IncubationService) -> None:
    await state.clear()
    await _answer_callback_message(
        callback,
        "Действие отменено.",
        reply_markup=incubation_menu_keyboard(incubation_service.get_user_settings(callback.from_user.id)),
    )
    await callback.answer()


@router.message(Command("new"))
async def new_batch(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewBatch.species)
    await message.answer("Выберите птицу:", reply_markup=species_keyboard())


@router.callback_query(F.data == "menu:home")
async def menu_home(
    callback: CallbackQuery,
    state: FSMContext,
    incubation_service: IncubationService,
    config: AppConfig,
) -> None:
    await state.clear()
    await _answer_callback_message(
        callback,
        "Главное меню:",
        reply_markup=main_menu_keyboard(
            incubation_service.get_user_settings(callback.from_user.id),
            web_url=config.web_open_url,
            miniapp_url=config.miniapp_open_url,
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:incubation")
async def menu_incubation(callback: CallbackQuery, state: FSMContext, incubation_service: IncubationService) -> None:
    await state.clear()
    await _answer_callback_message(
        callback,
        "🥚 Инкубация:",
        reply_markup=incubation_menu_keyboard(incubation_service.get_user_settings(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:new")
async def menu_new(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewBatch.species)
    await _answer_callback_message(callback, "Выберите птицу:", reply_markup=species_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu:batches")
async def menu_batches(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    await _send_batches(callback, incubation_service)
    await callback.answer()


@router.callback_query(F.data == "menu:today")
async def menu_today(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    await _send_today(callback, incubation_service)
    await callback.answer()


@router.callback_query(F.data == "menu:history")
async def menu_history(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    await _send_history(callback, incubation_service)
    await callback.answer()


@router.callback_query(F.data == "menu:stats")
async def menu_stats(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    await _send_stats(callback, incubation_service)
    await callback.answer()


@router.callback_query(F.data == "menu:profiles")
async def menu_profiles(callback: CallbackQuery) -> None:
    await _send_profiles(callback)
    await callback.answer()


@router.callback_query(F.data == "menu:reminders")
async def menu_reminders(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    settings = incubation_service.get_reminder_settings(callback.from_user.id)
    status = "включены" if settings.is_enabled else "выключены"
    await _answer_callback_message(
        callback,
        f"Напоминания: {status}.\n"
        f"Время: {settings.hour:02d}:{settings.minute:02d}\n\n"
        "Команды:\n"
        "/remind 09:00 - включить или изменить время\n"
        "/remind off - выключить",
        reply_markup=back_to_incubation_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:calendar")
async def menu_calendar(callback: CallbackQuery) -> None:
    await _answer_callback_message(
        callback,
        "Для какой птицы показать календарь работ?",
        reply_markup=guide_species_keyboard("calendar_species"),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:care")
async def menu_care(callback: CallbackQuery) -> None:
    await _answer_callback_message(
        callback,
        "Для какой птицы показать уход после вывода?",
        reply_markup=guide_species_keyboard("care_species"),
    )
    await callback.answer()


@router.callback_query(NewBatch.species, F.data.startswith("species:"))
async def select_species(callback: CallbackQuery, state: FSMContext) -> None:
    species = str(callback.data).split(":", 1)[1]
    profile = get_profile(species)
    await state.update_data(species=species, eggs_count=1)
    await state.set_state(NewBatch.eggs_count)
    await _answer_callback_message(
        callback,
        f"Выбрано: {profile.title}.\n"
        "Выставьте количество яиц кнопками или отправьте число сообщением.",
        reply_markup=number_adjust_keyboard(
            value=1,
            prefix="eggs",
            min_value=1,
        ),
    )
    await callback.answer()


@router.callback_query(NewBatch.eggs_count, F.data.startswith("num:eggs:"))
async def adjust_eggs_count(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    current = int(data.get("eggs_count", 1))
    next_value = _adjust_number(current, str(callback.data).split(":", 2)[2], 1)
    await state.update_data(eggs_count=next_value)
    await _edit_callback_message(
        callback,
        "Выставьте количество яиц кнопками или отправьте число сообщением.",
        reply_markup=number_adjust_keyboard(
            value=next_value,
            prefix="eggs",
            min_value=1,
        ),
    )
    await callback.answer()


@router.callback_query(NewBatch.eggs_count, F.data == "num_done:eggs")
async def finish_eggs_count(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    eggs_count = int(data.get("eggs_count", 1))
    await state.update_data(eggs_count=eggs_count)
    await state.set_state(NewBatch.start_date)
    await _answer_callback_message(
        callback,
        f"Количество яиц: {eggs_count}.\nУкажите дату закладки: {DATE_FORMAT_HINT}.",
        reply_markup=date_choice_keyboard(),
    )
    await callback.answer()


@router.callback_query(NewBatch.eggs_count, F.data == "num_manual:eggs")
async def manual_eggs_count(callback: CallbackQuery) -> None:
    await _answer_callback_message(callback, "Отправьте количество яиц числом, например 24.")
    await callback.answer()


@router.message(NewBatch.eggs_count)
async def enter_eggs_count(
    message: Message,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    if not message.text or not message.text.strip().isdigit():
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="new_batch_eggs",
            message="invalid_number",
        )
        await message.answer("Нужно отправить количество яиц числом, например 24.")
        return

    eggs_count = int(message.text.strip())
    if eggs_count <= 0:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="new_batch_eggs",
            message="not_positive",
        )
        await message.answer("Количество яиц должно быть больше нуля.")
        return

    await state.update_data(eggs_count=eggs_count)
    await state.set_state(NewBatch.start_date)
    await message.answer(
        f"Укажите дату закладки: {DATE_FORMAT_HINT}.",
        reply_markup=date_choice_keyboard(),
    )


@router.callback_query(NewBatch.start_date, F.data.startswith("date_offset:"))
async def choose_date_offset(callback: CallbackQuery, state: FSMContext) -> None:
    days_ago = int(str(callback.data).split(":", 1)[1])
    start_date = callback.message.date.date() - timedelta(days=days_ago)
    await state.update_data(start_date=start_date)
    await state.set_state(NewBatch.title)
    label = "сегодня" if days_ago == 0 else f"{days_ago} дн. назад"
    await _answer_callback_message(
        callback,
        f"Дата закладки: {start_date.isoformat()} ({label}).\n"
        "Введите название партии или оставьте стандартное.",
        reply_markup=skip_title_keyboard(),
    )
    await callback.answer()


@router.callback_query(NewBatch.start_date, F.data == "date_manual")
async def choose_manual_date(callback: CallbackQuery) -> None:
    await _answer_callback_message(callback, f"Введите дату закладки вручную: {DATE_FORMAT_HINT}.")
    await callback.answer()


@router.message(NewBatch.start_date)
async def enter_start_date(
    message: Message,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    if not message.text:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="new_batch_start_date",
            message="empty_date",
        )
        await message.answer(f"Введите дату текстом: {DATE_FORMAT_HINT}.")
        return

    try:
        start_date = parse_user_date(message.text)
    except ValueError as exc:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="new_batch_start_date",
            message=str(exc),
        )
        await message.answer(str(exc))
        return

    await state.update_data(start_date=start_date)
    await state.set_state(NewBatch.title)
    await message.answer(
        "Введите название партии или оставьте стандартное.",
        reply_markup=skip_title_keyboard(),
    )


@router.callback_query(NewBatch.title, F.data == "title_skip")
async def skip_title(
    callback: CallbackQuery,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    await _create_batch_from_state(callback.message, callback.from_user.id, state, incubation_service, None)
    await callback.answer()


@router.message(NewBatch.title)
async def enter_title(
    message: Message,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    title = message.text.strip() if message.text else None
    await _create_batch_from_state(message, message.from_user.id, state, incubation_service, title)


@router.message(Command("batches"))
async def list_batches(message: Message, incubation_service: IncubationService) -> None:
    statuses = incubation_service.get_user_statuses(
        message.from_user.id,
        today=_user_today(message.from_user.id, incubation_service),
    )
    if not statuses:
        await message.answer("Активных партий пока нет. Добавьте первую через /new.")
        return

    for status in statuses:
        await message.answer(
            _format_status(status),
            reply_markup=batch_actions_keyboard(status.batch.id, status.batch.is_active),
        )


@router.message(Command("today"))
async def today(message: Message, incubation_service: IncubationService) -> None:
    statuses = incubation_service.get_user_statuses(
        message.from_user.id,
        today=_user_today(message.from_user.id, incubation_service),
    )
    if not statuses:
        await message.answer("На сегодня задач нет: активных партий не найдено.")
        return

    lines = ["План на сегодня:"]
    for status in statuses:
        lines.append("")
        lines.append(f"{status.batch.title}: день {_day_label(status)}, {status.stage}")
        lines.extend(f"- {item}" for item in status.recommendations[:5])
    await message.answer("\n".join(lines))


@router.message(Command("history"))
async def history(message: Message, incubation_service: IncubationService) -> None:
    batches = incubation_service.list_completed(message.from_user.id)
    if not batches:
        await message.answer("История пока пустая: завершенных партий нет.")
        return

    for batch in batches:
        status = incubation_service.get_status(batch, today=batch.completed_at)
        await message.answer(
            _format_status(status),
            reply_markup=batch_actions_keyboard(batch.id, batch.is_active),
        )


@router.message(Command("stats"))
async def stats(message: Message, incubation_service: IncubationService) -> None:
    stats_value = incubation_service.get_stats(message.from_user.id)
    hatch_rate = (
        f"{stats_value.hatch_rate:.1f}%"
        if stats_value.hatch_rate is not None
        else "нет завершенных партий"
    )
    await message.answer(
        "Статистика инкубации:\n"
        f"Всего партий: {stats_value.total_batches}\n"
        f"Активных: {stats_value.active_batches}\n"
        f"Завершенных: {stats_value.completed_batches}\n"
        f"Яиц в завершенных партиях: {stats_value.total_eggs}\n"
        f"Вывелось: {stats_value.total_hatched}\n"
        f"Процент вывода: {hatch_rate}"
    )


@router.message(Command("profiles"))
async def profiles(message: Message) -> None:
    lines = ["Режимы инкубации:"]
    for profile in PROFILES.values():
        lines.append("")
        lines.append(f"{profile.title} ({profile.hatch_days} дн.)")
        lines.append(f"- основной режим: {profile.temperature_main}, {profile.humidity_main}")
        lines.append(f"- вывод: {profile.temperature_lockdown}, {profile.humidity_lockdown}")
        lines.append(f"- переворот до {profile.turn_until_day} дня")
        lines.append(f"- овоскопирование: {', '.join(map(str, profile.candle_days))} день")
    await message.answer("\n".join(lines))


@router.message(Command("calendar"))
async def calendar_command(message: Message) -> None:
    await message.answer(
        "Для какой птицы показать календарь работ?",
        reply_markup=guide_species_keyboard("calendar_species"),
    )


@router.message(Command("care"))
async def care_command(message: Message) -> None:
    await message.answer(
        "Для какой птицы показать уход после вывода?",
        reply_markup=guide_species_keyboard("care_species"),
    )


@router.callback_query(F.data.startswith("calendar_species:"))
async def calendar_species(callback: CallbackQuery) -> None:
    species = str(callback.data).split(":", 1)[1]
    profile = get_profile(species)
    await _answer_callback_message(
        callback,
        incubation_calendar(profile),
        reply_markup=back_to_incubation_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("care_species:"))
async def care_species(callback: CallbackQuery) -> None:
    species = str(callback.data).split(":", 1)[1]
    profile = get_profile(species)
    await _answer_callback_message(
        callback,
        post_hatch_care(profile.title),
        reply_markup=back_to_incubation_keyboard(),
    )
    await callback.answer()


@router.message(Command("edit"))
async def edit_batch(message: Message, incubation_service: IncubationService) -> None:
    if not message.text:
        await message.answer(_edit_help())
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) == 1:
        batches = incubation_service.list_active(message.from_user.id)
        if not batches:
            await message.answer("Активных партий для редактирования нет.", reply_markup=incubation_menu_keyboard())
            return
        for batch in batches:
            await message.answer(
                f"Выберите, что изменить в партии #{batch.id} {batch.title}:",
                reply_markup=edit_batch_keyboard(batch.id),
            )
        return
    if len(parts) == 2 and parts[1].isdigit():
        batch = incubation_service.get_batch(int(parts[1]), message.from_user.id)
        if batch is None:
            await message.answer("Партия не найдена.")
        elif not batch.is_active:
            await message.answer("Партия уже в истории. Для правок сначала верните ее в активные.")
        else:
            await message.answer(
                f"Что изменить в партии #{batch.id}?",
                reply_markup=edit_batch_keyboard(batch.id),
            )
        return
    if len(parts) < 4:
        await message.answer(_edit_help())
        return

    _, batch_id_text, field, value = parts
    try:
        batch_id = int(batch_id_text)
    except ValueError:
        await message.answer("ID партии должен быть числом.")
        return

    field = field.lower()
    try:
        if field == "note" and value == "-":
            value = ""
        updated = await _apply_edit(
            incubation_service,
            user_id=message.from_user.id,
            batch_id=batch_id,
            field=field,
            value=value,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    if updated is None:
        await message.answer("Партия не найдена.")
        return

    await message.answer(
        "Партия обновлена.\n\n" + _format_status(incubation_service.get_status(updated)),
        reply_markup=batch_actions_keyboard(updated.id, updated.is_active),
    )


@router.message(Command("remind"))
async def remind(message: Message, incubation_service: IncubationService) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1:
        settings = incubation_service.get_reminder_settings(message.from_user.id)
        status = "включены" if settings.is_enabled else "выключены"
        await message.answer(
            f"Напоминания: {status}.\n"
            f"Время: {settings.hour:02d}:{settings.minute:02d}\n\n"
            "/remind 09:00 - включить или изменить время\n"
            "/remind off - выключить"
        )
        return

    value = parts[1].strip().lower()
    if value in {"off", "выкл", "stop"}:
        current = incubation_service.get_reminder_settings(message.from_user.id)
        incubation_service.set_reminders(
            message.from_user.id,
            enabled=False,
            hour=current.hour,
            minute=current.minute,
        )
        await message.answer("Ежедневные напоминания выключены.")
        return

    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="remind",
            message="invalid_time",
            payload={"value": value},
        )
        await message.answer("Время нужно указать в формате ЧЧ:ММ, например /remind 09:00.")
        return

    incubation_service.set_reminders(
        message.from_user.id,
        enabled=True,
        hour=parsed.hour,
        minute=parsed.minute,
    )
    await message.answer(f"Ежедневные напоминания включены на {parsed.hour:02d}:{parsed.minute:02d}.")


@router.message(Command("reopen"))
async def reopen_command(message: Message, incubation_service: IncubationService) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /reopen ID")
        return
    batch = incubation_service.reopen_batch(int(parts[1]), message.from_user.id)
    if batch is None:
        await message.answer("Партия не найдена.")
        return
    await message.answer(
        "Партия снова активна.\n\n" + _format_status(incubation_service.get_status(batch)),
        reply_markup=batch_actions_keyboard(batch.id, batch.is_active),
    )


@router.callback_query(F.data.startswith("batch_status:"))
async def batch_status(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    batch_id = int(str(callback.data).split(":", 1)[1])
    batch = incubation_service.get_batch(batch_id, callback.from_user.id)
    if batch is None:
        await _answer_callback_message(callback, "Партия не найдена.")
    else:
        await _answer_callback_message(
            callback,
            _format_status(incubation_service.get_status(batch)),
            reply_markup=batch_actions_keyboard(batch.id, batch.is_active),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("batch_edit:"))
async def edit_menu_callback(
    callback: CallbackQuery,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    await state.clear()
    batch_id = int(str(callback.data).split(":", 1)[1])
    batch = incubation_service.get_batch(batch_id, callback.from_user.id)
    if batch is None:
        await _answer_callback_message(callback, "Партия не найдена.")
    elif not batch.is_active:
        await _answer_callback_message(
            callback,
            "Партия уже в истории. Для правок сначала верните ее в активные.",
            reply_markup=batch_actions_keyboard(batch.id, batch.is_active),
        )
    else:
        await _answer_callback_message(
            callback,
            f"Что изменить в партии #{batch.id}?",
            reply_markup=edit_batch_keyboard(batch.id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("batch_edit_help:"))
async def edit_help_callback(
    callback: CallbackQuery,
    incubation_service: IncubationService,
) -> None:
    batch_id = int(str(callback.data).split(":", 1)[1])
    batch = incubation_service.get_batch(batch_id, callback.from_user.id)
    if batch is None:
        await _answer_callback_message(callback, "Партия не найдена.")
    else:
        await _answer_callback_message(
            callback,
            f"Что изменить в партии #{batch.id}?",
            reply_markup=edit_batch_keyboard(batch.id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field:"))
async def edit_field_callback(
    callback: CallbackQuery,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    _, batch_id_text, field = str(callback.data).split(":", 2)
    batch_id = int(batch_id_text)
    batch = incubation_service.get_batch(batch_id, callback.from_user.id)
    if batch is None:
        await _answer_callback_message(callback, "Партия не найдена.")
        await callback.answer()
        return
    if not batch.is_active:
        await _answer_callback_message(callback, "Партия уже в истории. Сначала верните ее в активные.")
        await callback.answer()
        return

    if field == "species":
        await state.clear()
        await _answer_callback_message(
            callback,
            "Выберите новый вид птицы:",
            reply_markup=edit_species_keyboard(batch_id),
        )
        await callback.answer()
        return

    if field == "eggs":
        await state.clear()
        await state.update_data(batch_id=batch_id, eggs_count=batch.eggs_count)
        await state.set_state(EditBatch.eggs_count)
        await _answer_callback_message(
            callback,
            "Выставьте новое количество яиц кнопками или отправьте число сообщением.",
            reply_markup=number_adjust_keyboard(
                value=batch.eggs_count,
                prefix="edit_eggs",
                min_value=1,
                back_callback=f"batch_edit:{batch_id}",
                back_text="⬅️ Назад к редактированию",
            ),
        )
        await callback.answer()
        return

    await state.clear()
    await state.update_data(batch_id=batch_id, field=field)
    await state.set_state(EditBatch.value)
    await _answer_callback_message(
        callback,
        _edit_prompt(field),
        reply_markup=edit_batch_back_keyboard(batch_id),
    )
    await callback.answer()


@router.callback_query(EditBatch.eggs_count, F.data.startswith("num:edit_eggs:"))
async def adjust_edit_eggs_count(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    current = int(data.get("eggs_count", 1))
    next_value = _adjust_number(current, str(callback.data).split(":", 2)[2], 1)
    await state.update_data(eggs_count=next_value)
    await _edit_callback_message(
        callback,
        "Выставьте новое количество яиц кнопками или отправьте число сообщением.",
        reply_markup=number_adjust_keyboard(
            value=next_value,
            prefix="edit_eggs",
            min_value=1,
            back_callback=f"batch_edit:{data['batch_id']}",
            back_text="⬅️ Назад к редактированию",
        ),
    )
    await callback.answer()


@router.callback_query(EditBatch.eggs_count, F.data == "num_done:edit_eggs")
async def finish_edit_eggs_count(
    callback: CallbackQuery,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    data = await state.get_data()
    batch_id = int(data["batch_id"])
    eggs_count = int(data.get("eggs_count", 1))
    try:
        updated = incubation_service.update_batch(
            batch_id=batch_id,
            user_id=callback.from_user.id,
            eggs_count=eggs_count,
        )
    except ValueError as exc:
        await _answer_callback_message(callback, str(exc))
        await callback.answer()
        return

    await state.clear()
    if updated is None:
        await _answer_callback_message(callback, "Партия не найдена.")
    else:
        await _answer_callback_message(
            callback,
            "Партия обновлена.\n\n" + _format_status(incubation_service.get_status(updated)),
            reply_markup=batch_actions_keyboard(updated.id, updated.is_active),
        )
    await callback.answer()


@router.callback_query(EditBatch.eggs_count, F.data == "num_manual:edit_eggs")
async def manual_edit_eggs_count(callback: CallbackQuery) -> None:
    await _answer_callback_message(callback, "Отправьте новое количество яиц числом.")
    await callback.answer()


@router.message(EditBatch.eggs_count)
async def edit_eggs_count_message(
    message: Message,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    if not message.text or not message.text.strip().isdigit():
        await message.answer("Количество яиц должно быть числом.")
        return

    data = await state.get_data()
    batch_id = int(data["batch_id"])
    try:
        updated = incubation_service.update_batch(
            batch_id=batch_id,
            user_id=message.from_user.id,
            eggs_count=int(message.text.strip()),
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await state.clear()
    if updated is None:
        await message.answer("Партия не найдена.")
        return

    await message.answer(
        "Партия обновлена.\n\n" + _format_status(incubation_service.get_status(updated)),
        reply_markup=batch_actions_keyboard(updated.id, updated.is_active),
    )


@router.callback_query(F.data.startswith("edit_species:"))
async def edit_species_callback(
    callback: CallbackQuery,
    incubation_service: IncubationService,
) -> None:
    _, batch_id_text, species = str(callback.data).split(":", 2)
    batch_id = int(batch_id_text)
    try:
        updated = incubation_service.update_batch(
            batch_id=batch_id,
            user_id=callback.from_user.id,
            species=species,
        )
    except ValueError as exc:
        await _answer_callback_message(callback, str(exc))
        await callback.answer()
        return

    if updated is None:
        await _answer_callback_message(callback, "Партия не найдена.")
    else:
        await _answer_callback_message(
            callback,
            "Партия обновлена.\n\n" + _format_status(incubation_service.get_status(updated)),
            reply_markup=batch_actions_keyboard(updated.id, updated.is_active),
        )
    await callback.answer()


@router.message(EditBatch.value)
async def edit_value_message(
    message: Message,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    data = await state.get_data()
    batch_id = int(data["batch_id"])
    field = str(data["field"])
    value = (message.text or "").strip()
    if not value:
        await message.answer("Отправьте новое значение текстом или нажмите /cancel.")
        return

    try:
        updated = await _apply_edit(
            incubation_service,
            user_id=message.from_user.id,
            batch_id=batch_id,
            field=field,
            value=value,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await state.clear()
    if updated is None:
        await message.answer("Партия не найдена.")
        return

    await message.answer(
        "Партия обновлена.\n\n" + _format_status(incubation_service.get_status(updated)),
        reply_markup=batch_actions_keyboard(updated.id, updated.is_active),
    )


@router.callback_query(F.data.startswith("batch_complete:"))
async def complete_batch_start(
    callback: CallbackQuery,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    batch_id = int(str(callback.data).split(":", 1)[1])
    batch = incubation_service.get_batch(batch_id, callback.from_user.id)
    if batch is None:
        await _answer_callback_message(callback, "Партия не найдена.")
        await callback.answer()
        return
    if not batch.is_active:
        await _answer_callback_message(callback, "Партия уже находится в истории.")
        await callback.answer()
        return
    await state.clear()
    await state.update_data(batch_id=batch_id, hatched_count=0, hatched_max=batch.eggs_count)
    await state.set_state(CompleteBatch.hatched_count)
    await _answer_callback_message(
        callback,
        "Укажите результат вывода.\n"
        "Сколько птенцов вывелось?\n"
        "Выставьте число кнопками или отправьте значение сообщением.",
        reply_markup=number_adjust_keyboard(
            value=0,
            prefix="hatched",
            min_value=0,
            max_value=batch.eggs_count,
        ),
    )
    await callback.answer()


@router.callback_query(CompleteBatch.hatched_count, F.data.startswith("num:hatched:"))
async def adjust_hatched_count(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    current = int(data.get("hatched_count", 0))
    max_value = int(data.get("hatched_max", 0))
    next_value = _adjust_number(
        current,
        str(callback.data).split(":", 2)[2],
        min_value=0,
        max_value=max_value,
    )
    await state.update_data(hatched_count=next_value)
    await _edit_callback_message(
        callback,
        "Укажите результат вывода.\n"
        "Сколько птенцов вывелось?\n"
        "Выставьте число кнопками или отправьте значение сообщением.",
        reply_markup=number_adjust_keyboard(
            value=next_value,
            prefix="hatched",
            min_value=0,
            max_value=max_value,
        ),
    )
    await callback.answer()


@router.callback_query(CompleteBatch.hatched_count, F.data == "num_done:hatched")
async def finish_hatched_count(
    callback: CallbackQuery,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    data = await state.get_data()
    batch_id = int(data["batch_id"])
    hatched_count = int(data.get("hatched_count", 0))
    try:
        batch = incubation_service.complete_batch(
            batch_id=batch_id,
            user_id=callback.from_user.id,
            hatched_count=hatched_count,
            completed_at=callback.message.date.date(),
        )
    except ValueError as exc:
        await _answer_callback_message(callback, str(exc))
        await callback.answer()
        return

    await state.clear()
    if batch is None:
        await _answer_callback_message(callback, "Партия не найдена.")
    else:
        await _answer_callback_message(
            callback,
            "Партия завершена и перенесена в историю.\n\n"
            + _format_status(incubation_service.get_status(batch, today=callback.message.date.date())),
            reply_markup=batch_actions_keyboard(batch.id, batch.is_active),
        )
    await callback.answer()


@router.callback_query(CompleteBatch.hatched_count, F.data == "num_manual:hatched")
async def manual_hatched_count(callback: CallbackQuery) -> None:
    await _answer_callback_message(callback, "Отправьте число выведенных птенцов сообщением.")
    await callback.answer()


@router.message(CompleteBatch.hatched_count)
async def complete_batch_finish(
    message: Message,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    if not message.text or not message.text.strip().isdigit():
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="complete_batch",
            message="invalid_hatched_count",
        )
        await message.answer("Нужно отправить число выведенных птенцов.")
        return

    data = await state.get_data()
    batch_id = int(data["batch_id"])
    try:
        batch = incubation_service.complete_batch(
            batch_id=batch_id,
            user_id=message.from_user.id,
            hatched_count=int(message.text.strip()),
            completed_at=message.date.date(),
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await state.clear()
    if batch is None:
        await message.answer("Партия не найдена.")
        return

    await message.answer(
        "Партия завершена и перенесена в историю.\n\n"
        + _format_status(incubation_service.get_status(batch, today=message.date.date())),
        reply_markup=batch_actions_keyboard(batch.id, batch.is_active),
    )


@router.callback_query(F.data.startswith("batch_reopen:"))
async def reopen_callback(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    batch_id = int(str(callback.data).split(":", 1)[1])
    batch = incubation_service.reopen_batch(batch_id, callback.from_user.id)
    if batch is None:
        await _answer_callback_message(callback, "Партия не найдена.")
    else:
        await _answer_callback_message(
            callback,
            "Партия снова активна.\n\n" + _format_status(incubation_service.get_status(batch)),
            reply_markup=batch_actions_keyboard(batch.id, batch.is_active),
        )
    await callback.answer()


async def _create_batch_from_state(
    message: Message,
    user_id: int,
    state: FSMContext,
    incubation_service: IncubationService,
    title: str | None,
) -> None:
    data = await state.get_data()
    batch = incubation_service.create_batch(
        user_id=user_id,
        species=str(data["species"]),
        eggs_count=int(data["eggs_count"]),
        start_date=data["start_date"],
        title=title,
    )
    had_reminder_settings = incubation_service.has_reminder_settings(user_id)
    settings = incubation_service.get_reminder_settings(user_id)
    reminders_note = ""
    if not had_reminder_settings and not settings.is_enabled:
        incubation_service.set_reminders(user_id, True, 9, 0)
        reminders_note = "\n\nЕжедневные напоминания по инкубации включены на 09:00."
    await state.clear()
    status = incubation_service.get_status(batch, today=_user_today(user_id, incubation_service))
    await message.answer(
        "Партия добавлена.\n\n" + _format_status(status) + reminders_note,
        reply_markup=batch_actions_keyboard(batch.id, batch.is_active),
    )


async def _send_batches(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    statuses = incubation_service.get_user_statuses(
        callback.from_user.id,
        today=_user_today(callback.from_user.id, incubation_service),
    )
    if not statuses:
        await _answer_callback_message(
            callback,
            "Активных партий пока нет. Можно добавить первую.",
            reply_markup=incubation_menu_keyboard(),
        )
        return

    for status in statuses:
        await _answer_callback_message(
            callback,
            _format_status(status),
            reply_markup=batch_actions_keyboard(status.batch.id, status.batch.is_active),
        )


async def _send_today(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    statuses = incubation_service.get_user_statuses(
        callback.from_user.id,
        today=_user_today(callback.from_user.id, incubation_service),
    )
    if not statuses:
        await _answer_callback_message(
            callback,
            "На сегодня задач нет: активных партий не найдено.",
            reply_markup=incubation_menu_keyboard(),
        )
        return

    lines = ["План на сегодня:"]
    for status in statuses:
        lines.append("")
        lines.append(f"{status.batch.title}: день {_day_label(status)}, {status.stage}")
        lines.extend(f"- {item}" for item in status.recommendations[:5])
    await _answer_callback_message(callback, "\n".join(lines), reply_markup=incubation_menu_keyboard())


async def _send_history(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    batches = incubation_service.list_completed(callback.from_user.id)
    if not batches:
        await _answer_callback_message(
            callback,
            "История пока пустая: завершенных партий нет.",
            reply_markup=incubation_menu_keyboard(),
        )
        return

    for batch in batches:
        status = incubation_service.get_status(batch, today=batch.completed_at)
        await _answer_callback_message(
            callback,
            _format_status(status),
            reply_markup=batch_actions_keyboard(batch.id, batch.is_active),
        )


async def _send_stats(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    stats_value = incubation_service.get_stats(callback.from_user.id)
    hatch_rate = (
        f"{stats_value.hatch_rate:.1f}%"
        if stats_value.hatch_rate is not None
        else "нет завершенных партий"
    )
    await _answer_callback_message(
        callback,
        "Статистика инкубации:\n"
        f"Всего партий: {stats_value.total_batches}\n"
        f"Активных: {stats_value.active_batches}\n"
        f"Завершенных: {stats_value.completed_batches}\n"
        f"Яиц в завершенных партиях: {stats_value.total_eggs}\n"
        f"Вывелось: {stats_value.total_hatched}\n"
        f"Процент вывода: {hatch_rate}",
        reply_markup=incubation_menu_keyboard(),
    )


async def _send_profiles(callback: CallbackQuery) -> None:
    lines = ["Режимы инкубации:"]
    for profile in PROFILES.values():
        lines.append("")
        lines.append(f"{profile.title} ({profile.hatch_days} дн.)")
        lines.append(f"- основной режим: {profile.temperature_main}, {profile.humidity_main}")
        lines.append(f"- вывод: {profile.temperature_lockdown}, {profile.humidity_lockdown}")
        lines.append(f"- переворот до {profile.turn_until_day} дня")
        lines.append(f"- овоскопирование: {', '.join(map(str, profile.candle_days))} день")
    await _answer_callback_message(callback, "\n".join(lines), reply_markup=incubation_menu_keyboard())


async def _apply_edit(
    incubation_service: IncubationService,
    *,
    user_id: int,
    batch_id: int,
    field: str,
    value: str,
):
    if field in {"count", "eggs", "яиц"}:
        if not value.isdigit():
            raise ValueError("Количество яиц должно быть числом.")
        return incubation_service.update_batch(
            batch_id=batch_id,
            user_id=user_id,
            eggs_count=int(value),
        )
    if field in {"date", "start", "дата"}:
        return incubation_service.update_batch(
            batch_id=batch_id,
            user_id=user_id,
            start_date=parse_user_date(value),
        )
    if field in {"title", "name", "название"}:
        return incubation_service.update_batch(
            batch_id=batch_id,
            user_id=user_id,
            title=value,
        )
    if field in {"note", "заметка"}:
        return incubation_service.update_batch(
            batch_id=batch_id,
            user_id=user_id,
            note=value,
        )
    if field in {"species", "bird", "птица"}:
        if value not in PROFILES:
            raise ValueError("Неизвестная птица. Используйте chicken, goose, quail, duck или muscovy_duck.")
        return incubation_service.update_batch(
            batch_id=batch_id,
            user_id=user_id,
            species=value,
        )
    raise ValueError(_edit_help(batch_id))


def _format_status(status) -> str:
    days_left_text = (
        f"до вывода {status.days_left} дн."
        if status.days_left >= 0
        else f"вывод ожидался {-status.days_left} дн. назад"
    )
    day_text = _day_label(status)
    recommendations = "\n".join(f"- {item}" for item in status.recommendations)
    completed = ""
    if not status.batch.is_active:
        rate = ""
        if status.batch.hatched_count is not None and status.batch.eggs_count:
            rate = f" ({status.batch.hatched_count / status.batch.eggs_count * 100:.1f}%)"
        completed = (
            f"\nРезультат: {status.batch.hatched_count or 0} из "
            f"{status.batch.eggs_count}{rate}"
        )
    note = f"\nЗаметка: {status.batch.note}" if status.batch.note else ""
    return (
        f"#{status.batch.id} {status.batch.title}\n"
        f"Птица: {status.profile.title}\n"
        f"Яиц: {status.batch.eggs_count}\n"
        f"Дата закладки: {status.batch.start_date.isoformat()}\n"
        f"День: {day_text}\n"
        f"Этап: {status.stage}\n"
        f"Ожидаемый вывод: {status.hatch_date.isoformat()} ({days_left_text})"
        f"{completed}"
        f"{note}\n\n"
        f"Рекомендации:\n{recommendations}"
    )


def _user_today(
    user_id: int,
    incubation_service: IncubationService,
    now_utc: datetime | None = None,
) -> date:
    settings = incubation_service.get_user_settings(user_id)
    return to_user_local_time(
        now_utc or datetime.now(timezone.utc),
        str(settings.get("timezone", "Europe/Moscow")),
    ).date()


def _day_label(status) -> str:
    return str(status.day) if status.day > 0 else "ещё не началась"


def _edit_help(batch_id: int | None = None) -> str:
    target = str(batch_id) if batch_id is not None else "ID"
    return (
        "Редактирование партии:\n"
        f"/edit {target} яиц 24\n"
        f"/edit {target} дата 23.05.2026\n"
        f"/edit {target} название Новое название\n"
        f"/edit {target} заметка Заметка\n"
        f"/edit {target} птица chicken|goose|quail|duck|muscovy_duck"
    )


def _edit_prompt(field: str) -> str:
    prompts = {
        "eggs": "Введите новое количество яиц числом, например 24.",
        "date": f"Введите новую дату закладки: {DATE_FORMAT_HINT}.",
        "title": "Введите новое название партии.",
        "note": "Введите новую заметку. Чтобы очистить заметку, отправьте -",
    }
    return prompts.get(field, "Введите новое значение.")


def _adjust_number(
    current: int,
    action: str,
    min_value: int,
    max_value: int | None = None,
) -> int:
    if action == "max" and max_value is not None:
        return max_value
    next_value = current + int(action)
    if next_value < min_value:
        next_value = min_value
    if max_value is not None and next_value > max_value:
        next_value = max_value
    return next_value


async def _edit_callback_message(callback: CallbackQuery, text: str, **kwargs) -> None:
    if callback.message:
        try:
            await callback.message.edit_text(text, **kwargs)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            await callback.message.answer(text, **kwargs)


async def _answer_callback_message(callback: CallbackQuery, text: str, **kwargs) -> None:
    if callback.message:
        await callback.message.answer(text, **kwargs)


@router.callback_query()
async def unknown_callback(
    callback: CallbackQuery,
    incubation_service: IncubationService,
    config: AppConfig,
) -> None:
    incubation_service.track_scenario_error(
        user_id=callback.from_user.id if callback.from_user else None,
        scenario="unknown_callback",
        message=str(callback.data or ""),
    )
    await _answer_callback_message(
        callback,
        "Это действие уже недоступно. Откройте нужный раздел заново.",
        reply_markup=main_menu_keyboard(
            incubation_service.get_user_settings(callback.from_user.id),
            web_url=config.web_open_url,
            miniapp_url=config.miniapp_open_url,
        ),
    )
    await callback.answer()
