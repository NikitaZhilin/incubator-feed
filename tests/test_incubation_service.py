from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

from app.services.incubation import IncubationService
from app.storage.database import Database
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.users import UserRepository


class IncubationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_dir.name) / "test.db")
        database.initialize()
        self.service = IncubationService(
            BatchRepository(database),
            ReminderRepository(database),
            UserRepository(database),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_chicken_status(self) -> None:
        batch = self.service.create_batch(
            user_id=1,
            species="chicken",
            eggs_count=12,
            start_date=date(2026, 5, 20),
        )

        status = self.service.get_status(batch, today=date(2026, 5, 23))

        self.assertEqual(status.day, 4)
        self.assertEqual(status.hatch_date, date(2026, 6, 10))
        self.assertEqual(status.stage, "инкубация")

    def test_complete_and_stats(self) -> None:
        batch = self.service.create_batch(
            user_id=1,
            species="quail",
            eggs_count=20,
            start_date=date(2026, 5, 1),
        )

        completed = self.service.complete_batch(
            batch_id=batch.id,
            user_id=1,
            hatched_count=16,
            completed_at=date(2026, 5, 18),
        )
        stats = self.service.get_stats(1)

        self.assertIsNotNone(completed)
        self.assertFalse(completed.is_active)
        self.assertEqual(stats.completed_batches, 1)
        self.assertEqual(stats.total_hatched, 16)
        self.assertEqual(stats.hatch_rate, 80)

    def test_batches_are_isolated_by_telegram_user(self) -> None:
        batch = self.service.create_batch(
            user_id=1,
            species="chicken",
            eggs_count=12,
            start_date=date(2026, 5, 20),
        )

        self.assertEqual([item.id for item in self.service.list_active(1)], [batch.id])
        self.assertEqual(self.service.list_active(2), [])
        self.assertIsNone(self.service.get_batch(batch.id, 2))

    def test_completed_batch_cannot_be_edited(self) -> None:
        batch = self.service.create_batch(
            user_id=1,
            species="quail",
            eggs_count=20,
            start_date=date(2026, 5, 1),
        )
        self.service.complete_batch(
            batch_id=batch.id,
            user_id=1,
            hatched_count=16,
            completed_at=date(2026, 5, 18),
        )

        with self.assertRaises(ValueError):
            self.service.update_batch(
                batch_id=batch.id,
                user_id=1,
                eggs_count=21,
            )

    def test_completed_batch_cannot_be_completed_again(self) -> None:
        batch = self.service.create_batch(
            user_id=1,
            species="quail",
            eggs_count=20,
            start_date=date(2026, 5, 1),
        )
        self.service.complete_batch(
            batch_id=batch.id,
            user_id=1,
            hatched_count=16,
            completed_at=date(2026, 5, 18),
        )

        with self.assertRaises(ValueError):
            self.service.complete_batch(
                batch_id=batch.id,
                user_id=1,
                hatched_count=17,
                completed_at=date(2026, 5, 19),
            )

    def test_register_user_is_in_known_users(self) -> None:
        self.service.register_user(
            user_id=42,
            username="tester",
            first_name="Test",
            last_name="User",
        )

        self.assertIn(42, self.service.list_known_users())

    def test_reminders(self) -> None:
        settings = self.service.set_reminders(1, True, 8, 30)

        self.assertTrue(settings.is_enabled)
        self.assertEqual(settings.hour, 8)
        self.assertEqual(settings.minute, 30)

    def test_explicit_reminder_settings_are_remembered(self) -> None:
        self.assertFalse(self.service.has_reminder_settings(1))

        self.service.set_reminders(1, False, 9, 0)

        self.assertTrue(self.service.has_reminder_settings(1))

    def test_future_batch_is_planned_and_not_due_for_reminders(self) -> None:
        batch = self.service.create_batch(
            user_id=1,
            species="chicken",
            eggs_count=12,
            start_date=date(2026, 6, 1),
        )
        self.service.set_reminders(1, True, 9, 0)

        status = self.service.get_status(batch, today=date(2026, 5, 23))
        due_users = self.service.list_due_reminder_users(datetime(2026, 5, 23, 10, 0))

        self.assertLessEqual(status.day, 0)
        self.assertEqual(status.stage, "запланировано")
        self.assertEqual(due_users, [])


if __name__ == "__main__":
    unittest.main()
