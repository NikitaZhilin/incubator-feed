from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.keyboards.menu import main_menu_keyboard
from app.services.incubation import IncubationService


router = Router()


@router.message(Command("start"))
async def start(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    await state.clear()
    incubation_service.track("bot_started", user_id=message.from_user.id if message.from_user else None)
    await message.answer(
        "Я помогу вести инкубацию яиц и контролировать запас кормов.\n\n"
        "Выберите раздел в меню ниже.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Добавление партии:\n"
        "/new - выбрать птицу, количество яиц, дату закладки и название.\n\n"
        "Редактирование:\n"
        "/edit ID яиц 24\n"
        "/edit ID дата 23.05.2026\n"
        "/edit ID название Моя партия\n"
        "/edit ID заметка Любая заметка\n"
        "/edit ID птица chicken|goose|quail|duck|muscovy_duck\n\n"
        "Разделы инкубации:\n"
        "/calendar - что делать по дням инкубации\n"
        "/care - уход после вывода\n"
        "/feed - добавить корм и рассчитать остаток\n\n"
        "Настройки:\n"
        "/settings - уведомления, хозяйство, единицы\n"
        "/timezone Europe/Moscow - часовой пояс\n"
        "/farm Мое хозяйство - название хозяйства\n"
        "/disclaimer - справочный дисклеймер\n\n"
        "Закрытие партии:\n"
        "Нажмите кнопку Завершить вывод под партией и укажите количество выведенных птенцов.\n\n"
        "Напоминания:\n"
        "/remind 09:00 - включить ежедневный план\n"
        "/remind off - выключить\n\n"
        "Отмена текущего действия: /cancel."
    )


@router.message(Command("menu"))
async def menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Главное меню:", reply_markup=main_menu_keyboard())


@router.message(Command("cancel"))
async def cancel_any(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено. Главное меню:", reply_markup=main_menu_keyboard())
