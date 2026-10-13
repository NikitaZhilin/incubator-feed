from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.keyboards.admin import (
    MAX_CALLBACK_VERSION_LENGTH,
    RELEASE_CALLBACK_PREFIX,
    parse_release_callback,
    release_confirm_keyboard,
)
from app.keyboards.menu import back_to_menu_keyboard
from app.services.admin import AdminService
from app.services.release_notifications import (
    ReleaseNotificationService,
    build_release_preview,
    count_release_recipients,
)
from app.services.reminders import classify_telegram_error


router = Router()


class AdminBroadcast(StatesGroup):
    confirm = State()


class AdminReleaseNotes(StatesGroup):
    waiting_text = State()


RELEASE_DRAFT_KEY = "release_notes_draft"
MAX_RELEASE_NOTES_INPUT = 3000
# Versions whose broadcast is running right now (guards against double taps).
_release_sends_in_progress: set[str] = set()


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


@router.callback_query(F.data.startswith(RELEASE_CALLBACK_PREFIX))
async def admin_release_action(
    callback: CallbackQuery,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    if not admin_service.is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    action, version = parse_release_callback(callback.data or "")
    current_version = _current_release_version(admin_service)
    if not current_version or version != current_version[:MAX_CALLBACK_VERSION_LENGTH]:
        await callback.answer(
            f"Это уведомление от прошлой версии. Сейчас работает: {current_version or 'не указана'}.",
            show_alert=True,
        )
        return

    if action == "preview":
        await callback.answer()
        await _show_release_preview(callback.message, state, admin_service, edit=True)
    elif action == "edit":
        await state.set_state(AdminReleaseNotes.waiting_text)
        await callback.answer()
        await callback.message.answer(
            f"Пришлите одним сообщением, что изменилось в версии {escape(current_version)}.\n"
            "Каждый пункт с новой строки.\n"
            "Отмена: /cancel"
        )
    elif action == "skip":
        await callback.answer("Рассылка отменена")
        await callback.message.edit_text(
            f"🚫 Уведомление о версии {escape(current_version)} пользователям не отправлялось.",
            reply_markup=None,
        )
    elif action == "send":
        if current_version in _release_sends_in_progress:
            await callback.answer("Рассылка уже идёт", show_alert=True)
            return
        _release_sends_in_progress.add(current_version)
        try:
            await _send_release(callback, state, admin_service, current_version)
        finally:
            _release_sends_in_progress.discard(current_version)
    else:
        await callback.answer("Неизвестное действие", show_alert=True)


@router.message(AdminReleaseNotes.waiting_text)
async def admin_release_notes_input(
    message: Message,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    if not _is_admin_message(message, admin_service):
        await state.clear()
        await message.answer("Команда недоступна.")
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Нужен текст. Пришлите список изменений или /cancel.")
        return
    if len(text) > MAX_RELEASE_NOTES_INPUT:
        await message.answer(
            f"Слишком длинно ({len(text)} символов). Сократите до {MAX_RELEASE_NOTES_INPUT}."
        )
        return
    await state.set_state(None)
    await state.update_data(
        **{RELEASE_DRAFT_KEY: {"version": _current_release_version(admin_service), "notes": text}}
    )
    await _show_release_preview(message, state, admin_service, edit=False)


async def _send_release(
    callback: CallbackQuery,
    state: FSMContext,
    admin_service: AdminService,
    current_version: str,
) -> None:
    await callback.answer("Рассылаю…")
    # Remove the buttons first so a second tap cannot start another run.
    await callback.message.edit_text(
        f"⏳ Рассылаю уведомление о версии {escape(current_version)}…",
        reply_markup=None,
    )
    notes = await _release_notes(state, admin_service)
    result = await ReleaseNotificationService(
        bot=callback.bot,
        users=admin_service.users,
        notifications=admin_service.notifications,
    ).send_release_notice(
        version=current_version,
        notes=notes,
        importance="major",
    )
    await state.update_data(**{RELEASE_DRAFT_KEY: None})
    await callback.message.edit_text(
        f"✅ Уведомление о версии {escape(current_version)} разослано.\n"
        f"Отправлено: {result.sent}, пропущено: {result.skipped}, ошибок: {result.failed}.",
        reply_markup=None,
    )


async def _show_release_preview(
    message: Message,
    state: FSMContext,
    admin_service: AdminService,
    *,
    edit: bool,
) -> None:
    version = _current_release_version(admin_service)
    notes = await _release_notes(state, admin_service)
    recipients = count_release_recipients(admin_service.users)
    text = build_release_preview(version, notes, recipients=recipients)
    keyboard = release_confirm_keyboard(version, recipients)
    if edit:
        await message.edit_text(text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


async def _release_notes(state: FSMContext, admin_service: AdminService) -> str:
    """Admin-edited notes for the current version win over the deploy notes."""
    data = await state.get_data()
    draft = data.get(RELEASE_DRAFT_KEY)
    if isinstance(draft, dict) and draft.get("version") == _current_release_version(admin_service):
        return str(draft.get("notes") or "")
    return admin_service.config.release_notes


def _current_release_version(admin_service: AdminService) -> str:
    return (admin_service.config.release_version or "").strip()


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
