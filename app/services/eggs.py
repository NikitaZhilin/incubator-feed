from datetime import date, datetime, timedelta, timezone
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain import DailyWeather, EggEntry, EggStats, HenLayingExclusion, WeatherSettings
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository
from app.services.weather import OpenMeteoWeatherClient


EXCLUSION_REASON_LABELS = {
    "broody": "наседка сидит на яйцах",
    "with_chicks": "уход за цыплятами",
    "molting": "линька",
    "sick": "болеет или восстановление",
    "other": "другая причина",
}

MAX_MULTI_DAY_COLLECTION_DAYS = 30


class EggService:
    def __init__(
        self,
        eggs: EggRepository,
        feeds: FeedRepository,
        weather_client: OpenMeteoWeatherClient | None = None,
        timezone_name: str = "Europe/Moscow",
    ) -> None:
        self.eggs = eggs
        self.feeds = feeds
        self.weather_client = weather_client
        self.timezone_name = timezone_name

    def record_today(self, user_id: int, eggs_count: int, *, today: date | None = None, note: str = "") -> EggEntry:
        current_date = today or self.current_date()
        if eggs_count < 0:
            raise ValueError("Количество яиц не может быть отрицательным.")
        total_hens = self.total_laying_hens(user_id)
        excluded = self.excluded_hens_count(user_id, on_date=current_date, total_hens_count=total_hens)
        active_hens = max(total_hens - excluded, 0)
        return self.eggs.create_entry(
            user_id=user_id,
            entry_date=current_date,
            eggs_count=eggs_count,
            active_hens_count=active_hens,
            total_hens_count=total_hens,
            excluded_hens_count=excluded,
            note=note,
        )

    def record_entry(
        self,
        user_id: int,
        eggs_count: int,
        *,
        entry_date: date,
        note: str = "",
    ) -> EggEntry:
        return self.record_today(user_id, eggs_count, today=entry_date, note=note)

    def preview_multi_day_distribution(
        self,
        user_id: int,
        total_eggs: int,
        *,
        days: int | None = None,
        today: date | None = None,
        use_empty_days: bool = False,
    ) -> list[tuple[date, int]]:
        if total_eggs <= 0:
            raise ValueError("Количество яиц должно быть больше нуля.")
        current_date = today or self.current_date()
        if days is None:
            average = self.average_recorded_eggs(user_id)
            if average <= 0:
                raise ValueError("Недостаточно статистики. Укажите количество дней вручную.")
            days = min(max(ceil(total_eggs / average), 2), MAX_MULTI_DAY_COLLECTION_DAYS)
            use_empty_days = True
        self._validate_multi_day_period(days)
        if use_empty_days:
            dates = self.recent_empty_days(user_id, count=days, today=current_date)
            if not dates:
                raise ValueError("За последние 30 дней нет пустых дней. Укажите количество дней вручную.")
        else:
            dates = [current_date - timedelta(days=offset) for offset in range(days)]
        counts = self.distribute_eggs(total_eggs, len(dates))
        return list(zip(dates, counts))

    def record_multi_day_collection(
        self,
        user_id: int,
        total_eggs: int,
        distribution: list[tuple[date, int]],
        *,
        auto_period: bool = False,
    ) -> list[EggEntry]:
        if not distribution:
            raise ValueError("Нет дат для распределения сбора.")
        if total_eggs <= 0:
            raise ValueError("Количество яиц должно быть больше нуля.")
        if sum(count for _, count in distribution) != total_eggs:
            raise ValueError("Распределение не сходится с общим количеством яиц.")
        days = len(distribution)
        note = f"Сбор за несколько дней: {total_eggs} шт. за {days} дн."
        if auto_period:
            note += ", период рассчитан автоматически"
        return [
            self.record_entry(
                user_id,
                eggs_count,
                entry_date=entry_date,
                note=note,
            )
            for entry_date, eggs_count in distribution
        ]

    def average_recorded_eggs(self, user_id: int) -> float:
        return float(self.eggs.average_daily_total(user_id) or 0)

    def recent_empty_days(
        self,
        user_id: int,
        *,
        count: int,
        today: date | None = None,
        max_lookback_days: int = MAX_MULTI_DAY_COLLECTION_DAYS,
    ) -> list[date]:
        if count <= 0:
            raise ValueError("Количество дней должно быть больше нуля.")
        current_date = today or self.current_date()
        lookback_days = max(max_lookback_days, count)
        start_date = current_date - timedelta(days=lookback_days - 1)
        existing_dates = self.eggs.entry_dates_between(
            user_id,
            start_date=start_date,
            end_date=current_date,
        )
        days: list[date] = []
        for offset in range(lookback_days):
            candidate = current_date - timedelta(days=offset)
            if candidate not in existing_dates:
                days.append(candidate)
                if len(days) >= count:
                    break
        return days

    @staticmethod
    def distribute_eggs(total_eggs: int, days: int) -> list[int]:
        if total_eggs < 0:
            raise ValueError("Количество яиц не может быть отрицательным.")
        if days <= 0:
            raise ValueError("Количество дней должно быть больше нуля.")
        base = total_eggs // days
        remainder = total_eggs % days
        return [base + (1 if index < remainder else 0) for index in range(days)]

    @staticmethod
    def _validate_multi_day_period(days: int) -> None:
        if days < 2:
            raise ValueError("Период должен быть минимум 2 дня.")
        if days > MAX_MULTI_DAY_COLLECTION_DAYS:
            raise ValueError(f"Период должен быть не больше {MAX_MULTI_DAY_COLLECTION_DAYS} дней.")

    def get_entry(self, user_id: int, entry_id: int) -> EggEntry | None:
        return self.eggs.get_entry(entry_id, user_id)

    def list_entries(self, user_id: int, *, limit: int = 20) -> list[EggEntry]:
        return self.eggs.list_entries(user_id, limit=limit)

    def update_entry(
        self,
        *,
        user_id: int,
        entry_id: int,
        entry_date: date | None = None,
        eggs_count: int | None = None,
        note: str | None = None,
    ) -> EggEntry:
        current = self.eggs.get_entry(entry_id, user_id)
        if current is None:
            raise ValueError("Запись по яйцам не найдена.")
        next_date = entry_date or current.entry_date
        next_count = current.eggs_count if eggs_count is None else eggs_count
        if next_count < 0:
            raise ValueError("Количество яиц не может быть отрицательным.")
        total_hens = self.total_laying_hens(user_id)
        excluded = self.excluded_hens_count(user_id, on_date=next_date, total_hens_count=total_hens)
        updated = self.eggs.update_entry(
            entry_id=entry_id,
            user_id=user_id,
            entry_date=next_date,
            eggs_count=next_count,
            active_hens_count=max(total_hens - excluded, 0),
            total_hens_count=total_hens,
            excluded_hens_count=excluded,
            note=note.strip() if note is not None else None,
        )
        if updated is None:
            raise ValueError("Запись по яйцам не найдена.")
        return updated

    def delete_entry(self, *, user_id: int, entry_id: int) -> bool:
        return self.eggs.delete_entry(entry_id=entry_id, user_id=user_id)

    def stats(
        self,
        user_id: int,
        *,
        today: date | None = None,
        refresh_weather: bool = False,
    ) -> EggStats:
        current_date = today or self.current_date()
        total_hens = self.total_laying_hens(user_id)
        active_exclusions = tuple(self.eggs.list_active_exclusions(user_id, on_date=current_date))
        excluded_hens = min(sum(item.hens_count for item in active_exclusions), total_hens)
        active_hens = max(total_hens - excluded_hens, 0)
        today_eggs = self.eggs.sum_between(user_id, start_date=current_date, end_date=current_date)
        week_start = current_date - timedelta(days=6)
        month_start = current_date - timedelta(days=29)
        week_eggs = self.eggs.sum_between(user_id, start_date=week_start, end_date=current_date)
        month_eggs = self.eggs.sum_between(user_id, start_date=month_start, end_date=current_date)
        week_recorded_days = len(self.eggs.daily_totals(user_id, start_date=week_start, end_date=current_date))
        month_recorded_days = len(self.eggs.daily_totals(user_id, start_date=month_start, end_date=current_date))
        week_average = week_eggs / week_recorded_days if week_recorded_days else 0
        month_average = month_eggs / month_recorded_days if month_recorded_days else 0
        eggs_per_active_hen = (week_average / active_hens) if active_hens > 0 else None
        weather_settings = self.eggs.get_weather_settings(user_id)
        weather = (
            self.refresh_weather(user_id, today=current_date)
            if refresh_weather
            else self.get_daily_weather(user_id, today=current_date)
        )
        weather_impact_percent, weather_note = self._weather_impact(weather)
        weather_adjusted_week_forecast = (
            max(self._round_forecast(week_average * 7 * (1 + weather_impact_percent / 100)), 0)
            if weather is not None
            else None
        )
        return EggStats(
            today=current_date,
            total_hens_count=total_hens,
            excluded_hens_count=excluded_hens,
            active_hens_count=active_hens,
            today_eggs=today_eggs,
            week_eggs=week_eggs,
            week_average=week_average,
            month_eggs=month_eggs,
            month_average=month_average,
            eggs_per_active_hen=eggs_per_active_hen,
            next_week_forecast=self._round_forecast(week_average * 7),
            weather_adjusted_week_forecast=weather_adjusted_week_forecast,
            weather_impact_percent=weather_impact_percent,
            weather_note=weather_note,
            weather=weather,
            active_exclusions=active_exclusions,
            weather_city=weather_settings.city,
        )

    def history(self, user_id: int, *, days: int = 14, today: date | None = None) -> list[tuple[date, int]]:
        current_date = today or self.current_date()
        start_date = current_date - timedelta(days=max(days - 1, 0))
        totals = self.eggs.daily_totals(user_id, start_date=start_date, end_date=current_date)
        return [
            (current_date - timedelta(days=offset), totals.get(current_date - timedelta(days=offset), 0))
            for offset in range(days)
        ]

    def create_exclusion(
        self,
        *,
        user_id: int,
        hens_count: int,
        reason: str,
        started_at: date | None = None,
        expected_until: date | None = None,
    ) -> HenLayingExclusion:
        if hens_count <= 0:
            raise ValueError("Количество кур должно быть больше нуля.")
        if reason not in EXCLUSION_REASON_LABELS:
            raise ValueError("Неизвестная причина.")
        current_date = started_at or self.current_date()
        total_hens = self.total_laying_hens(user_id)
        if total_hens > 0 and hens_count > total_hens:
            raise ValueError(f"В поголовье сейчас {total_hens} несушек. Укажите число не больше этого.")
        if expected_until is not None and expected_until < current_date:
            raise ValueError("Дата окончания не может быть раньше начала.")
        return self.eggs.create_exclusion(
            user_id=user_id,
            hens_count=hens_count,
            reason=reason,
            started_at=current_date,
            expected_until=expected_until,
        )

    def list_open_exclusions(self, user_id: int) -> list[HenLayingExclusion]:
        return self.eggs.list_open_exclusions(user_id)

    def finish_exclusion(self, *, user_id: int, exclusion_id: int, ended_at: date | None = None) -> bool:
        return self.eggs.finish_exclusion(
            exclusion_id=exclusion_id,
            user_id=user_id,
            ended_at=ended_at or self.current_date(),
        )

    def get_weather_settings(self, user_id: int) -> WeatherSettings:
        return self.eggs.get_weather_settings(user_id)

    def update_weather_city(self, *, user_id: int, city: str) -> WeatherSettings:
        clean_city = city.strip()[:120]
        if not clean_city:
            raise ValueError("Введите город текстом.")
        if self.weather_client is None:
            return self.eggs.update_weather_city(user_id=user_id, city=clean_city)
        location = self.weather_client.geocode(clean_city)
        display_city = location.name
        if location.admin1:
            display_city = f"{display_city}, {location.admin1}"
        return self.eggs.update_weather_city(
            user_id=user_id,
            city=display_city,
            latitude=location.latitude,
            longitude=location.longitude,
            provider="open-meteo",
        )

    def get_daily_weather(self, user_id: int, *, today: date | None = None) -> DailyWeather | None:
        return self.eggs.get_daily_weather(user_id=user_id, weather_date=today or self.current_date())

    def refresh_weather(
        self,
        user_id: int,
        *,
        today: date | None = None,
        force: bool = False,
    ) -> DailyWeather | None:
        current_date = today or self.current_date()
        settings = self.eggs.get_weather_settings(user_id)
        stored = self.eggs.get_daily_weather(user_id=user_id, weather_date=current_date)
        if not force and stored is not None and stored.city == settings.city:
            return stored
        if self.weather_client is None:
            return stored
        if settings.latitude is None or settings.longitude is None:
            location = self.weather_client.geocode(settings.city)
            settings = self.eggs.update_weather_city(
                user_id=user_id,
                city=location.name if not location.admin1 else f"{location.name}, {location.admin1}",
                latitude=location.latitude,
                longitude=location.longitude,
                provider="open-meteo",
            )
        try:
            weather_day = self.weather_client.forecast_today(
                latitude=settings.latitude,
                longitude=settings.longitude,
                today=current_date,
            )
        except Exception as primary_exc:
            try:
                weather_day = self.weather_client.forecast_today_by_coordinates(
                    latitude=settings.latitude,
                    longitude=settings.longitude,
                    today=current_date,
                )
            except Exception as fallback_exc:
                raise RuntimeError(
                    "погодные сервисы не ответили. "
                    f"Open-Meteo: {primary_exc}; wttr.in: {fallback_exc}"
                ) from fallback_exc
        return self.eggs.upsert_daily_weather(
            user_id=user_id,
            weather_date=weather_day.date,
            city=settings.city,
            temperature_avg_c=weather_day.temperature_avg_c,
            temperature_min_c=weather_day.temperature_min_c,
            temperature_max_c=weather_day.temperature_max_c,
            precipitation_mm=weather_day.precipitation_mm,
            condition=weather_day.condition,
            provider=weather_day.provider,
            day_temperature_min_c=weather_day.day_temperature_min_c,
            day_temperature_max_c=weather_day.day_temperature_max_c,
            day_condition=weather_day.day_condition,
            night_temperature_min_c=weather_day.night_temperature_min_c,
            night_temperature_max_c=weather_day.night_temperature_max_c,
            night_condition=weather_day.night_condition,
            tomorrow_date=weather_day.tomorrow_date,
            tomorrow_temperature_min_c=weather_day.tomorrow_temperature_min_c,
            tomorrow_temperature_max_c=weather_day.tomorrow_temperature_max_c,
            tomorrow_condition=weather_day.tomorrow_condition,
        )

    def weather_needs_refresh(
        self,
        user_id: int,
        *,
        today: date | None = None,
        max_age: timedelta = timedelta(hours=6),
    ) -> bool:
        current_date = today or self.current_date()
        settings = self.eggs.get_weather_settings(user_id)
        stored = self.eggs.get_daily_weather(user_id=user_id, weather_date=current_date)
        if stored is None or stored.city != settings.city:
            return True
        created_at = stored.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - created_at > max_age

    def total_laying_hens(self, user_id: int) -> int:
        return sum(
            group.bird_count
            for group in self.feeds.list_bird_groups(user_id)
            if group.is_active and group.group_kind == "adult" and group.role == "hens"
        )

    def current_date(self, now: datetime | None = None) -> date:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(self._timezone()).date()

    def excluded_hens_count(self, user_id: int, *, on_date: date, total_hens_count: int | None = None) -> int:
        total_hens = self.total_laying_hens(user_id) if total_hens_count is None else total_hens_count
        active_exclusions = self.eggs.list_active_exclusions(user_id, on_date=on_date)
        return min(sum(item.hens_count for item in active_exclusions), total_hens)

    @staticmethod
    def _round_forecast(value: float) -> int:
        return int(value + 0.5)

    @staticmethod
    def _weather_impact(weather: DailyWeather | None) -> tuple[int, str]:
        if weather is None or weather.temperature_avg_c is None:
            return 0, "Погодные данные за сегодня еще не загружены."
        avg = weather.temperature_avg_c
        precipitation = weather.precipitation_mm or 0
        if avg < -10 or avg > 35:
            percent = -20
        elif avg < 0 or avg > 32:
            percent = -15
        elif avg < 5 or avg > 28:
            percent = -10
        elif avg < 10 or avg > 24:
            percent = -5
        else:
            percent = 0

        if precipitation >= 10 and percent > -20:
            percent -= 5

        if percent == 0:
            note = "Погодная поправка не применяется: уличная температура в комфортном диапазоне."
        elif avg < 10:
            note = "Ориентировочная поправка из-за холода. Важнее фактическая температура и свет в курятнике."
        elif avg > 24:
            note = "Ориентировочная поправка из-за жары. Важнее фактическая температура, вода и вентиляция."
        else:
            note = "Ориентировочная погодная поправка."
        if precipitation >= 10:
            note += " Сильные осадки могут дополнительно снижать активность птицы."
        return percent, note

    def _timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")
