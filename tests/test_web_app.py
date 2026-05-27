from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.storage.database import Database
from app.services.feeds import FeedService
from app.services.stock import StockService
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.heartbeats import HeartbeatRepository
from app.storage.repositories.stock import StockRepository
from app.storage.repositories.users import UserRepository
from app.web.config import WebConfig
from app.web.main import create_app


class WebAppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "web.db"
        self.database = Database(self.db_path)
        self.database.initialize()
        self.config = WebConfig(
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
            restart_request_dir=Path(self.temp_dir.name) / "restart-requests",
            link_token="link-token",
        )
        self.client = TestClient(create_app(self.config))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_health_is_public(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_protected_pages_require_token(self) -> None:
        self.assertEqual(self.client.get("/status").status_code, 401)
        self.assertEqual(self.client.get("/version").status_code, 401)
        self.assertEqual(self.client.get("/summary").status_code, 401)
        self.assertEqual(self.client.get("/feeds/data").status_code, 401)
        self.assertEqual(self.client.get("/feeds").status_code, 401)
        self.assertEqual(self.client.get("/eggs/data").status_code, 401)
        self.assertEqual(self.client.get("/eggs").status_code, 401)
        self.assertEqual(self.client.get("/incubation/data").status_code, 401)
        self.assertEqual(self.client.get("/incubation").status_code, 401)
        self.assertEqual(self.client.get("/").status_code, 401)

    def test_protected_pages_accept_bearer_token(self) -> None:
        self._write_ok_heartbeats()

        response = self.client.get("/status", headers=self._auth())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["db"]["status"], "ok")

    def test_regular_pages_accept_link_token_query(self) -> None:
        config = WebConfig(
            **{
                **self.config.__dict__,
                "admin_token": "",
                "link_token": "link-only-token",
            }
        )
        client = TestClient(create_app(config))

        response = client.get("/summary?auth=link-only-token")
        admin_response = client.get("/admin/service-status?auth=link-only-token")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(admin_response.status_code, 503)

    def test_link_token_navigation_keeps_auth_query(self) -> None:
        self._create_household_data()

        index_response = self.client.get("/?auth=link-token")
        feeds_response = self.client.get("/feeds?auth=link-token")
        eggs_response = self.client.get("/eggs?auth=link-token")
        incubation_response = self.client.get("/incubation?auth=link-token")

        self.assertEqual(index_response.status_code, 200)
        self.assertIn("/feeds?auth=link-token", index_response.text)
        self.assertIn("/eggs?auth=link-token", index_response.text)
        self.assertIn("/incubation?auth=link-token", index_response.text)
        self.assertEqual(feeds_response.status_code, 200)
        self.assertIn("/?auth=link-token", feeds_response.text)
        self.assertEqual(eggs_response.status_code, 200)
        self.assertIn("/?auth=link-token", eggs_response.text)
        self.assertEqual(incubation_response.status_code, 200)
        self.assertIn("/?auth=link-token", incubation_response.text)

    def test_service_status_accepts_x_admin_token(self) -> None:
        self._write_ok_heartbeats()

        response = self.client.get("/admin/service-status", headers={"X-Admin-Token": "secret-token"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertIn("bot", payload["services"])
        self.assertIn("worker", payload["services"])

    def test_restart_writes_allowlisted_request(self) -> None:
        response = self.client.post(
            "/admin/restart",
            headers={"X-Admin-Token": "secret-token"},
            json={
                "target": "bot",
                "confirm": "restart:incubator",
                "requested_by": "pytest",
                "reason": "test",
            },
        )
        bad_response = self.client.post(
            "/admin/restart",
            headers={"X-Admin-Token": "secret-token"},
            json={"target": "postgres", "confirm": "restart:incubator"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["target"], "bot")
        self.assertEqual(bad_response.status_code, 400)
        files = list((Path(self.temp_dir.name) / "restart-requests").glob("incubator-*.json"))
        self.assertEqual(len(files), 1)
        self.assertIn('"bot_key": "incubator"', files[0].read_text(encoding="utf-8"))

    def test_version_returns_release_metadata(self) -> None:
        response = self.client.get("/version", headers=self._auth())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["version"], "0.1.3-beta")
        self.assertEqual(payload["commit"], "abc123")
        self.assertEqual(payload["environment"], "test")

    def test_index_returns_html_summary(self) -> None:
        self._write_ok_heartbeats()
        self._create_household_data()

        response = self.client.get("/", headers=self._auth())

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("tg_bot_inkubator", response.text)
        self.assertIn("Хозяйство", response.text)
        self.assertIn("polling_bot", response.text)
        self.assertIn("reminder_runner", response.text)

    def test_summary_returns_household_snapshot(self) -> None:
        self._create_household_data()

        response = self.client.get("/summary", headers=self._auth())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["selected_user_id"], 1)
        self.assertEqual(payload["eggs"]["today_eggs"], 7)
        self.assertEqual(payload["eggs"]["total_hens"], 12)
        self.assertGreater(payload["feeds"]["ready_mix"]["remaining_kg"], 0)
        self.assertEqual(payload["feeds"]["bird_groups"]["hens"], 12)
        self.assertEqual(payload["incubation"]["active_batches"], 1)

    def test_feeds_data_and_page_return_stock_snapshot(self) -> None:
        self._create_household_data()

        data_response = self.client.get("/feeds/data", headers=self._auth())
        page_response = self.client.get("/feeds", headers=self._auth())

        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        self.assertEqual(payload["selected_user_id"], 1)
        self.assertTrue(payload["feeds"]["stock_items"])
        self.assertTrue(payload["history"])
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Корма и склад", page_response.text)
        self.assertIn("Смесь для кур", page_response.text)

    def test_eggs_data_and_page_return_egg_snapshot(self) -> None:
        self._create_household_data()

        data_response = self.client.get("/eggs/data", headers=self._auth())
        page_response = self.client.get("/eggs", headers=self._auth())

        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        self.assertEqual(payload["selected_user_id"], 1)
        self.assertEqual(payload["eggs"]["today_eggs"], 7)
        self.assertTrue(payload["history"])
        self.assertTrue(payload["open_exclusions"])
        self.assertEqual(payload["eggs"]["weather"]["city"], "Курск")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Яйца", page_response.text)
        self.assertIn("наседка сидит на яйцах", page_response.text)

    def test_incubation_data_and_page_return_batch_snapshot(self) -> None:
        self._create_household_data()

        data_response = self.client.get("/incubation/data", headers=self._auth())
        page_response = self.client.get("/incubation", headers=self._auth())

        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        self.assertEqual(payload["selected_user_id"], 1)
        self.assertEqual(payload["incubation"]["active_batches"], 1)
        self.assertEqual(payload["incubation"]["completed_batches"], 1)
        self.assertTrue(payload["active_batches"])
        self.assertTrue(payload["completed_batches"])
        self.assertTrue(payload["active_batches"][0]["recommendations"])
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Инкубация", page_response.text)
        self.assertIn("Куриные яйца", page_response.text)

    def test_summary_does_not_create_default_weather_settings(self) -> None:
        UserRepository(self.database).upsert(user_id=1, first_name="Admin")
        before = self._row_counts()

        response = self.client.get("/summary", headers=self._auth())
        after = self._row_counts()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(after, before)

    def test_summary_does_not_create_missing_database(self) -> None:
        missing_path = Path(self.temp_dir.name) / "missing.db"
        config = WebConfig(
            **{
                **self.config.__dict__,
                "db_path": missing_path,
            }
        )
        client = TestClient(create_app(config))

        response = client.get("/summary", headers=self._auth())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["db"]["status"], "error")
        self.assertFalse(missing_path.exists())

    def test_status_does_not_create_database_rows(self) -> None:
        self._write_ok_heartbeats()
        before = self._row_counts()

        response = self.client.get("/status", headers=self._auth())
        after = self._row_counts()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(after, before)

    def test_missing_admin_token_disables_protected_pages(self) -> None:
        config = WebConfig(
            **{
                **self.config.__dict__,
                "admin_token": "",
                "link_token": "",
            }
        )
        client = TestClient(create_app(config))

        response = client.get("/status")

        self.assertEqual(response.status_code, 503)

    def _write_ok_heartbeats(self) -> None:
        now = datetime.now(timezone.utc)
        started_at = now - timedelta(minutes=5)
        heartbeats = HeartbeatRepository(self.database)
        heartbeats.upsert(
            service_name="polling_bot",
            status="ok",
            version="0.1.3-beta",
            started_at=started_at,
            last_seen_at=now,
            metadata={"environment": "test", "handlers_registered": True},
        )
        heartbeats.upsert(
            service_name="reminder_runner",
            status="ok",
            version="0.1.3-beta",
            started_at=started_at,
            last_seen_at=now,
            metadata={"interval_seconds": 60, "timezone": "Europe/Moscow"},
        )

    def _row_counts(self) -> dict[str, int]:
        with self.database.connect() as connection:
            return {
                "service_heartbeats": int(
                    connection.execute("SELECT COUNT(*) FROM service_heartbeats").fetchone()[0]
                ),
                "users": int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]),
                "critical_errors": int(
                    connection.execute("SELECT COUNT(*) FROM critical_errors").fetchone()[0]
                ),
                "weather_settings": int(
                    connection.execute("SELECT COUNT(*) FROM weather_settings").fetchone()[0]
                ),
                "daily_weather": int(
                    connection.execute("SELECT COUNT(*) FROM daily_weather").fetchone()[0]
                ),
            }

    def _auth(self) -> dict[str, str]:
        return {"Authorization": "Bearer secret-token"}

    def _create_household_data(self) -> None:
        today = datetime.now(timezone.utc).date()
        UserRepository(self.database).upsert(user_id=1, first_name="Admin")
        feeds = FeedRepository(self.database)
        feed_service = FeedService(feeds)
        hens = feed_service.create_bird_group(
            user_id=1,
            name="Несушки",
            bird_count=12,
            species="chicken",
            role="hens",
        )
        flock = feed_service.create_flock(user_id=1, name="Основное стадо", member_group_ids=[hens.id])
        stock_service = StockService(StockRepository(self.database), feeds)
        mix = stock_service.add_purchase(
            user_id=1,
            name="Смесь для кур",
            kind="finished_mix",
            amount_kg=40,
        )
        stock_service.assign_flock_feed(
            user_id=1,
            flock_id=flock.id,
            stock_item_id=mix.item.id,
        )
        eggs = EggRepository(self.database)
        eggs.create_entry(
            user_id=1,
            entry_date=today,
            eggs_count=7,
            active_hens_count=12,
            total_hens_count=12,
            excluded_hens_count=0,
        )
        eggs.create_entry(
            user_id=1,
            entry_date=today - timedelta(days=1),
            eggs_count=6,
            active_hens_count=11,
            total_hens_count=12,
            excluded_hens_count=1,
        )
        eggs.create_exclusion(
            user_id=1,
            hens_count=1,
            reason="broody",
            started_at=today,
            expected_until=today + timedelta(days=14),
        )
        eggs.upsert_daily_weather(
            user_id=1,
            weather_date=today,
            city="Курск",
            temperature_avg_c=12,
            temperature_min_c=8,
            temperature_max_c=17,
            precipitation_mm=1.5,
            condition="дождь",
            provider="test",
            day_temperature_min_c=11,
            day_temperature_max_c=17,
            day_condition="дождь",
            night_temperature_min_c=8,
            night_temperature_max_c=13,
            night_condition="облачно",
            tomorrow_date=today + timedelta(days=1),
            tomorrow_temperature_min_c=9,
            tomorrow_temperature_max_c=18,
            tomorrow_condition="облачно",
        )
        batches = BatchRepository(self.database)
        batches.create(
            user_id=1,
            species="chicken",
            eggs_count=10,
            start_date=today,
            title="Куриные яйца",
        )
        completed = batches.create(
            user_id=1,
            species="chicken",
            eggs_count=9,
            start_date=today - timedelta(days=24),
            title="Прошлый вывод",
        )
        batches.complete(
            batch_id=completed.id,
            user_id=1,
            hatched_count=7,
            completed_at=today - timedelta(days=3),
        )


if __name__ == "__main__":
    unittest.main()
