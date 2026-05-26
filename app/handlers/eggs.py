import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.domain import DailyWeather, EggStats, HenLayingExclusion
from app.keyboards.eggs import (
    eggs_back_keyboard,
    eggs_cancel_keyboard,
    eggs_menu_keyboard,
    exclusion_reason_keyboard,
    exclusions_keyboard,
    weather_keyboard,
)
from app.services.eggs import EXCLUSION_REASON_LABELS, EggService
from app.utils.dates import DATE_FORMAT_HINT, parse_user_date


router = Router()


class EggEntryFlow(StatesGroup):
    count = State()


class EggExclusionFlow(StatesGroup):
    count = State()
    expected_until = State()


class EggWeatherFlow(StatesGroup):
    city = State()


@router.callback_query(F.data == "eggs:menu")
async def eggs_menu(callback: CallbackQuery, state: FSMContext, egg_service: EggService) -> None:
    await state.clear()
    await callback.message.answer(
        _format_eggs_menu(_safe_stats(egg_service, callback.from_user.id)),
        reply_markup=eggs_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "eggs:add")
async def eggs_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EggEntryFlow.count)
    await callback.message.answer(
        "Сколько яиц собрано сегодня?\n\n"
        "Введите число. Если хотите внести несколько раз за день, можно добавлять отдельными записями.",
        reply_markup=eggs_cancel_keyboard(),
    )
    await callback.answer()


@router.message(EggEntryFlow.count)
async def eggs_count(message: Message, state: FSMContext, egg_service: EggService) -> None:
    try:
        count = int((message.text or "").strip())
        entry = egg_service.record_today(message.from_user.id, count)
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=eggs_cancel_keyboard())
        return
    await state.clear()
    await message.answer(
        "Запись добавлена.\n\n"
        f"Дата: {entry.entry_date.isoformat()}\n"
        f"Яиц: {entry.eggs_count}\n"
        f"Несушек в расчете: {entry.active_hens_count} из {entry.total_hens_count}",
        reply_markup=eggs_menu_keyboard(),
    )


@router.callback_query(F.data == "eggs:stats")
async def eggs_stats(callback: CallbackQuery, egg_service: EggService) -> None:
    await callback.message.answer(
        _format_stats(_safe_stats(egg_service, callback.from_user.id)),
        reply_markup=eggs_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "eggs:history")
async def eggs_history(callback: CallbackQuery, egg_service: EggService) -> None:
    rows = egg_service.history(callback.from_user.id, days=14)
    lines = ["📅 История яиц за 14 дней", ""]
    if not any(total for _, total in rows):
        lines.append("Записей пока нет. Добавьте первый сбор яиц.")
    else:
        for day, total in rows:
            lines.append(f"- {day.isoformat()}: {total} шт.")
    await callback.message.answer("\n".join(lines), reply_markup=eggs_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "eggs:exclusions")
async def eggs_exclusions(callback: CallbackQuery, egg_service: EggService) -> None:
    exclusions = egg_service.list_open_exclusions(callback.from_user.id)
    await callback.message.answer(_format_exclusions(exclusions), reply_markup=exclusions_keyboard(exclusions))
    await callback.answer()


@router.callback_query(F.data == "eggs:exclude")
async def eggs_exclude_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(
        "Почему курица временно не несется?",
        reply_markup=exclusion_reason_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("eggs:exclude_reason:"))
async def eggs_exclude_reason(callback: CallbackQuery, state: FSMContext) -> None:
    reason = str(callback.data).split(":", 2)[2]
    if reason not in EXCLUSION_REASON_LABELS:
        await callback.answer("Причина не найдена", show_alert=True)
        return
    await state.update_data(reason=reason)
    await state.set_state(EggExclusionFlow.count)
    await callback.message.answer(
        "Сколько несушек временно не несется?",
        reply_markup=eggs_cancel_keyboard(),
    )
    await callback.answer()


@router.message(EggExclusionFlow.count)
async def eggs_exclude_count(message: Message, state: FSMContext) -> None:
    try:
        count = int((message.text or "").strip())
        if count <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите количество кур целым числом больше нуля.", reply_markup=eggs_cancel_keyboard())
        return
    await state.update_data(hens_count=count)
    await state.set_state(EggExclusionFlow.expected_until)
    await message.answer(
        "До какой даты не учитывать их в яйценоскости?\n\n"
        f"Формат: {DATE_FORMAT_HINT}. Если дата пока неизвестна, отправьте 0.",
        reply_markup=eggs_cancel_keyboard(),
    )


