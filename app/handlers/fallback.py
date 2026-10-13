"""Catch-all for buttons nobody handles.

Dialog state lives in memory, so after a deploy or restart the buttons of an
unfinished dialog (choose a date, a count, a purchase type...) have no handler.
Without this router Telegram keeps the button spinning and nothing happens.
"""

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.config import AppConfig
from app.keyboards.menu import main_menu_keyboard
from app.services.incubation import IncubationService


router = Router()

STALE_BUTTON_TEXT = "Эта кнопка устарела: бот перезапускался или действие уже завершено."


@router.callback_query()
async def stale_button(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig | None = None,
    incubation_service: IncubationService | None = None,
) -> None:
    await state.clear()
    await callback.answer(STALE_BUTTON_TEXT, show_alert=True)
    if callback.message is None:
        return
    settings = (
        incubation_service.get_user_settings(callback.from_user.id) if incubation_service else None
    )
    await callback.message.answer(
        "Главное меню:",
        reply_markup=main_menu_keyboard(
            settings,
            web_url=config.web_open_url if config else "",
            miniapp_url=config.miniapp_open_url if config else "",
        ),
    )
