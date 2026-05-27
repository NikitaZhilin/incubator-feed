from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.eggs import EggService
from app.services.feeds import FeedService
from app.services.weather import GeocodedLocation, WeatherDay
from app.services.weather import OpenMeteoWeatherClient
from app.handlers.eggs import _display_city, _display_weather_condition, _format_weather_brief
from app.storage.database import Database
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository


class EggServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.db")
        self.database.initialize()
        self.feed_repository = FeedRepository(self.database)
        self.feed_service = FeedService(self.feed_repository)
        self.egg_service = EggService(EggRepository(self.database), self.feed_repository)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_stats_count_only_adult_hens(self) -> None:
        self.feed_service.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=11,
            species="chicken",
            role="hens",
        )
        self.feed_service.create_bird_group(
            user_id=1,
            name="Петухи",
            bird_count=2,
            species="chicken",
            role="roosters",
        )
        self.feed_service.create_bird_group(
            user_id=1,
            name="Цыплята",
            bird_count=8,
            species="chicken",
            group_kind="chicks",
            role="chicks",
            hatched_at=date(2026, 5, 1),
        )

        stats = self.egg_service.stats(1, today=date(2026, 5, 26))

        self.assertEqual(stats.total_hens_count, 11)
        self.assertEqual(stats.active_hens_count, 11)

    def test_recording_eggs_uses_active_hens_after_exclusion(self) -> None:
        self.feed_service.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=11,
            species="chicken",
            role="hens",
        )
        self.egg_service.create_exclusion(
            user_id=1,
            hens_count=1,
            reason="broody",
            started_at=date(2026, 5, 20),
            expected_until=date(2026, 6, 15),
        )

        entry = self.egg_service.record_today(1, 7, today=date(2026, 5, 26))
        stats = self.egg_service.stats(1, today=date(2026, 5, 26))

        self.assertEqual(entry.total_hens_count, 11)
        self.assertEqual(entry.excluded_hens_count, 1)
        self.assertEqual(entry.active_hens_count, 10)
        self.assertEqual(stats.week_eggs, 7)
        self.assertEqual(stats.next_week_forecast, 49)
        self.assertEqual(round(stats.eggs_per_active_hen, 2), 0.7)

    def test_stats_average_uses_days_with_entries(self) -> None:
        self.feed_service.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=12,
            species="chicken",
            role="hens",
        )

        self.egg_service.record_today(1, 7, today=date(2026, 5, 27))
        self.egg_service.record_today(1, 8, today=date(2026, 5, 28))

        stats = self.egg_service.stats(1, today=date(2026, 5, 28))

        self.assertEqual(stats.week_eggs, 15)
        self.assertEqual(stats.month_eggs, 15)
        self.assertEqual(stats.week_average, 7.5)
        self.assertEqual(stats.month_average, 7.5)
        self.assertEqual(stats.next_week_forecast, 53)
        self.assertEqual(round(stats.eggs_per_active_hen, 3), 0.625)

    def test_update_entry_moves_eggs_to_correct_day(self) -> None:
        entry = self.egg_service.record_today(1, 7, today=date(2026, 5, 25))

        updated = self.egg_service.update_entry(
            user_id=1,
            entry_id=entry.id,
            entry_date=date(2026, 5, 26),
        )
        history = self.egg_service.history(1, days=3, today=date(2026, 5, 27))

        self.assertEqual(updated.entry_date, date(2026, 5, 26))
        self.assertEqual(updated.eggs_count, 7)
        self.assertEqual(history, [(date(2026, 5, 27), 0), (date(2026, 5, 26), 7), (date(2026, 5, 25), 0)])

    def test_history_returns_zero_days_without_entries(self) -> None:
        rows = self.egg_service.history(1, days=3, today=date(2026, 5, 26))

        self.assertEqual(rows, [(date(2026, 5, 26), 0), (date(2026, 5, 25), 0), (date(2026, 5, 24), 0)])

    def test_current_date_uses_bot_timezone_not_server_utc_date(self) -> None:
        service = EggService(
            EggRepository(self.database),
            self.feed_repository,
            timezone_name="Europe/Moscow",
        )

        current_date = service.current_date(datetime(2026, 5, 26, 23, 45, tzinfo=timezone.utc))

        self.assertEqual(current_date, date(2026, 5, 27))

    def test_weather_is_loaded_and_applied_to_forecast(self) -> None:
        class FakeWeatherClient:
            def geocode(self, city: str) -> GeocodedLocation:
                return GeocodedLocation(name="Курск", admin1="Курская область", latitude=51.73, longitude=36.19)

            def forecast_today(self, *, latitude: float, longitude: float, today: date) -> WeatherDay:
                return WeatherDay(
                    date=today,
                    temperature_avg_c=33.0,
                    temperature_min_c=27.0,
                    temperature_max_c=36.0,
                    precipitation_mm=0.0,
                    condition="ясно",
                )

        service = EggService(EggRepository(self.database), self.feed_repository, FakeWeatherClient())
        self.feed_service.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=10,
            species="chicken",
            role="hens",
        )
        for offset in range(7):
            service.record_today(1, 10, today=date(2026, 5, 20 + offset))

        settings = service.update_weather_city(user_id=1, city="Курск")
        weather = service.refresh_weather(1, today=date(2026, 5, 26), force=True)
        stats = service.stats(1, today=date(2026, 5, 26), refresh_weather=True)

        self.assertEqual(settings.city, "Курск, Курская область")
        self.assertEqual(weather.temperature_avg_c, 33.0)
        self.assertEqual(stats.next_week_forecast, 70)
        self.assertEqual(stats.weather_impact_percent, -15)
        self.assertEqual(stats.weather_adjusted_week_forecast, 60)
        self.assertIn("жары", stats.weather_note)

    def test_weather_falls_back_to_city_provider(self) -> None:
        class FallbackWeatherClient:
            def geocode(self, city: str) -> GeocodedLocation:
                return GeocodedLocation(name="Курск", admin1="Курская область", latitude=51.73, longitude=36.19)

            def forecast_today(self, *, latitude: float, longitude: float, today: date) -> WeatherDay:
                raise TimeoutError("open-meteo timeout")

            def forecast_today_by_city(self, *, city: str, today: date) -> WeatherDay:
                raise AssertionError("Fallback must use coordinates to avoid Cyrillic URL issues.")

            def forecast_today_by_coordinates(self, *, latitude: float, longitude: float, today: date) -> WeatherDay:
                return WeatherDay(
                    date=today,
                    temperature_avg_c=18.0,
                    temperature_min_c=12.0,
                    temperature_max_c=23.0,
                    precipitation_mm=1.0,
                    condition="облачно",
                    provider="wttr.in",
                )

        service = EggService(EggRepository(self.database), self.feed_repository, FallbackWeatherClient())
        service.update_weather_city(user_id=1, city="Курск")

        weather = service.refresh_weather(1, today=date(2026, 5, 26), force=True)

        self.assertEqual(weather.provider, "wttr.in")
        self.assertEqual(weather.temperature_avg_c, 18.0)

    def test_wttr_city_url_encodes_cyrillic_city(self) -> None:
        class CapturingWeatherClient(OpenMeteoWeatherClient):
            def __init__(self) -> None:
                super().__init__()
                self.request_url = ""

            def _get_json(self, base_url: str, params: dict[str, object]) -> dict:
                self.request_url = base_url
                return {
                    "current_condition": [
                        {
                            "temp_C": "18",
                            "precipMM": "0",
                            "lang_ru": [{"value": "ясно"}],
                        }
                    ],
                    "weather": [
                        {
                            "avgtempC": "18",
                            "mintempC": "12",
                            "maxtempC": "23",
                        }
                    ],
                }

        client = CapturingWeatherClient()

        weather = client.forecast_today_by_city(city="Курск, Курская область", today=date(2026, 5, 26))

        self.assertIn("%D0%9A%D1%83%D1%80%D1%81%D0%BA", client.request_url)
        self.assertEqual(weather.provider, "wttr.in")

    def test_weather_display_is_russian_for_cached_english_values(self) -> None:
        self.assertEqual(_display_weather_condition("Patchy rain nearby"), "местами дождь поблизости")
        self.assertEqual(_display_city("Курск, Курская Область"), "Курск, Курская область")

    def test_open_meteo_forecast_parses_day_night_and_tomorrow(self) -> None:
        class FakeOpenMeteoClient(OpenMeteoWeatherClient):
            def _get_json(self, base_url: str, params: dict[str, object]) -> dict:
                return {
                    "daily": {
                        "time": ["2026-05-27", "2026-05-28"],
                        "weather_code": [3, 61],
                        "temperature_2m_max": [22, 23],
                        "temperature_2m_min": [10, 11],
                        "temperature_2m_mean": [16, 17],
                        "precipitation_sum": [0.5, 2.0],
                    },
                    "hourly": {
                        "time": [
                            "2026-05-27T08:00",
                            "2026-05-27T14:00",
                            "2026-05-27T21:00",
                            "2026-05-28T03:00",
                        ],
                        "temperature_2m": [14, 22, 15, 10],
                        "weather_code": [2, 3, 0, 0],
                        "precipitation": [0, 0, 0, 0],
                    },
                }

        weather = FakeOpenMeteoClient().forecast_today(
            latitude=51.73,
            longitude=36.19,
            today=date(2026, 5, 27),
        )

        self.assertEqual(weather.day_temperature_min_c, 14)
        self.assertEqual(weather.day_temperature_max_c, 22)
        self.assertEqual(weather.night_temperature_min_c, 10)
        self.assertEqual(weather.night_temperature_max_c, 15)
        self.assertEqual(weather.tomorrow_date, date(2026, 5, 28))
        self.assertEqual(weather.tomorrow_condition, "дождь")

    def test_weather_brief_formats_day_night_and_tomorrow(self) -> None:
        weather = self.egg_service.eggs.upsert_daily_weather(
            user_id=1,
            weather_date=date(2026, 5, 27),
            city="Курск, Курская область",
            temperature_avg_c=16,
            temperature_min_c=10,
            temperature_max_c=22,
            precipitation_mm=0,
            condition="переменная облачность",
            provider="open-meteo",
            day_temperature_min_c=14,
            day_temperature_max_c=22,
            day_condition="переменная облачность",
            night_temperature_min_c=10,
            night_temperature_max_c=15,
            night_condition="ясно",
            tomorrow_date=date(2026, 5, 28),
            tomorrow_temperature_min_c=11,
            tomorrow_temperature_max_c=23,
            tomorrow_condition="дождь",
        )

        text = _format_weather_brief(weather)

        self.assertIn("День: 14...22 °C", text)
        self.assertIn("Ночь: 10...15 °C", text)
        self.assertIn("Завтра: 28.05.2026: 11...23 °C, дождь", text)

    def test_weather_brief_uses_legacy_daily_values_when_day_part_is_missing(self) -> None:
        weather = self.egg_service.eggs.upsert_daily_weather(
            user_id=1,
            weather_date=date(2026, 5, 27),
            city="Курск, Курская область",
            temperature_avg_c=16,
            temperature_min_c=10,
            temperature_max_c=22,
            precipitation_mm=0,
            condition="переменная облачность",
            provider="open-meteo",
        )

        text = _format_weather_brief(weather)

        self.assertIn("День: 10...22 °C, переменная облачность", text)
        self.assertNotIn("День: температура нет данных", text)


if __name__ == "__main__":
    unittest.main()
