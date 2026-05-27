from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from app.services.status_probe import build_status_report, status_exit_code
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.heartbeats import HeartbeatRepository


class StatusProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.database = Database(self.db_path)
        self.database.initialize()
        self.heartbeats = HeartbeatRepository(self.database)
        self.now = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
        self.started_at = self.now - timedelta(hours=1)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fresh_required_heartbeats_are_ok(self) -> None:
        self._write_ok("polling_bot")
        self._write_ok("reminder_runner")

        report = build_status_report(self.db_path, now=self.now)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(status_exit_code(report), 0)
        self.assertEqual(len(report["heartbeats"]), 2)
        self.assertFalse(any(item["stale"] for item in report["heartbeats"]))

    def test_missing_required_heartbeat_is_down(self) -> None:
        self._write_ok("polling_bot")

        report = build_status_report(self.db_path, now=self.now)

        self.assertEqual(report["status"], "down")
        self.assertEqual(status_exit_code(report), 1)
        reminder = _heartbeat(report, "reminder_runner")
        self.assertTrue(reminder["stale"])
        self.assertEqual(reminder["status"], "down")

    def test_stale_heartbeat_is_down(self) -> None:
        self._write_ok("polling_bot", last_seen_at=self.now - timedelta(minutes=3))
        self._write_ok("reminder_runner")

        report = build_status_report(self.db_path, now=self.now)

        self.assertEqual(report["status"], "down")
        self.assertTrue(_heartbeat(report, "polling_bot")["stale"])

    def test_reminder_last_error_is_degraded(self) -> None:
        self._write_ok("polling_bot")
        self.heartbeats.upsert(
            service_name="reminder_runner",
            status="degraded",
            version="0.1.3-beta",
            started_at=self.started_at,
            last_seen_at=self.now - timedelta(seconds=10),
            last_error="Reminder loop failed",
            metadata={"interval_seconds": 60, "timezone": "Europe/Moscow"},
        )

        report = build_status_report(self.db_path, now=self.now)

        self.assertEqual(report["status"], "degraded")
        self.assertEqual(status_exit_code(report), 1)
        self.assertEqual(_heartbeat(report, "reminder_runner")["last_error"], "Reminder loop failed")

    def test_critical_errors_make_report_degraded(self) -> None:
        self._write_ok("polling_bot")
        self._write_ok("reminder_runner")
        AnalyticsRepository(self.database).log_critical("polling", "boom")

        report = build_status_report(self.db_path, now=self.now)

        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["errors"]["critical_total"], 1)

    def test_unavailable_database_returns_probe_error_exit_code(self) -> None:
        report = build_status_report(Path(self.temp_dir.name) / "missing.db", now=self.now)

        self.assertEqual(report["db"]["status"], "error")
        self.assertEqual(status_exit_code(report), 2)

    def test_status_probe_script_prints_valid_json(self) -> None:
        now = datetime.now(timezone.utc)
        self._write_ok("polling_bot", last_seen_at=now - timedelta(seconds=10))
        self._write_ok("reminder_runner", last_seen_at=now - timedelta(seconds=10))
        env = {
            **os.environ,
            "ENVIRONMENT": "prod",
            "DATABASE_PATH": str(self.db_path),
        }

        result = subprocess.run(
            [sys.executable, "-B", "scripts/status_probe.py"],
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["db"]["status"], "ok")

    def _write_ok(self, service_name: str, *, last_seen_at: datetime | None = None) -> None:
        metadata = (
            {"environment": "test", "handlers_registered": True}
            if service_name == "polling_bot"
            else {"interval_seconds": 60, "timezone": "Europe/Moscow"}
        )
        self.heartbeats.upsert(
            service_name=service_name,
            status="ok",
            version="0.1.3-beta",
            started_at=self.started_at,
            last_seen_at=last_seen_at or self.now - timedelta(seconds=10),
            metadata=metadata,
        )


def _heartbeat(report: dict, service_name: str) -> dict:
    return next(item for item in report["heartbeats"] if item["service_name"] == service_name)


if __name__ == "__main__":
    unittest.main()
