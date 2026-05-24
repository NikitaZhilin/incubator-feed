from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.keyboards.menu import settings_keyboard
from app.services.incubation import IncubationService


router = Router()


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


@router.callback_query(F.data.startswith("settings:toggle:"))
async def settings_toggle(callback: CallbackQuery, incubation_service: IncubationService) -> None:
    field = str(callback.data).split(":", 2)[2]
    current = incubation_service.get_user_settings(callback.from_user.id)
    updated = incubation_service.update_user_settings(
        callback.from_user.id,
        **{field: not bool(current[field])},
    )
    await callback.message.answer(_format_settings(updated), reply_markup=settings_keyboard())
    await callback.answer("Сохранено")


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
        await message.answer("Для MVP доступны метрические единицы: /units metric")
        return
    incubation_service.update_user_settings(message.from_user.id, units="metric")
    await message.answer("Единицы измерения сохранены: кг и граммы.")


@router.message(Command("disclaimer"))
async def disclaimer_command(message: Message) -> None:
    from app.services.guides import disclaimer_text

    await message.answer(disclaimer_text())


def _format_settings(settings: dict) -> str:
    def yes(value: bool) -> str:
        return "включены" if value else "выключены"

    return (
        "Настройки\n\n"
        f"Хозяйство: {settings.get('farm_name') or 'не указано'}\n"
        f"Часовой пояс: {settings.get('timezone', 'Europe/Moscow')}\n"
        f"Время уведомлений: {settings.get('notification_time', '09:00')}\n"
        f"Единицы: {settings.get('units', 'metric')}\n\n"
        f"Инкубация: {yes(bool(settings.get('notify_incubation', True)))}\n"
        f"Корма: {yes(bool(settings.get('notify_feed', True)))}\n"
        f"Уход после вывода: {yes(bool(settings.get('notify_post_hatch_care', True)))}\n"
        f"Сервисные: {yes(bool(settings.get('notify_service', True)))}\n\n"
        "Команды: /remind 09:00, /timezone Europe/Moscow, /farm Название, /units metric."
    )
