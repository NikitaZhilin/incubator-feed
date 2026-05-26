from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import AppConfig
from app.keyboards.menu import (
    about_bot_keyboard,
    settings_back_keyboard,
    settings_keyboard,
    settings_sections_keyboard,
)
from app.services.release_notifications import DEFAULT_TESTING_DISCLAIMER
from app.services.incubation import IncubationService
from app.version import APP_VERSION


router = Router()


class SettingsFlow(StatesGroup):
    farm_name = State()
    timezone = State()
    notification_time = State()


@router.message(Command("settings"))
async def settings_command(message: Message, incubation_service: IncubationService) -> None:
    await message.answer(
        _format_settings(incubation_service.get_user_settings(message.from_user.id)),
        reply_markup=settings_keyboard(),
    )


@router.callback_query(F.data == "settings:menu")
async def settings_menu(
    callback: CallbackQuery,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    await state.clear()
    await callback.message.answer(
        _format_settings(incubation_service.get_user_settings(callback.from_user.id)),
        reply_markup=settings_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:sections")
async def settings_sections(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    settings = incubation_service.get_user_settings(callback.from_user.id)
    await callback.message.answer(
        _format_sections(settings),
        reply_markup=settings_sections_keyboard(settings),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:toggle:"))
async def settings_toggle(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    field = str(callback.data).split(":", 2)[2]
    if field not in {
        "notify_incubation",
        "notify_feed",
        "notify_eggs",
        "notify_post_hatch_care",
        "notify_service",
    }:
        await callback.answer("Настройка не найдена", show_alert=True)
        return
    current = incubation_service.get_user_settings(callback.from_user.id)
    updated = incubation_service.update_user_settings(
        callback.from_user.id,
        **{field: not bool(current[field])},
    )
    await callback.message.answer(_format_sections(updated), reply_markup=settings_sections_keyboard(updated))
    await callback.answer("Сохранено")


@router.callback_query(F.data.startswith("settings:edit:"))
async def settings_edit(callback: CallbackQuery, state: FSMContext, incubation_service: IncubationService) -> None:
    field = str(callback.data).split(":", 2)[2]
    settings = incubation_service.get_user_settings(callback.from_user.id)
    if field == "farm_name":
        await state.set_state(SettingsFlow.farm_name)
        await callback.message.answer(
            "Введите название хозяйства. Чтобы очистить название, отправьте -.",
            reply_markup=settings_back_keyboard(),
        )
    elif field == "timezone":
        await state.set_state(SettingsFlow.timezone)
        await callback.message.answer(
            "Введите часовой пояс, например Europe/Moscow.\n"
            f"Сейчас: {settings.get('timezone', 'Europe/Moscow')}",
            reply_markup=settings_back_keyboard(),
        )
    elif field == "notification_time":
        await state.set_state(SettingsFlow.notification_time)
        await callback.message.answer(
            "Введите время уведомлений в формате ЧЧ:ММ, например 09:00.\n"
            f"Сейчас: {settings.get('notification_time', '09:00')}",
            reply_markup=settings_back_keyboard(),
        )
    else:
        await callback.answer("Настройка не найдена", show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data == "settings:about")
async def settings_about(callback: CallbackQuery, config: AppConfig) -> None:
    await callback.message.answer(
        format_about_bot(config),
        reply_markup=about_bot_keyboard(
            github_url=config.github_url,
            changelog_url=config.changelog_url,
        ),
    )
    await callback.answer()


@router.message(SettingsFlow.farm_name)
async def settings_farm_name(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer("Введите название хозяйства текстом или отправьте - для очистки.")
        return
    farm_name = "" if value == "-" else value[:255]
    updated = incubation_service.update_user_settings(message.from_user.id, farm_name=farm_name)
    await state.clear()
    await message.answer(_format_settings(updated), reply_markup=settings_keyboard())


@router.message(SettingsFlow.timezone)
async def settings_timezone(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    timezone = (message.text or "").strip()
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        await message.answer("Не знаю такой часовой пояс. Пример: Europe/Moscow")
        return
    updated = incubation_service.update_user_settings(message.from_user.id, timezone=timezone)
    await state.clear()
    await message.answer(_format_settings(updated), reply_markup=settings_keyboard())


@router.message(SettingsFlow.notification_time)
async def settings_notification_time(
    message: Message,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    try:
        notification_time = _parse_notification_time(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    updated = incubation_service.update_user_settings(
        message.from_user.id,
        notification_time=notification_time,
    )
    await state.clear()
    await message.answer(_format_settings(updated), reply_markup=settings_keyboard())


@router.message(Command("timezone"))
async def timezone_command(message: Message, incubation_service: IncubationService) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1:
        settings = incubation_service.get_user_settings(message.from_user.id)
        await message.answer(
            f"Текущий часовой пояс: {settings.get('timezone', 'Europe/Moscow')}\n"
            "Изменить: /timezone Europe/Moscow"
        )
        return
    timezone = parts[1].strip()
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        await message.answer("Не знаю такой часовой пояс. Пример: /timezone Europe/Moscow")
        return
    incubation_service.update_user_settings(message.from_user.id, timezone=timezone)
    await message.answer(f"Часовой пояс сохранен: {timezone}")


@router.message(Command("farm"))
async def farm_command(message: Message, incubation_service: IncubationService) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1 or not parts[1].strip():
        await message.answer("Название хозяйства можно задать так: /farm Мое хозяйство")
        return
    farm_name = parts[1].strip()[:255]
    incubation_service.update_user_settings(message.from_user.id, farm_name=farm_name)
    await message.answer(f"Название хозяйства сохранено: {farm_name}")


@router.message(Command("units"))
async def units_command(message: Message, incubation_service: IncubationService) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1 or parts[1].strip().lower() not in {"metric", "kg"}:
        await message.answer("Сейчас используются килограммы и граммы. Дополнительно менять ничего не нужно.")
        return
    incubation_service.update_user_settings(message.from_user.id, units="metric")
    await message.answer("Единицы измерения сохранены: кг и граммы.")


@router.message(Command("disclaimer"))
async def disclaimer_command(message: Message) -> None:
    from app.services.guides import disclaimer_text

    await message.answer(disclaimer_text())


def _format_settings(settings: dict) -> str:
    return (
        "⚙️ Настройки\n\n"
        f"Хозяйство: {settings.get('farm_name') or 'не указано'}\n"
        f"Часовой пояс: {settings.get('timezone', 'Europe/Moscow')}\n"
        f"Уведомления: {settings.get('notification_time', '09:00')}\n"
        "Единицы: кг и граммы\n\n"
        "Разделы и уведомления настраиваются отдельной кнопкой ниже."
    )


def _format_sections(settings: dict) -> str:
    def status(value: bool) -> str:
        return "включено" if value else "выключено"

    return (
        "🧩 Разделы и уведомления\n\n"
        "Если выключить раздел, его кнопка пропадает из главного меню и уведомления по нему не приходят.\n"
        "Системные сообщения — это важные уведомления о работе бота и крупных обновлениях.\n\n"
        f"Инкубация: {status(bool(settings.get('notify_incubation', True)))}\n"
        f"Корма: {status(bool(settings.get('notify_feed', True)))}\n"
        f"Яйца: {status(bool(settings.get('notify_eggs', True)))}\n"
        f"Уход после вывода: {status(bool(settings.get('notify_post_hatch_care', True)))}\n"
        f"Системные сообщения: {status(bool(settings.get('notify_service', True)))}"
    )


def _parse_notification_time(value: str) -> str:
    parts = value.strip().split(":", 1)
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError("Введите время в формате ЧЧ:ММ, например 09:00.")
    hour = int(parts[0])
    minute = int(parts[1])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Время должно быть в диапазоне от 00:00 до 23:59.")
    return f"{hour:02d}:{minute:02d}"


def format_about_bot(config: AppConfig) -> str:
    version = config.release_version or APP_VERSION
    notes = _release_note_items(config.release_notes)
    lines = [
        "ℹ️ О боте",
        "",
        f"Версия: {version}",
        f"Канал: {config.release_channel}",
        "Статус: тестовый режим",
        "",
        "Состояние:",
        f"Последний запуск: {_format_runtime_time(config.runtime_started_at, config.timezone)}",
    ]
    if config.release_deployed_at:
        lines.append(f"Последний деплой: {_format_runtime_time(config.release_deployed_at, config.timezone)}")
    if config.release_commit:
        lines.append(f"Коммит: {config.release_commit[:12]}")
    lines.extend(
        [
            "",
            "Проект:",
            config.github_url,
            "",
            "История изменений:",
            config.changelog_url,
        ]
    )
    if notes:
        lines.extend(["", "Что нового:"])
        lines.extend(f"- {item}" for item in notes)
    lines.extend(["", DEFAULT_TESTING_DISCLAIMER])
    return "\n".join(lines)


def _format_runtime_time(value: datetime | str, timezone_name: str) -> str:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("Europe/Moscow")

    if isinstance(value, datetime):
        moment = value
    else:
        raw = value.strip()
        if not raw:
            return "неизвестно"
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(zone).strftime("%d.%m.%Y %H:%M")


def _release_note_items(notes: str) -> list[str]:
    items: list[str] = []
    for raw_line in notes.replace(";", "\n").splitlines():
        item = raw_line.strip().lstrip("-•").strip()
        if item:
            items.append(item)
    return items
