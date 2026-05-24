from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.keyboards.menu import back_to_menu_keyboard
from app.services.admin import AdminService
from app.services.reminders import classify_telegram_error


router = Router()


class AdminBroadcast(StatesGroup):
    confirm = State()


@router.message(Command("admin"))
async def admin_command(message: Message, admin_service: AdminService) -> None:
    if not _is_admin_message(message, admin_service):
        await message.answer("Команда недоступна.")
        return
    await message.answer(_format_admin_stats(admin_service), reply_markup=back_to_menu_keyboard())


@router.message(Command("admin_export"))
async def admin_export(message: Message, admin_service: AdminService) -> None:
    if not _is_admin_message(message, admin_service):
        await message.answer("Команда недоступна.")
        return
    payload = admin_service.export_stats_csv()
    await message.answer_document(
        BufferedInputFile(payload, filename="bot_stats.csv"),
        caption="Выгрузка простой статистики.",
    )


@router.message(Command("admin_broadcast"))
async def admin_broadcast(message: Message, state: FSMContext, admin_service: AdminService) -> None:
    if not _is_admin_message(message, admin_service):
        await message.answer("Команда недоступна.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1 or not parts[1].strip():
        await message.answer("Текст рассылки: /admin_broadcast Сообщение пользователям")
        return
    await state.set_state(AdminBroadcast.confirm)
    await state.update_data(text=parts[1].strip())
    await message.answer(
        "Подтвердите сервисную рассылку активным пользователям.\n"
        "Отправьте: ДА\n"
        "Отмена: /cancel"
    )


@router.message(AdminBroadcast.confirm)
async def admin_broadcast_confirm(
    message: Message,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    if not _is_admin_message(message, admin_service):
        await state.clear()
        await message.answer("Команда недоступна.")
        return
    if (message.text or "").strip().upper() != "ДА":
        await state.clear()
        await message.answer("Рассылка отменена.")
        return
    data = await state.get_data()
    text = str(data["text"])
    await state.clear()
    user_ids = admin_service.users.list_active_users()
    sent = 0
    failed = 0
    for user_id in user_ids:
        event_key = f"service:broadcast:{message.message_id}:user_{user_id}"
        admin_service.notifications.record_attempt(
            user_id=user_id,
            type="service",
            event_key=event_key,
            scheduled_for=message.date,
        )
        try:
            await message.bot.send_message(user_id, text)
            admin_service.notifications.mark_sent(event_key, message.date)
            sent += 1
        except Exception as exc:
            error_code = classify_telegram_error(exc)
            admin_service.notifications.mark_failed(
                event_key,
                error_code=error_code,
                error_message=str(exc),
            )
            if error_code in {"blocked", "deactivated"}:
                admin_service.users.mark_inactive(user_id, error_code)
            failed += 1
    await message.answer(f"Рассылка завершена. Отправлено: {sent}, ошибок: {failed}.")


@router.callback_query(F.data == "admin:refresh")
async def admin_refresh(callback: CallbackQuery, admin_service: AdminService) -> None:
    if not admin_service.is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.message.answer(_format_admin_stats(admin_service), reply_markup=back_to_menu_keyboard())
    await callback.answer()


def _is_admin_message(message: Message, admin_service: AdminService) -> bool:
    return bool(message.from_user and admin_service.is_admin(message.from_user.id))


def _format_admin_stats(admin_service: AdminService) -> str:
    stats = admin_service.get_stats()
    recent_users = "\n".join(
        f"- {row['user_id']} @{row['username'] or '-'} {row['created_at']}"
        for row in stats.recent_users
    ) or "- нет"
    recent_errors = "\n".join(
        f"- {row['created_at']} {row['source']}: {row['message']}"
        for row in stats.recent_errors
    ) or "- нет"
    return (
        "Админ-панель\n\n"
        f"Пользователей: {stats.total_users}\n"
        f"Активных пользователей: {stats.active_users}\n"
        f"Активных партий: {stats.active_batches}\n"
        f"Активных кормов: {stats.active_feeds}\n"
        f"Ошибок уведомлений: {stats.notification_failures}\n"
        f"Свободно на диске: {stats.free_disk_mb} МБ\n\n"
        f"Последние регистрации:\n{recent_users}\n\n"
        f"Последние критические ошибки:\n{recent_errors}\n\n"
        "Команды: /admin_export, /admin_broadcast текст"
    )
