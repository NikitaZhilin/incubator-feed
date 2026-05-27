from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.storage.database import Database
from app.storage.repositories.heartbeats import HeartbeatRepository
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
        self.assertEqual(self.client.get("/").status_code, 401)

    def test_protected_pages_accept_bearer_token(self) -> None:
        self._write_ok_heartbeats()

        response = self.client.get("/status", headers=self._auth())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["db"]["status"], "ok")

    def test_version_returns_release_metadata(self) -> None:
        response = self.client.get("/version", headers=self._auth())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["version"], "0.1.3-beta")
        self.assertEqual(payload["commit"], "abc123")
        self.assertEqual(payload["environment"], "test")

    def test_index_returns_html_summary(self) -> None:
        self._write_ok_heartbeats()

        response = self.client.get("/", headers=self._auth())

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("tg_bot_inkubator", response.text)
        self.assertIn("polling_bot", response.text)
        self.assertIn("reminder_runner", response.text)

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
            }

    def _auth(self) -> dict[str, str]:
        return {"Authorization": "Bearer secret-token"}


if __name__ == "__main__":
    unittest.main()
