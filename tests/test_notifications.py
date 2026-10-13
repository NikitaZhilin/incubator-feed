from datetime import datetime, timedelta, timezone
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


    def _fail(self, key: str) -> None:
        self.notifications.record_attempt(
            user_id=1,
            type="daily_summary",
            event_key=key,
            scheduled_for=datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc),
        )
        self.notifications.mark_failed(key, error_code="telegram_error", error_message="bad")

    def test_new_and_pending_events_can_be_attempted(self) -> None:
        self.assertTrue(self.notifications.can_attempt("new-event"))

    def test_failed_event_waits_before_retry(self) -> None:
        self._fail("summary:1")
        right_now = datetime.now(timezone.utc)

        self.assertFalse(self.notifications.can_attempt("summary:1", now=right_now))
        self.assertTrue(
            self.notifications.can_attempt("summary:1", now=right_now + timedelta(minutes=11))
        )

    def test_failed_event_stops_after_max_attempts(self) -> None:
        for _ in range(5):
            self._fail("summary:2")
        later = datetime.now(timezone.utc) + timedelta(hours=2)

        self.assertFalse(self.notifications.can_attempt("summary:2", now=later))

    def test_sent_event_is_never_attempted_again(self) -> None:
        now = datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc)
        self.notifications.record_attempt(
            user_id=1, type="feed", event_key="feed:1", scheduled_for=now
        )
        self.notifications.mark_sent("feed:1", now)

        self.assertFalse(self.notifications.can_attempt("feed:1"))


if __name__ == "__main__":
    unittest.main()
