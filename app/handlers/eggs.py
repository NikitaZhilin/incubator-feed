import asyncio
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.domain import DailyWeather, EggStats, HenLayingExclusion
from app.keyboards.eggs import (
    eggs_back_keyboard,
    eggs_cancel_keyboard,
    egg_entry_date_keyboard,
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
    await _answer_eggs_menu(callback.message, callback.from_user.id, egg_service)
    await callback.answer()


@router.callback_query(F.data == "eggs:add")
async def eggs_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(
        "За какой день добавить сбор яиц?",
        reply_markup=egg_entry_date_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("eggs:add_date:"))
async def eggs_add_date(callback: CallbackQuery, state: FSMContext) -> None:
    choice = str(callback.data).rsplit(":", 1)[1]
    try:
        entry_date = _egg_entry_date_from_choice(choice)
    except ValueError:
        await callback.answer("Дата не найдена.", show_alert=True)
        return
    await state.update_data(entry_date=entry_date.isoformat())
    await state.set_state(EggEntryFlow.count)
    await callback.message.answer(
        f"Сколько яиц собрано {_egg_entry_date_label(choice)} ({entry_date.isoformat()})?\n\n"
        "Введите число. Если хотите внести несколько раз за день, можно добавлять отдельными записями.",
        reply_markup=eggs_cancel_keyboard(),
    )
    await callback.answer()


@router.message(EggEntryFlow.count)
async def eggs_count(message: Message, state: FSMContext, egg_service: EggService) -> None:
    try:
        count = int((message.text or "").strip())
        data = await state.get_data()
        entry_date = date.fromisoformat(str(data.get("entry_date") or date.today().isoformat()))
        entry = egg_service.record_today(message.from_user.id, count, today=entry_date)
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
    needs_refresh = egg_service.weather_needs_refresh(callback.from_user.id)
    sent_message = await callback.message.answer(
        _format_weather_screen(settings.city, weather, updating=needs_refresh),
        reply_markup=weather_keyboard(),
    )
    if needs_refresh and sent_message is not None:
        asyncio.create_task(
            _refresh_and_edit_weather_screen(sent_message, callback.from_user.id, egg_service)
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
    return _format_eggs_menu_text(stats)


async def _answer_eggs_menu(message: Message, user_id: int, egg_service: EggService) -> None:
    stats = _safe_stats(egg_service, user_id)
    needs_refresh = egg_service.weather_needs_refresh(user_id)
    sent_message = await message.answer(
        _format_eggs_menu_text(stats, weather_updating=needs_refresh),
        reply_markup=eggs_menu_keyboard(),
    )
    if needs_refresh and sent_message is not None:
        asyncio.create_task(_refresh_and_edit_eggs_menu(sent_message, user_id, egg_service))


async def _refresh_and_edit_eggs_menu(message: Message, user_id: int, egg_service: EggService) -> None:
    try:
        await asyncio.to_thread(egg_service.refresh_weather, user_id, force=True)
        stats = _safe_stats(egg_service, user_id)
        text = _format_eggs_menu_text(stats)
    except Exception as exc:
        stats = _safe_stats(egg_service, user_id)
        text = (
            _format_eggs_menu_text(stats)
            + "\n\n"
            + f"Погоду сейчас не удалось обновить: {_format_weather_error(exc)}"
        )
    try:
        await message.edit_text(text, reply_markup=eggs_menu_keyboard())
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def _refresh_and_edit_weather_screen(message: Message, user_id: int, egg_service: EggService) -> None:
    try:
        weather = await asyncio.to_thread(egg_service.refresh_weather, user_id, force=True)
        settings = egg_service.get_weather_settings(user_id)
        text = _format_weather_screen(settings.city, weather)
    except Exception as exc:
        settings = egg_service.get_weather_settings(user_id)
        weather = egg_service.get_daily_weather(user_id)
        text = (
            _format_weather_screen(settings.city, weather)
            + "\n\n"
            + f"Погоду сейчас не удалось обновить: {_format_weather_error(exc)}"
        )
    try:
        await message.edit_text(text, reply_markup=weather_keyboard())
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


def _format_eggs_menu_text(stats: EggStats, *, weather_updating: bool = False) -> str:
    return (
        "🥚 Яйца\n\n"
        "Здесь учитываем ежедневный сбор яиц и считаем прогноз только по взрослым несушкам.\n\n"
        f"Сегодня: {stats.today_eggs} шт.\n"
        f"Несутся сейчас: {stats.active_hens_count} из {stats.total_hens_count}\n"
        f"Прогноз на 7 дней: примерно {stats.next_week_forecast} шт.\n"
        f"{_format_weather_forecast_line(stats)}\n\n"
        f"{_format_weather_brief(stats.weather, updating=weather_updating)}"
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


def _egg_entry_date_from_choice(choice: str, *, today: date | None = None) -> date:
    current = today or date.today()
    if choice == "today":
        return current
    if choice == "yesterday":
        return current - timedelta(days=1)
    raise ValueError("unknown date choice")


def _egg_entry_date_label(choice: str) -> str:
    if choice == "today":
        return "сегодня"
    if choice == "yesterday":
        return "вчера"
    return "за выбранный день"


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
        return "Погода за сегодня еще не загружена."
    precipitation = (
        "нет данных"
        if weather.precipitation_mm is None
        else f"{weather.precipitation_mm:.1f} мм"
    )
    return (
        f"Погода на {weather.weather_date.isoformat()}:\n"
        f"- день: {_format_weather_part(weather.day_temperature_min_c, weather.day_temperature_max_c, weather.day_condition)}\n"
        f"- ночь: {_format_weather_part(weather.night_temperature_min_c, weather.night_temperature_max_c, weather.night_condition)}\n"
        f"- завтра: {_format_tomorrow_weather(weather)}\n"
        f"- осадки: {precipitation}\n"
        f"- источник: {weather.provider}"
    )


def _format_weather_screen(city: str, weather: DailyWeather | None, *, updating: bool = False) -> str:
    update_line = "Погода обновляется..." if updating else "Погода загружена из кеша."
    return (
        "🌦 Город и погода\n\n"
        f"Город: {city}\n"
        f"{update_line}\n\n"
        f"{_format_weather(weather)}"
        "\n\n"
        "Погодная поправка в расчетах ориентировочная: бот смотрит уличную погоду, "
        "а яйценоскость сильнее зависит от фактических условий в курятнике."
    )


def _format_weather_brief(weather: DailyWeather | None, *, updating: bool = False) -> str:
    if updating:
        if weather is None:
            return "Погода: обновляется..."
        return "Погода: обновляется, пока показаны последние сохраненные данные.\n" + _format_weather_brief(weather)
    if weather is None:
        return "Погода: не загружена."
    return (
        f"Погода, {_display_city(weather.city)}:\n"
        f"День: {_format_weather_part(weather.day_temperature_min_c, weather.day_temperature_max_c, weather.day_condition)}\n"
        f"Ночь: {_format_weather_part(weather.night_temperature_min_c, weather.night_temperature_max_c, weather.night_condition)}\n"
        f"Завтра: {_format_tomorrow_weather(weather)}"
    )


def _format_weather_part(
    temperature_min_c: float | None,
    temperature_max_c: float | None,
    condition: str,
) -> str:
    if temperature_min_c is None and temperature_max_c is None:
        temperature = "температура нет данных"
    elif temperature_min_c is None:
        temperature = f"до {temperature_max_c:.0f} °C"
    elif temperature_max_c is None:
        temperature = f"от {temperature_min_c:.0f} °C"
    elif round(temperature_min_c) == round(temperature_max_c):
        temperature = f"{temperature_max_c:.0f} °C"
    else:
        temperature = f"{temperature_min_c:.0f}...{temperature_max_c:.0f} °C"
    condition_text = _display_weather_condition(condition) or "состояние не уточнено"
    return f"{temperature}, {condition_text}"


def _format_tomorrow_weather(weather: DailyWeather) -> str:
    prefix = f"{weather.tomorrow_date.isoformat()}: " if weather.tomorrow_date else ""
    return prefix + _format_weather_part(
        weather.tomorrow_temperature_min_c,
        weather.tomorrow_temperature_max_c,
        weather.tomorrow_condition,
    )


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


def _display_city(value: str) -> str:
    clean = " ".join(value.strip().split())
    return clean.replace(" Область", " область")


def _display_weather_condition(value: str) -> str:
    clean = " ".join(value.strip().split())
    if not clean:
        return ""
    lower = clean.lower()
    translations = {
        "patchy rain nearby": "местами дождь поблизости",
        "sunny": "ясно",
        "clear": "ясно",
        "partly cloudy": "переменная облачность",
        "cloudy": "облачно",
        "overcast": "пасмурно",
        "mist": "дымка",
        "fog": "туман",
        "light rain": "небольшой дождь",
        "moderate rain": "дождь",
        "heavy rain": "сильный дождь",
    }
    if lower in translations:
        return translations[lower]
    if any("a" <= char <= "z" for char in lower):
        return "погодные условия уточняются"
    return clean[:1].lower() + clean[1:]
