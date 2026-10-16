"""«✅ Покормил»: mark that the birds were fed with the usual mix."""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.keyboards.menu import feeding_done_keyboard
from app.services.feeding import FeedingService


router = Router()


def _format_kg(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + " кг"


def format_feeding_done(service: FeedingService, user_id: int, result) -> str:
    event = result.event
    at = service.format_time(event)
    if result.duplicate:
        return f"Уже отмечено в {at}. Повторное нажатие не считается."
    lines = [f"✅ Отмечено: покормили в {at}."]
    if event.daily_norm_kg > 0:
        lines.append(
            f"По норме стадо ({event.bird_count} птиц) съедает около "
            f"{_format_kg(event.daily_norm_kg)} смеси в день."
        )
    else:
        lines.append("Добавьте поголовье в «Корма → Поголовье и стада», чтобы бот считал расход по норме.")
    if result.feedings_today > 1:
        lines.append(f"Сегодня это {result.feedings_today}-е кормление.")
    week = service.week(user_id, today=event.fed_date)
    lines.append(
        f"За 7 дней: кормили {week.fed_days} из {week.days} дн., "
        f"ушло около {_format_kg(week.estimated_kg)} по норме."
    )
    lines.append("Склад не меняется: это отметка и расчёт по норме.")
    return "\n".join(lines)


@router.callback_query(F.data == "feeding:done")
async def feeding_done(callback: CallbackQuery, feeding_service: FeedingService) -> None:
    result = feeding_service.record(callback.from_user.id)
    await callback.answer("Уже отмечено" if result.duplicate else "Отмечено ✅")
    await callback.message.answer(
        format_feeding_done(feeding_service, callback.from_user.id, result),
        reply_markup=feeding_done_keyboard(result.event.id),
    )


@router.callback_query(F.data.startswith("feeding:undo:"))
async def feeding_undo(callback: CallbackQuery, feeding_service: FeedingService) -> None:
    raw_id = str(callback.data).rsplit(":", 1)[1]
    event = feeding_service.feeding.get(int(raw_id), callback.from_user.id) if raw_id.isdigit() else None
    if event is None or not feeding_service.undo(callback.from_user.id, event.id):
        await callback.answer("Эта отметка уже отменена.", show_alert=True)
        return
    await callback.answer("Отметка отменена")
    await callback.message.answer(f"Отметка о кормлении в {feeding_service.format_time(event)} отменена.")
