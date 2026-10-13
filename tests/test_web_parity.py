"""Web features that mirror the bot: the site must allow everything the bot does."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.services.stock import StockService
from app.storage.database import Database
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.stock import StockRepository
from app.storage.repositories.users import UserRepository
from app.utils.dates import local_today
from app.web.config import WebConfig
from app.web.main import create_app


AUTH = "?auth=link-token"


class WebParityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "web.db"
        self.database = Database(self.db_path)
        self.database.initialize()
        config = WebConfig(
            enabled=True,
            host="127.0.0.1",
            port=8080,
            admin_token="secret-token",
            db_path=self.db_path,
            environment="test",
            release_version="0.1.3-beta",
            release_channel="beta",
            release_deployed_at="2026-05-27T12:00:00Z",
            release_commit="abc123",
            github_url="https://github.com/example/project",
            changelog_url="https://github.com/example/project/blob/main/docs/CHANGELOG.md",
            link_token="link-token",
        )
        self.client = TestClient(create_app(config))
        self.users = UserRepository(self.database)
        self.users.upsert(user_id=1, first_name="Admin")
        self.feeds = FeedService(FeedRepository(self.database))
        self.hens = self.feeds.create_bird_group(
            user_id=1, name="Несушки", bird_count=10, species="chicken", role="hens"
        )
        self.today = local_today()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _post(self, path: str, data: dict):
        payload = {"user_id": "1", **data}
        return self.client.post(f"{path}{AUTH}", data=payload, follow_redirects=False)

    def test_navigation_has_advisor_faq_and_settings(self) -> None:
        page = self.client.get(f"/{AUTH}").text

        self.assertIn("Птицевод", page)
        self.assertIn("FAQ", page)
        self.assertIn("Настройки и о боте", page)

    def test_hen_exclusion_can_be_created_and_finished(self) -> None:
        response = self._post(
            "/eggs/exclusions",
            {"hens_count": "2", "reason": "broody", "started_at": self.today.isoformat()},
        )
        exclusions = EggRepository(self.database).list_open_exclusions(1)

        self.assertEqual(response.status_code, 303)
        self.assertEqual([item.hens_count for item in exclusions], [2])
        self.assertIn("Снова несутся", self.client.get(f"/eggs{AUTH}").text)

        self._post(f"/eggs/exclusions/{exclusions[0].id}/finish", {})

        self.assertEqual(EggRepository(self.database).list_open_exclusions(1), [])

    def test_multi_day_collection_preview_then_record(self) -> None:
        query = {
            "user_id": "1",
            "total_eggs": "9",
            "collection_date": self.today.isoformat(),
            "mode": "manual",
            "days": "3",
        }
        preview = self.client.get("/eggs/multi-day", params={**query, "auth": "link-token"})
        before = EggRepository(self.database).list_entries(1, limit=50)

        self.assertEqual(preview.status_code, 200)
        self.assertIn("Проверьте раскладку", preview.text)
        self.assertEqual(before, [])

        response = self._post("/eggs/multi-day", {k: v for k, v in query.items() if k != "user_id"})
        entries = EggRepository(self.database).list_entries(1, limit=50)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(sum(entry.eggs_count for entry in entries), 9)
        self.assertEqual(len({entry.entry_date for entry in entries}), 3)

    def test_already_fed_mix_does_not_increase_finished_mix(self) -> None:
        stock = StockService(StockRepository(self.database), FeedRepository(self.database))
        stock.add_purchase(user_id=1, name="Кукуруза", kind="ingredient", amount_kg=20)

        response = self._post(
            "/feeds/mixes/already-fed",
            {
                "mix_count": "1",
                "grain_base": "wheat",
                "fed_date": (self.today - timedelta(days=3)).isoformat(),
                "request_id": "fed-1",
            },
        )
        repeat = self._post(
            "/feeds/mixes/already-fed",
            {"mix_count": "1", "grain_base": "wheat", "request_id": "fed-1"},
        )
        finished = [
            estimate
            for estimate in stock.list_estimates(1)
            if estimate.item.kind == "finished_mix"
        ]
        corn = next(e for e in stock.list_estimates(1) if e.item.name == "Кукуруза")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(repeat.status_code, 303)
        self.assertEqual(round(finished[0].remaining_kg, 3), 0)
        # 3.5 parts * 0.72 kg = 2.52 kg of corn written off once, not twice.
        self.assertAlmostEqual(corn.remaining_kg, 20 - 2.52, places=2)

    def test_bird_group_and_flock_can_be_archived(self) -> None:
        flock = self.feeds.create_flock(user_id=1, name="Стадо", member_group_ids=[self.hens.id])

        not_confirmed = self._post(f"/flocks/{flock.id}/archive", {})
        self.assertTrue(self.feeds.get_flock(flock.id, 1).is_active)
        self.assertEqual(not_confirmed.status_code, 303)

        self._post(f"/flocks/{flock.id}/archive", {"confirm_archive": "yes"})
        self._post(f"/bird-groups/{self.hens.id}/archive", {"confirm_archive": "yes"})

        self.assertFalse(self.feeds.get_flock(flock.id, 1).is_active)
        self.assertFalse(self.feeds.get_bird_group(self.hens.id, 1).is_active)

    def test_incubation_batch_can_be_edited(self) -> None:
        service = IncubationService(BatchRepository(self.database))
        batch = service.create_batch(
            user_id=1, species="chicken", eggs_count=10, start_date=self.today
        )

        self._post(
            f"/incubation/batches/{batch.id}/edit",
            {
                "species": "duck",
                "eggs_count": "12",
                "start_date": (self.today - timedelta(days=2)).isoformat(),
                "title": "Утки",
                "note": "вторая закладка",
            },
        )
        updated = service.get_batch(batch.id, 1)

        self.assertEqual(updated.species, "duck")
        self.assertEqual(updated.eggs_count, 12)
        self.assertEqual(updated.title, "Утки")
        self.assertIn("Сохранить партию", self.client.get(f"/incubation{AUTH}").text)

    def test_batch_edit_rejects_year_typo(self) -> None:
        service = IncubationService(BatchRepository(self.database))
        batch = service.create_batch(user_id=1, species="chicken", eggs_count=10, start_date=self.today)

        response = self._post(
            f"/incubation/batches/{batch.id}/edit",
            {"species": "chicken", "eggs_count": "10", "start_date": date(2016, 1, 1).isoformat()},
        )

        self.assertIn("error=", response.headers["location"])
        self.assertEqual(service.get_batch(batch.id, 1).start_date, self.today)

    def test_farm_settings_can_be_saved(self) -> None:
        response = self._post(
            "/settings/profile",
            {"farm_name": "Ферма & Ко", "notification_time": "07:30", "timezone": "Europe/Samara"},
        )
        settings = self.users.get_settings(1)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(settings["farm_name"], "Ферма & Ко")
        self.assertEqual(settings["notification_time"], "07:30")
        self.assertEqual(settings["timezone"], "Europe/Samara")

        bad = self._post(
            "/settings/profile",
            {"farm_name": "x", "notification_time": "25:00", "timezone": "Europe/Moscow"},
        )
        self.assertIn("error=", bad.headers["location"])

    def test_advisor_and_faq_pages_render(self) -> None:
        advisor = self.client.get(f"/advisor{AUTH}")
        faq = self.client.get(f"/help{AUTH}&topic=eggs")

        self.assertEqual(advisor.status_code, 200)
        self.assertIn("План на сегодня", advisor.text)
        self.assertIn("Мало яиц", advisor.text)
        self.assertEqual(faq.status_code, 200)
        self.assertIn("FAQ", faq.text)

    def test_group_ration_can_be_assigned(self) -> None:
        stock = StockService(StockRepository(self.database), FeedRepository(self.database))
        item = stock.add_purchase(user_id=1, name="Комбикорм", kind="commercial_feed", amount_kg=25).item

        page = self.client.get(f"/livestock{AUTH}").text
        response = self._post(
            "/feeding-assignments",
            {"bird_group_id": str(self.hens.id), "stock_item_id": str(item.id), "daily_per_bird_g": "110"},
        )

        self.assertIn("Назначить рацион", page)
        self.assertEqual(response.status_code, 303)
        # 10 hens * 110 g = 1.1 kg per day, the same number the bot shows.
        self.assertAlmostEqual(stock.estimate_item(item).daily_usage_kg, 1.1, places=3)

    def test_incubation_page_has_calendar_and_care_reference(self) -> None:
        page = self.client.get(f"/incubation{AUTH}").text

        self.assertIn("Справочник: календарь и уход после вывода", page)
        self.assertIn("Уход после вывода", page)

    def test_new_pages_require_token(self) -> None:
        self.assertEqual(self.client.get("/advisor").status_code, 401)
        self.assertEqual(self.client.get("/help").status_code, 401)
        self.assertEqual(self.client.post("/eggs/exclusions", data={}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