@router.message(EggExclusionFlow.expected_until)
async def eggs_exclude_until(message: Message, state: FSMContext, egg_service: EggService) -> None:
    raw = (message.text or "").strip()
    try:
        expected_until = None if raw in {"0", "-", "нет", "не знаю"} else parse_user_date(raw)
        data = await state.get_data()
        exclusion = egg_service.create_exclusion(
            user_id=message.from_user.id,
            hens_count=int(data["hens_count"]),
            reason=str(data["reason"]),
            expected_until=expected_until,
        )
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=eggs_cancel_keyboard())
        return
    await state.clear()
    await message.answer(
        "Исключение добавлено.\n\n" + _format_exclusion(exclusion),
        reply_markup=exclusions_keyboard(egg_service.list_open_exclusions(message.from_user.id)),
    )


@router.callback_query(F.data.startswith("eggs:exclude_finish:"))
async def eggs_exclude_finish(callback: CallbackQuery, egg_service: EggService) -> None:
    exclusion_id = int(str(callback.data).rsplit(":", 1)[1])
    finished = egg_service.finish_exclusion(user_id=callback.from_user.id, exclusion_id=exclusion_id)
    exclusions = egg_service.list_open_exclusions(callback.from_user.id)
    text = "Курица снова учитывается в яйценоскости." if finished else "Исключение не найдено."
    await callback.message.answer(
        text + "\n\n" + _format_exclusions(exclusions),
        reply_markup=exclusions_keyboard(exclusions),
    )
    await callback.answer()


@router.callback_query(F.data == "eggs:weather")
async def eggs_weather(callback: CallbackQuery, egg_service: EggService) -> None:
    weather = egg_service.get_daily_weather(callback.from_user.id)
    settings = egg_service.get_weather_settings(callback.from_user.id)
    await callback.message.answer(
        "🌦 Город и погода\n\n"
        f"Город: {settings.city}\n"
        f"{_format_weather(weather)}"
        "\n\n"
        "Погодная поправка в расчетах ориентировочная: бот смотрит уличную погоду, "
        "а яйценоскость сильнее зависит от фактических условий в курятнике.\n\n"
        "Для загрузки свежих данных нажмите Обновить погоду.",
        reply_markup=weather_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "eggs:weather_refresh")
async def eggs_weather_refresh(callback: CallbackQuery, egg_service: EggService) -> None:
    try:
        weather = await asyncio.to_thread(
            egg_service.refresh_weather,
            callback.from_user.id,
            force=True,
        )
    except Exception as exc:
        await callback.message.answer(
            f"Погоду сейчас не удалось обновить: {_format_weather_error(exc)}",
            reply_markup=weather_keyboard(),
        )
        await callback.answer()
        return
    await callback.message.answer(
        "Погода обновлена.\n\n" + _format_weather(weather),
        reply_markup=weather_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "eggs:weather_city")
async def eggs_weather_city(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EggWeatherFlow.city)
    await callback.message.answer(
        "Введите город для погодной привязки, например Курск.",
        reply_markup=eggs_cancel_keyboard(),
    )
    await callback.answer()


@router.message(EggWeatherFlow.city)
async def eggs_weather_city_save(message: Message, state: FSMContext, egg_service: EggService) -> None:
    try:
        settings = await asyncio.to_thread(
            egg_service.update_weather_city,
            user_id=message.from_user.id,
            city=message.text or "",
        )
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=eggs_cancel_keyboard())
        return
    except Exception as exc:
        await state.clear()
        await message.answer(
            f"Город сейчас не удалось проверить: {_format_weather_error(exc)}",
            reply_markup=weather_keyboard(),
        )
        return
    try:
        weather = await asyncio.to_thread(
            egg_service.refresh_weather,
            message.from_user.id,
            force=True,
        )
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=eggs_cancel_keyboard())
        return
    except Exception as exc:
        await state.clear()
        await message.answer(
            f"Город сохранен: {settings.city}\n\n"
            f"Погоду сейчас не удалось загрузить: {_format_weather_error(exc)}",
            reply_markup=weather_keyboard(),
        )
        return
    await state.clear()
    await message.answer(
        f"Город сохранен: {settings.city}\n\n" + _format_weather(weather),
        reply_markup=weather_keyboard(),
    )


def _format_eggs_menu(stats: EggStats) -> str:
    return (
        "🥚 Яйца\n\n"
        "Здесь учитываем ежедневный сбор яиц и считаем прогноз только по взрослым несушкам.\n\n"
        f"Сегодня: {stats.today_eggs} шт.\n"
        f"Несутся сейчас: {stats.active_hens_count} из {stats.total_hens_count}\n"
        f"Прогноз на 7 дней: примерно {stats.next_week_forecast} шт.\n"
        f"{_format_weather_forecast_line(stats)}\n\n"
        f"{_format_weather_brief(stats.weather)}"
    )


