from datetime import datetime, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.keyboards.poultry_advisor import (
    advisor_back_keyboard,
    advisor_feed_keyboard,
    advisor_health_keyboard,
    advisor_menu_keyboard,
)
from app.services.incubation import IncubationService
from app.services.poultry_advisor import PoultryAdvisorService


router = Router()


@router.message(Command("advisor"))
async def advisor_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🐔 Птицевод-практик\n\nВыберите, с чем помочь по хозяйству.",
        reply_markup=advisor_menu_keyboard(),
    )


@router.callback_query(F.data == "advisor:menu")
async def advisor_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(
        "🐔 Птицевод-практик\n\nВыберите, с чем помочь по хозяйству.",
        reply_markup=advisor_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "advisor:today")
async def advisor_today(
    callback: CallbackQuery,
    state: FSMContext,
    poultry_advisor_service: PoultryAdvisorService,
    incubation_service: IncubationService,
) -> None:
    await state.clear()
    now = datetime.now(datetime_timezone.utc)
    local_now = _local_now(callback.from_user.id, incubation_service, now)
    await callback.message.answer(
        poultry_advisor_service.build_today_plan(
            callback.from_user.id,
            local_now=local_now,
            now_utc=now,
        ),
        reply_markup=advisor_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "advisor:feed")
async def advisor_feed(
    callback: CallbackQuery,
    state: FSMContext,
    poultry_advisor_service: PoultryAdvisorService,
) -> None:
    await state.clear()
    await callback.message.answer(
        poultry_advisor_service.build_feed_advice(callback.from_user.id),
        reply_markup=advisor_feed_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "advisor:mix_timing")
async def advisor_mix_timing(
    callback: CallbackQuery,
    state: FSMContext,
    poultry_advisor_service: PoultryAdvisorService,
    incubation_service: IncubationService,
) -> None:
    await state.clear()
    now = datetime.now(datetime_timezone.utc)
    local_now = _local_now(callback.from_user.id, incubation_service, now)
    await callback.message.answer(
        poultry_advisor_service.build_mix_timing_advice(
            callback.from_user.id,
            now_utc=now,
            local_now=local_now,
        ),
        reply_markup=advisor_feed_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "advisor:eggs_drop")
async def advisor_eggs_drop(
    callback: CallbackQuery,
    state: FSMContext,
    poultry_advisor_service: PoultryAdvisorService,
) -> None:
    await state.clear()
    await callback.message.answer(
        poultry_advisor_service.build_egg_drop_advice(callback.from_user.id),
        reply_markup=advisor_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "advisor:incubation_today")
async def advisor_incubation_today(
    callback: CallbackQuery,
    state: FSMContext,
    poultry_advisor_service: PoultryAdvisorService,
) -> None:
    await state.clear()
    await callback.message.answer(
        poultry_advisor_service.build_incubation_today_advice(callback.from_user.id),
        reply_markup=advisor_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "advisor:health")
async def advisor_health(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(
        "🩺 Проблема с птицей\n\n"
        "Выберите, есть ли признаки риска. Я не ставлю диагнозы и не назначаю лечение.",
        reply_markup=advisor_health_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "advisor:health:red_flags")
async def advisor_health_red_flags(
    callback: CallbackQuery,
    state: FSMContext,
    poultry_advisor_service: PoultryAdvisorService,
) -> None:
    await state.clear()
    await callback.message.answer(
        poultry_advisor_service.build_health_red_flags_advice(),
        reply_markup=advisor_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "advisor:health:no_red_flags")
async def advisor_health_no_red_flags(
    callback: CallbackQuery,
    state: FSMContext,
    poultry_advisor_service: PoultryAdvisorService,
) -> None:
    await state.clear()
    await callback.message.answer(
        poultry_advisor_service.build_health_observation_advice(),
        reply_markup=advisor_back_keyboard(),
    )
    await callback.answer()


def _local_now(user_id: int, incubation_service: IncubationService, now_utc: datetime) -> datetime:
    settings = incubation_service.get_user_settings(user_id)
    try:
        zone = ZoneInfo(str(settings.get("timezone", "Europe/Moscow")))
    except Exception:
        zone = ZoneInfo("Europe/Moscow")
    return now_utc.astimezone(zone)
