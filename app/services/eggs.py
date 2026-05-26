from datetime import date, timedelta

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


class EggService:
    def __init__(
        self,
        eggs: EggRepository,
        feeds: FeedRepository,
        weather_client: OpenMeteoWeatherClient | None = None,
    ) -> None:
        self.eggs = eggs
        self.feeds = feeds
        self.weather_client = weather_client

    def record_today(self, user_id: int, eggs_count: int, *, today: date | None = None, note: str = "") -> EggEntry:
        current_date = today or date.today()
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

    def stats(
        self,
        user_id: int,
        *,
        today: date | None = None,
        refresh_weather: bool = False,
    ) -> EggStats:
        current_date = today or date.today()
        total_hens = self.total_laying_hens(user_id)
        active_exclusions = tuple(self.eggs.list_active_exclusions(user_id, on_date=current_date))
        excluded_hens = min(sum(item.hens_count for item in active_exclusions), total_hens)
        active_hens = max(total_hens - excluded_hens, 0)
        today_eggs = self.eggs.sum_between(user_id, start_date=current_date, end_date=current_date)
        week_start = current_date - timedelta(days=6)
        month_start = current_date - timedelta(days=29)
        week_eggs = self.eggs.sum_between(user_id, start_date=week_start, end_date=current_date)
        month_eggs = self.eggs.sum_between(user_id, start_date=month_start, end_date=current_date)
        week_average = week_eggs / 7
        month_average = month_eggs / 30
        eggs_per_active_hen = (week_average / active_hens) if active_hens > 0 else None
        weather_settings = self.eggs.get_weather_settings(user_id)
        weather = (
            self.refresh_weather(user_id, today=current_date)
            if refresh_weather
            else self.get_daily_weather(user_id, today=current_date)
        )
        weather_impact_percent, weather_note = self._weather_impact(weather)
        weather_adjusted_week_forecast = (
            max(round(week_average * 7 * (1 + weather_impact_percent / 100)), 0)
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
            next_week_forecast=round(week_average * 7),
            weather_adjusted_week_forecast=weather_adjusted_week_forecast,
            weather_impact_percent=weather_impact_percent,
            weather_note=weather_note,
            weather=weather,
            active_exclusions=active_exclusions,
            weather_city=weather_settings.city,
        )

    def history(self, user_id: int, *, days: int = 14, today: date | None = None) -> list[tuple[date, int]]:
        current_date = today or date.today()
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
        current_date = started_at or date.today()
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
            ended_at=ended_at or date.today(),
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
        return self.eggs.get_daily_weather(user_id=user_id, weather_date=today or date.today())

    def refresh_weather(
        self,
        user_id: int,
        *,
        today: date | None = None,
        force: bool = False,
    ) -> DailyWeather | None:
        current_date = today or date.today()
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
        )

    def total_laying_hens(self, user_id: int) -> int:
        return sum(
            group.bird_count
            for group in self.feeds.list_bird_groups(user_id)
            if group.is_active and group.group_kind == "adult" and group.role == "hens"
        )

    def excluded_hens_count(self, user_id: int, *, on_date: date, total_hens_count: int | None = None) -> int:
        total_hens = self.total_laying_hens(user_id) if total_hens_count is None else total_hens_count
        active_exclusions = self.eggs.list_active_exclusions(user_id, on_date=on_date)
        return min(sum(item.hens_count for item in active_exclusions), total_hens)

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
