from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

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
            link_token="link-token",
            release_notes="Добавлена web-страница смеси; Добавлен экран о боте",
            release_importance="minor",
            release_notice_enabled=False,
            admin_startup_notice_mode="once_per_deploy",
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
        self.assertEqual(self.client.get("/mix/data").status_code, 401)
        self.assertEqual(self.client.get("/mix").status_code, 401)
        self.assertEqual(self.client.get("/mix/confirm").status_code, 401)
        self.assertEqual(self.client.get("/livestock/data").status_code, 401)
        self.assertEqual(self.client.get("/livestock").status_code, 401)
        self.assertEqual(self.client.get("/eggs/data").status_code, 401)
        self.assertEqual(self.client.get("/eggs").status_code, 401)
        self.assertEqual(self.client.get("/incubation/data").status_code, 401)
        self.assertEqual(self.client.get("/incubation").status_code, 401)
        self.assertEqual(self.client.get("/about/data").status_code, 401)
        self.assertEqual(self.client.get("/about").status_code, 401)
        self.assertEqual(self.client.get("/").status_code, 401)
        self.assertEqual(
            self.client.post("/eggs/entries", data={"eggs_count": "1"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/stock/purchases", data={"name": "Премикс", "amount": "1 кг"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/feeds/mixes", data={"mix_count": "1"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/bird-groups", data={"name": "Несушки", "bird_count": "1"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/flocks", data={"name": "Основное стадо"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.patch("/bird-groups/1", data={"name": "Несушки", "bird_count": "1"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.patch("/flocks/1", data={"name": "Основное стадо"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/flock-feed-assignments", data={"flock_id": "1"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/settings/weather", data={"city": "Курск"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.patch("/settings/sections", data={"sections": "feeds"}).status_code,
            401,
        )

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

        self.assertEqual(response.status_code, 200)

    def test_link_token_navigation_keeps_auth_query(self) -> None:
        self._create_household_data()

        index_response = self.client.get("/?auth=link-token")
        feeds_response = self.client.get("/feeds?auth=link-token")
        mix_response = self.client.get("/mix?auth=link-token")
        livestock_response = self.client.get("/livestock?auth=link-token")
        eggs_response = self.client.get("/eggs?auth=link-token")
        incubation_response = self.client.get("/incubation?auth=link-token")
        about_response = self.client.get("/about?auth=link-token")

        self.assertEqual(index_response.status_code, 200)
        self.assertIn('aria-label="Основные разделы"', index_response.text)
        self.assertIn("/feeds?auth=link-token", index_response.text)
        self.assertIn("/mix?auth=link-token", index_response.text)
        self.assertIn("/livestock?auth=link-token", index_response.text)
        self.assertIn("/eggs?auth=link-token", index_response.text)
        self.assertIn("/incubation?auth=link-token", index_response.text)
        self.assertIn("/about?auth=link-token", index_response.text)
        self.assertEqual(feeds_response.status_code, 200)
        self.assertIn('aria-current="page"', feeds_response.text)
        self.assertIn("/?auth=link-token", feeds_response.text)
        self.assertEqual(mix_response.status_code, 200)
        self.assertIn('aria-current="page"', mix_response.text)
        self.assertIn("/?auth=link-token", mix_response.text)
        self.assertEqual(livestock_response.status_code, 200)
        self.assertIn('aria-current="page"', livestock_response.text)
        self.assertIn("/?auth=link-token", livestock_response.text)
        self.assertEqual(eggs_response.status_code, 200)
        self.assertIn('aria-current="page"', eggs_response.text)
        self.assertIn("/?auth=link-token", eggs_response.text)
        self.assertEqual(incubation_response.status_code, 200)
        self.assertIn('aria-current="page"', incubation_response.text)
        self.assertIn("/?auth=link-token", incubation_response.text)
        self.assertEqual(about_response.status_code, 200)
        self.assertIn('aria-current="page"', about_response.text)
        self.assertIn("/?auth=link-token", about_response.text)

    def test_version_returns_release_metadata(self) -> None:
        response = self.client.get("/version", headers=self._auth())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["version"], "0.1.3-beta")
        self.assertEqual(payload["commit"], "abc123")
        self.assertEqual(payload["environment"], "test")
        self.assertEqual(payload["release_importance"], "minor")
        self.assertEqual(payload["release_notes"], ["Добавлена web-страница смеси", "Добавлен экран о боте"])

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
        self.assertIn("Добавить покупку", page_response.text)
        self.assertIn("Смесь для кур", page_response.text)

    def test_stock_purchase_can_be_created_from_web_form(self) -> None:
        self._create_household_data()

        post_response = self.client.post(
            "/stock/purchases?auth=link-token",
            data={
                "user_id": "1",
                "name": "Премикс web",
                "kind": "ingredient",
                "amount": "2 пачки 500 гр",
                "note": "web покупка",
            },
            follow_redirects=False,
        )
        data_response = self.client.get("/feeds/data", headers=self._auth())
        page_response = self.client.get(post_response.headers["location"], headers=self._auth())

        self.assertEqual(post_response.status_code, 303)
        self.assertIn("/feeds?auth=link-token", post_response.headers["location"])
        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        stock_item = next(
            item for item in payload["feeds"]["stock_items"] if item["name"] == "Премикс web"
        )
        self.assertEqual(stock_item["remaining_kg"], 1.0)
        self.assertEqual(payload["history"][0]["item_name"], "Премикс web")
        self.assertEqual(payload["history"][0]["note"], "web покупка")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Покупка добавлена", page_response.text)

    def test_mix_data_and_page_return_recipe_and_history(self) -> None:
        self._create_household_data()

        data_response = self.client.get("/mix/data", headers=self._auth())
        page_response = self.client.get("/mix", headers=self._auth())

        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        self.assertEqual(payload["selected_user_id"], 1)
        self.assertEqual(payload["mix"]["grain_base_label"], "Зерносмесь")
        self.assertGreater(payload["mix"]["possible_mix_count"], 0)
        self.assertTrue(payload["mix"]["ingredients"])
        self.assertTrue(payload["mix"]["grain_base_options"])
        self.assertTrue(payload["history"])
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Формула одного замеса", page_response.text)
        self.assertIn("Создать замес", page_response.text)
        self.assertIn("Зерновая смесь для кур несушек", page_response.text)

    def test_mix_can_be_confirmed_and_created_from_web_form(self) -> None:
        self._create_household_data()

        confirm_response = self.client.get(
            "/mix/confirm?auth=link-token&user_id=1&mix_count=1&grain_base=layer_grain_mix"
        )
        post_response = self.client.post(
            "/feeds/mixes?auth=link-token",
            data={
                "user_id": "1",
                "mix_count": "1",
                "grain_base": "layer_grain_mix",
            },
            follow_redirects=False,
        )
        data_response = self.client.get("/mix/data", headers=self._auth())
        page_response = self.client.get(post_response.headers["location"], headers=self._auth())

        self.assertEqual(confirm_response.status_code, 200)
        self.assertIn("Подтверждение замеса", confirm_response.text)
        self.assertIn("Создать замес и обновить склад", confirm_response.text)
        self.assertEqual(post_response.status_code, 303)
        self.assertIn("/mix?auth=link-token", post_response.headers["location"])
        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        self.assertTrue(payload["history"])
        self.assertIsNotNone(payload["history"][0]["mix_id"])
        self.assertGreater(payload["history"][0]["amount_kg"], 0)
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Замес создан", page_response.text)

    def test_livestock_data_and_page_return_groups_and_flocks(self) -> None:
        self._create_household_data()

        data_response = self.client.get("/livestock/data", headers=self._auth())
        page_response = self.client.get("/livestock", headers=self._auth())

        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        self.assertEqual(payload["selected_user_id"], 1)
        self.assertTrue(payload["bird_groups"])
        self.assertTrue(payload["flocks"])
        self.assertEqual(payload["bird_groups"][0]["role"], "hens")
        self.assertTrue(payload["flocks"][0]["members"])
        self.assertTrue(payload["flocks"][0]["assignments"])
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Поголовье и стада", page_response.text)
        self.assertIn("Добавить поголовье", page_response.text)
        self.assertIn("Создать стадо", page_response.text)
        self.assertIn("Основное стадо", page_response.text)

    def test_bird_group_can_be_created_from_web_form(self) -> None:
        self._create_household_data()
        today = datetime.now(ZoneInfo("Europe/Moscow")).date()

        post_response = self.client.post(
            "/bird-groups?auth=link-token",
            data={
                "user_id": "1",
                "name": "Цыплята май",
                "bird_count": "11",
                "species": "chicken",
                "group_kind": "chicks",
                "role": "chicks",
                "hatched_at": today.isoformat(),
                "joined_at": "",
                "reserve_percent": "10",
            },
            follow_redirects=False,
        )
        data_response = self.client.get("/livestock/data", headers=self._auth())
        page_response = self.client.get(post_response.headers["location"], headers=self._auth())

        self.assertEqual(post_response.status_code, 303)
        self.assertIn("/livestock?auth=link-token", post_response.headers["location"])
        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        created = next(
            item for item in payload["bird_groups"] if item["name"] == "Цыплята май"
        )
        self.assertEqual(created["bird_count"], 11)
        self.assertEqual(created["group_kind"], "chicks")
        self.assertEqual(created["role"], "chicks")
        self.assertEqual(created["reserve_percent"], 10)
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Поголовье добавлено", page_response.text)

    def test_bird_group_can_be_updated_from_web_form(self) -> None:
        self._create_household_data()
        data_before = self.client.get("/livestock/data", headers=self._auth()).json()
        group_id = data_before["bird_groups"][0]["id"]

        post_response = self.client.patch(
            f"/bird-groups/{group_id}?auth=link-token",
            data={
                "user_id": "1",
                "name": "Несушки обновлено",
                "bird_count": "13",
                "role": "hens",
                "hatched_at": "",
                "joined_at": "",
                "reserve_percent": "0",
            },
            follow_redirects=False,
        )
        data_response = self.client.get("/livestock/data", headers=self._auth())
        page_response = self.client.get(post_response.headers["location"], headers=self._auth())

        self.assertEqual(post_response.status_code, 303)
        payload = data_response.json()
        updated = next(item for item in payload["bird_groups"] if item["id"] == group_id)
        self.assertEqual(updated["name"], "Несушки обновлено")
        self.assertEqual(updated["bird_count"], 13)
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Поголовье обновлено", page_response.text)

    def test_flock_can_be_created_from_web_form(self) -> None:
        self._create_household_data()
        data_before = self.client.get("/livestock/data", headers=self._auth()).json()
        group_id = data_before["bird_groups"][0]["id"]

        post_response = self.client.post(
            "/flocks?auth=link-token",
            data={
                "user_id": "1",
                "name": "Молодняк",
                "member_group_ids": str(group_id),
            },
            follow_redirects=False,
        )
        data_response = self.client.get("/livestock/data", headers=self._auth())
        page_response = self.client.get(post_response.headers["location"], headers=self._auth())

        self.assertEqual(post_response.status_code, 303)
        self.assertIn("/livestock?auth=link-token", post_response.headers["location"])
        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        created = next(item for item in payload["flocks"] if item["name"] == "Молодняк")
        self.assertEqual(created["members_count"], 1)
        self.assertEqual(created["members"][0]["bird_group_id"], group_id)
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Стадо создано", page_response.text)

    def test_flock_can_be_updated_from_web_form(self) -> None:
        self._create_household_data()
        data_before = self.client.get("/livestock/data", headers=self._auth()).json()
        flock_id = data_before["flocks"][0]["id"]
        group_id = data_before["bird_groups"][0]["id"]

        post_response = self.client.patch(
            f"/flocks/{flock_id}?auth=link-token",
            data={
                "user_id": "1",
                "name": "Стадо web",
                "member_group_ids": str(group_id),
            },
            follow_redirects=False,
        )
        data_response = self.client.get("/livestock/data", headers=self._auth())
        page_response = self.client.get(post_response.headers["location"], headers=self._auth())

        self.assertEqual(post_response.status_code, 303)
        payload = data_response.json()
        updated = next(item for item in payload["flocks"] if item["id"] == flock_id)
        self.assertEqual(updated["name"], "Стадо web")
        self.assertEqual(updated["members"][0]["bird_group_id"], group_id)
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Стадо обновлено", page_response.text)

    def test_flock_feed_can_be_assigned_from_web_form(self) -> None:
        self._create_household_data()
        data_before = self.client.get("/livestock/data", headers=self._auth()).json()
        flock_id = data_before["flocks"][0]["id"]
        mix_id = next(
            item["id"]
            for item in data_before["feeds"]["stock_items"]
            if item["kind"] == "finished_mix"
        )

        post_response = self.client.post(
            "/flock-feed-assignments?auth=link-token",
            data={
                "user_id": "1",
                "flock_id": str(flock_id),
                "stock_item_id": str(mix_id),
            },
            follow_redirects=False,
        )
        page_response = self.client.get(post_response.headers["location"], headers=self._auth())

        self.assertEqual(post_response.status_code, 303)
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Смесь назначена стаду", page_response.text)

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
        self.assertIn("Добавить сбор", page_response.text)
        self.assertIn("наседка сидит на яйцах", page_response.text)

    def test_egg_entry_can_be_created_from_web_form(self) -> None:
        self._create_household_data()

        post_response = self.client.post(
            "/eggs/entries?auth=link-token",
            data={
                "user_id": "1",
                "entry_day": "today",
                "eggs_count": "4",
                "note": "вечерний сбор",
            },
            follow_redirects=False,
        )
        data_response = self.client.get("/eggs/data", headers=self._auth())
        page_response = self.client.get(post_response.headers["location"], headers=self._auth())

        self.assertEqual(post_response.status_code, 303)
        self.assertIn("/eggs?auth=link-token", post_response.headers["location"])
        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        self.assertEqual(payload["eggs"]["today_eggs"], 11)
        self.assertEqual(payload["history"][0]["eggs_count"], 4)
        self.assertEqual(payload["history"][0]["note"], "вечерний сбор")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Запись добавлена", page_response.text)

    def test_weather_city_can_be_updated_from_web_form(self) -> None:
        self._create_household_data()

        post_response = self.client.post(
            "/settings/weather?auth=link-token",
            data={"user_id": "1", "city": "Яценовская"},
            follow_redirects=False,
        )
        settings = EggRepository(self.database).get_weather_settings(1)
        page_response = self.client.get(post_response.headers["location"], headers=self._auth())

        self.assertEqual(post_response.status_code, 303)
        self.assertEqual(settings.city, "Яценовская")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Город погоды обновлен", page_response.text)

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

    def test_about_data_and_page_return_release_settings_and_runtime(self) -> None:
        self._write_ok_heartbeats()
        self._create_household_data()

        data_response = self.client.get("/about/data", headers=self._auth())
        page_response = self.client.get("/about", headers=self._auth())

        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        self.assertEqual(payload["selected_user_id"], 1)
        self.assertEqual(payload["release"]["version"], "0.1.3-beta")
        self.assertEqual(payload["release"]["user_release_messages"], "off")
        self.assertEqual(payload["settings"]["timezone"], "Europe/Moscow")
        self.assertEqual(payload["runtime"]["status"], "ok")
        self.assertTrue(payload["runtime"]["heartbeats"])
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("О боте", page_response.text)
        self.assertIn("Добавлена web-страница смеси", page_response.text)
        self.assertIn("GitHub", page_response.text)

    def test_sections_can_be_updated_from_web_form(self) -> None:
        self._write_ok_heartbeats()
        self._create_household_data()

        post_response = self.client.patch(
            "/settings/sections?auth=link-token",
            data={
                "user_id": "1",
                "sections": ["feeds", "eggs"],
            },
            follow_redirects=False,
        )
        settings = UserRepository(self.database).get_settings(1)
        page_response = self.client.get(post_response.headers["location"], headers=self._auth())

        self.assertEqual(post_response.status_code, 303)
        self.assertFalse(settings["notify_incubation"])
        self.assertTrue(settings["notify_feed"])
        self.assertTrue(settings["notify_eggs"])
        self.assertFalse(settings["notify_post_hatch_care"])
        self.assertFalse(settings["notify_service"])
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Разделы Telegram-бота обновлены", page_response.text)

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
        today = datetime.now(ZoneInfo("Europe/Moscow")).date()
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
        stock_service.add_purchase(
            user_id=1,
            name="Кукуруза дроблёная",
            kind="ingredient",
            amount_kg=60,
        )
        stock_service.add_purchase(
            user_id=1,
            name="Зерносмесь для кур несушек",
            kind="ingredient",
            amount_kg=40,
        )
        stock_service.add_purchase(
            user_id=1,
            name="Ячмень",
            kind="ingredient",
            amount_kg=40,
        )
        stock_service.add_purchase(
            user_id=1,
            name="Комбикорм Щигровский",
            kind="ingredient",
            amount_kg=25,
        )
        stock_service.add_purchase(
            user_id=1,
            name="Мясокостная мука",
            kind="ingredient",
            amount_kg=5,
        )
        stock_service.add_purchase(
            user_id=1,
            name="Рыбная мука",
            kind="ingredient",
            amount_kg=5,
        )
        stock_service.add_purchase(
            user_id=1,
            name="Ракушка дроблёная мелкая",
            kind="ingredient",
            amount_kg=10,
        )
        stock_service.add_purchase(
            user_id=1,
            name="Премикс",
            kind="ingredient",
            amount_kg=3,
        )
        stock_service.produce_mix(user_id=1, mix_count=1, grain_base="layer_grain_mix")
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