def _format_stats(stats: EggStats) -> str:
    per_hen = (
        "нет данных"
        if stats.eggs_per_active_hen is None
        else f"{stats.eggs_per_active_hen:.2f} шт./курицу в день"
    )
    lines = [
        "📊 Расчеты по яйцам",
        "",
        f"Дата: {stats.today.isoformat()}",
        f"Сегодня собрано: {stats.today_eggs} шт.",
        "",
        f"Взрослых несушек: {stats.total_hens_count}",
        f"Временно не несутся: {stats.excluded_hens_count}",
        f"Учитываются в яйценоскости: {stats.active_hens_count}",
        "",
        f"За 7 дней: {stats.week_eggs} шт., в среднем {stats.week_average:.1f} шт./день",
        f"За 30 дней: {stats.month_eggs} шт., в среднем {stats.month_average:.1f} шт./день",
        f"На одну активную несушку: {per_hen}",
        "",
        f"Прогноз на следующую неделю: примерно {stats.next_week_forecast} шт.",
        _format_weather_forecast_line(stats),
        "",
        f"Город для погодной привязки: {stats.weather_city}",
        _format_weather(stats.weather),
        f"Погодная поправка: {stats.weather_impact_percent:+d}%. {stats.weather_note}",
    ]
    if stats.active_exclusions:
        lines.extend(["", "Не учитываются сейчас:"])
        lines.extend(f"- {_format_exclusion(item)}" for item in stats.active_exclusions)
    if stats.total_hens_count == 0:
        lines.extend(
            [
                "",
                "Важно: несушки не найдены. Создайте поголовье с ролью 'куры/несушки', "
                "иначе расчет будет без привязки к курицам.",
            ]
        )
    return "\n".join(lines)


def _format_exclusions(exclusions: list[HenLayingExclusion]) -> str:
    lines = ["🐔 Куры, которые временно не несутся", ""]
    if not exclusions:
        lines.append("Активных исключений нет.")
    else:
        lines.extend(f"- {_format_exclusion(item)}" for item in exclusions)
    return "\n".join(lines)


def _format_exclusion(exclusion: HenLayingExclusion) -> str:
    reason = EXCLUSION_REASON_LABELS.get(exclusion.reason, exclusion.reason)
    until = f" до {exclusion.expected_until.isoformat()}" if exclusion.expected_until else " без даты окончания"
    return f"#{exclusion.id}: {exclusion.hens_count} кур., {reason}{until}"


def _safe_stats(egg_service: EggService, user_id: int) -> EggStats:
    return egg_service.stats(user_id, refresh_weather=False)


def _format_weather_forecast_line(stats: EggStats) -> str:
    if stats.weather_adjusted_week_forecast is None:
        return "Погодная поправка: нет данных за сегодня."
    if stats.weather_impact_percent == 0:
        return f"С погодой: без поправки, примерно {stats.weather_adjusted_week_forecast} шт."
    return (
        f"С погодой: примерно {stats.weather_adjusted_week_forecast} шт. "
        f"({stats.weather_impact_percent:+d}%)."
    )


def _format_weather(weather: DailyWeather | None) -> str:
    if weather is None:
        return "Погода за сегодня еще не загружена. Нажмите Обновить погоду."
    temp = "нет данных"
    if weather.temperature_avg_c is not None:
        temp = f"{weather.temperature_avg_c:.1f} °C"
        if weather.temperature_min_c is not None and weather.temperature_max_c is not None:
            temp += f" ({weather.temperature_min_c:.0f}...{weather.temperature_max_c:.0f} °C)"
    precipitation = (
        "нет данных"
        if weather.precipitation_mm is None
        else f"{weather.precipitation_mm:.1f} мм"
    )
    condition = weather.condition or "нет данных"
    return (
        f"Погода на {weather.weather_date.isoformat()}:\n"
        f"- температура: {temp}\n"
        f"- осадки: {precipitation}\n"
        f"- состояние: {condition}\n"
        f"- источник: {weather.provider}"
    )


def _format_weather_brief(weather: DailyWeather | None) -> str:
    if weather is None:
        return "Погода: не загружена. Откройте Город и погода -> Обновить погоду."
    temp = "нет данных"
    if weather.temperature_avg_c is not None:
        temp = f"{weather.temperature_avg_c:.1f} °C"
    condition = f", {weather.condition}" if weather.condition else ""
    return f"Погода: {temp}{condition}, {weather.city}."


def _format_weather_error(exc: Exception) -> str:
    text = str(exc).strip()
    lowered = text.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "погодные сервисы не ответили за отведенное время. Попробуйте обновить позже."
    if "погодные сервисы не ответили" in lowered:
        return text
    if "urlopen error" in lowered:
        return "нет соединения с погодным сервисом. Попробуйте позже."
    return text or "неизвестная ошибка погодного сервиса."
