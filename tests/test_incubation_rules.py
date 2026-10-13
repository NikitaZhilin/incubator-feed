from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.incubation import IncubationService
from app.storage.database import Database
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.users import UserRepository
from app.utils.dates import validate_incubation_start_date


class IncubationRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_dir.name) / "test.db")
        database.initialize()
        self.users = UserRepository(database)
        self.service = IncubationService(BatchRepository(database), ReminderRepository(database), self.users)
        self.users.upsert(user_id=1)
        self.users.update_settings(1, notification_time="09:00", notify_post_hatch_care=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _completed(self, start: date, hatched: int) -> None:
        batch = self.service.create_batch(user_id=1, species="chicken", eggs_count=10, start_date=start)
        self.service.complete_batch(
            batch_id=batch.id,
            user_id=1,
            hatched_count=hatched,
            completed_at=start + timedelta(days=21),
        )

    def test_old_batches_do_not_get_post_hatch_memo(self) -> None:
        self._completed(date(2025, 5, 1), hatched=8)

        due = self.service.list_due_post_hatch_notifications(
            datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        )

        self.assertEqual(due, [])

    def test_recent_batch_gets_memo_but_not_when_nothing_hatched(self) -> None:
        self._completed(date(2026, 9, 21), hatched=8)
        self._completed(date(2026, 9, 21), hatched=0)

        due = self.service.list_due_post_hatch_notifications(
            datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        )

        self.assertEqual([item.status.batch.hatched_count for item in due], [8])

    def test_start_date_typos_are_rejected(self) -> None:
        today = date(2026, 10, 13)
        validate_incubation_start_date(today - timedelta(days=20), today=today)
        validate_incubation_start_date(today + timedelta(days=7), today=today)
        with self.assertRaises(ValueError):
            validate_incubation_start_date(date(2025, 10, 13), today=today)
        with self.assertRaises(ValueError):
            validate_incubation_start_date(date(2062, 10, 13), today=today)


if __name__ == "__main__":
    unittest.main()
