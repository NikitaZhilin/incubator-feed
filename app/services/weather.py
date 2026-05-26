from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class GeocodedLocation:
    name: str
    latitude: float
    longitude: float
    country: str = ""
    admin1: str = ""


@dataclass(frozen=True)
class WeatherDay:
    date: date
    temperature_avg_c: float | None
    temperature_min_c: float | None
    temperature_max_c: float | None
    precipitation_mm: float | None
    condition: str
    provider: str = "open-meteo"


class OpenMeteoWeatherClient:
    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        self.timeout_seconds = timeout_seconds

    def geocode(self, city: str) -> GeocodedLocation:
        payload = self._get_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            {
                "name": city,
                "count": 1,
                "language": "ru",
                "format": "json",
            },
        )
        results = payload.get("results") or []
        if not results:
            raise ValueError("Город не найден. Проверьте написание или укажите ближайший крупный город.")
        item = results[0]
        return GeocodedLocation(
            name=_normalize_place_name(str(item.get("name") or city)),
            latitude=float(item["latitude"]),
            longitude=float(item["longitude"]),
            country=str(item.get("country") or ""),
            admin1=_normalize_place_name(str(item.get("admin1") or "")),
        )

    def forecast_today(self, *, latitude: float, longitude: float, today: date) -> WeatherDay:
        payload = self._get_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": f"{latitude:.6f}",
                "longitude": f"{longitude:.6f}",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum",
                "timezone": "auto",
                "forecast_days": 3,
            },
        )
        daily = payload.get("daily") or {}
        dates = [date.fromisoformat(str(value)) for value in daily.get("time", [])]
        if not dates:
            raise ValueError("Погодный сервис не вернул дневной прогноз.")
        try:
            index = dates.index(today)
        except ValueError:
            index = 0
        return WeatherDay(
            date=dates[index],
            temperature_avg_c=_float_at(daily.get("temperature_2m_mean"), index),
            temperature_min_c=_float_at(daily.get("temperature_2m_min"), index),
            temperature_max_c=_float_at(daily.get("temperature_2m_max"), index),
            precipitation_mm=_float_at(daily.get("precipitation_sum"), index),
            condition=_weather_code_label(_int_at(daily.get("weather_code"), index)),
            provider="open-meteo",
        )

    def forecast_today_by_city(self, *, city: str, today: date) -> WeatherDay:
        clean_city = city.split(",", 1)[0].strip() or city.strip()
        return self._forecast_today_from_wttr(location=quote(clean_city, safe=""), today=today)

    def forecast_today_by_coordinates(
        self,
        *,
        latitude: float,
        longitude: float,
        today: date,
    ) -> WeatherDay:
        return self._forecast_today_from_wttr(
            location=f"{latitude:.6f},{longitude:.6f}",
            today=today,
        )

    def _forecast_today_from_wttr(self, *, location: str, today: date) -> WeatherDay:
        payload = self._get_json(
            f"https://wttr.in/{location}",
            {
                "format": "j1",
                "lang": "ru",
            },
        )
        current = (payload.get("current_condition") or [{}])[0]
        weather = (payload.get("weather") or [{}])[0]
        condition_items = current.get("lang_ru") or current.get("weatherDesc") or []
        condition = ""
        if condition_items:
            condition = str(condition_items[0].get("value") or "")
        avg = _float_value(weather.get("avgtempC"))
        if avg is None:
            avg = _float_value(current.get("temp_C"))
        return WeatherDay(
            date=today,
            temperature_avg_c=avg,
            temperature_min_c=_float_value(weather.get("mintempC")),
            temperature_max_c=_float_value(weather.get("maxtempC")),
            precipitation_mm=_float_value(current.get("precipMM")),
            condition=_normalize_condition(condition),
            provider="wttr.in",
        )

    def _get_json(self, base_url: str, params: dict[str, object]) -> dict:
        url = f"{base_url}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "incubator-feed-bot/1.0"})
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


def _float_at(values, index: int) -> float | None:
    if not values or index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def _float_value(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _int_at(values, index: int) -> int | None:
    if not values or index >= len(values) or values[index] is None:
        return None
    return int(values[index])


def _weather_code_label(code: int | None) -> str:
    if code is None:
        return ""
    if code == 0:
        return "ясно"
    if code in {1, 2, 3}:
        return "переменная облачность"
    if code in {45, 48}:
        return "туман"
    if code in {51, 53, 55, 56, 57}:
        return "морось"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "дождь"
    if code in {71, 73, 75, 77, 85, 86}:
        return "снег"
    if code in {95, 96, 99}:
        return "гроза"
    return f"код погоды {code}"


def _normalize_place_name(value: str) -> str:
    clean = " ".join(value.strip().split())
    if not clean:
        return ""
    replacements = {
        "Курская Область": "Курская область",
        "Московская Область": "Московская область",
        "Ленинградская Область": "Ленинградская область",
    }
    return replacements.get(clean, clean.replace(" Область", " область"))


def _normalize_condition(value: str) -> str:
    clean = " ".join(value.strip().split())
    if not clean:
        return ""
    lower = clean.lower()
    translations = {
        "sunny": "ясно",
        "clear": "ясно",
        "partly cloudy": "переменная облачность",
        "cloudy": "облачно",
        "overcast": "пасмурно",
        "mist": "дымка",
        "fog": "туман",
        "patchy rain nearby": "местами дождь поблизости",
        "light rain": "небольшой дождь",
        "moderate rain": "дождь",
        "heavy rain": "сильный дождь",
        "light drizzle": "морось",
        "patchy light drizzle": "местами морось",
        "light snow": "небольшой снег",
        "moderate snow": "снег",
        "heavy snow": "сильный снег",
        "thundery outbreaks possible": "возможна гроза",
    }
    if lower in translations:
        return translations[lower]
    if any("a" <= char <= "z" for char in lower):
        return "погодные условия уточняются"
    return clean[:1].lower() + clean[1:]
