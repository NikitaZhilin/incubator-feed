from datetime import date
from pathlib import Path
import tempfile
import unittest

from app.services.eggs import EggService
from app.services.feeds import FeedService
from app.services.weather import GeocodedLocation, WeatherDay
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
        self.assertEqual(stats.next_week_forecast, 7)
        self.assertEqual(round(stats.eggs_per_active_hen, 2), 0.1)

    def test_history_returns_zero_days_without_entries(self) -> None:
        rows = self.egg_service.history(1, days=3, today=date(2026, 5, 26))

        self.assertEqual(rows, [(date(2026, 5, 26), 0), (date(2026, 5, 25), 0), (date(2026, 5, 24), 0)])

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
        for _ in range(7):
            service.record_today(1, 10, today=date(2026, 5, 26))

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


if __name__ == "__main__":
    unittest.main()
