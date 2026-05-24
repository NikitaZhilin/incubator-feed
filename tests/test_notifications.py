from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.storage.database import Database
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.users import UserRepository


class NotificationRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.db")
        self.database.initialize()
        self.notifications = NotificationRepository(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sent_event_is_deduplicated(self) -> None:
        now = datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc)
        self.notifications.record_attempt(
            user_id=1,
            type="incubation",
            event_key="incubation:user_1:2026-05-25",
            scheduled_for=now,
        )
        self.notifications.mark_sent("incubation:user_1:2026-05-25", now)

        self.assertTrue(self.notifications.was_sent("incubation:user_1:2026-05-25"))

    def test_user_can_be_marked_inactive(self) -> None:
        users = UserRepository(self.database)
        users.upsert(user_id=1, username="u")
        users.mark_inactive(1, "blocked")

        self.assertFalse(users.get_settings(1)["is_active"])


if __name__ == "__main__":
    unittest.main()
