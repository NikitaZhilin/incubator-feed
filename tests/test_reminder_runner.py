from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.domain import FeedEstimate, FeedStock
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.services.reminders import ReminderRunner
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.users import UserRepository


class FakeBot:
    def __init__(self) -> None:
        self.sent_to: list[int] = []

    async def send_message(self, user_id: int, text: str) -> None:
        if user_id == 1:
            raise RuntimeError("temporary telegram failure")
        self.sent_to.append(user_id)


class FakeIncubationService:
    def list_due_incubation_notifications(self, now) -> list:
        return []

    def list_due_post_hatch_notifications(self, now) -> list:
        return []

    def get_user_settings(self, user_id: int) -> dict:
        return {
            "user_id": user_id,
            "timezone": "Europe/Moscow",
            "notification_time": "09:00",
            "notify_feed": True,
            "is_active": True,
        }


class FakeFeedService:
    def __init__(self) -> None:
        created_at = datetime(2026, 5, 23, tzinfo=timezone.utc)
        self.estimates = [
            self._estimate(1, created_at),
            self._estimate(2, created_at),
        ]
        self.marked: list[int] = []

    def list_due_purchase_reminders(self, now) -> list[FeedEstimate]:
        return self.estimates

    def mark_purchase_reminded(self, feed_id: int, reminded_at) -> None:
        self.marked.append(feed_id)

    @staticmethod
    def _estimate(user_id: int, created_at: datetime) -> FeedEstimate:
        feed = FeedStock(
            id=user_id,
            user_id=user_id,
            name=f"Feed {user_id}",
            amount_kg=1,
            bird_count=10,
            daily_per_bird_g=100,
            low_threshold_kg=5,
            created_at=created_at,
        )
        return FeedEstimate(
            feed=feed,
            remaining_kg=1,
            daily_usage_kg=1,
            days_left=1,
            threshold_days_left=0,
            buy_remind_at=None,
        )


class ReminderRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_feed_reminder_failure_does_not_block_next_feed(self) -> None:
        bot = FakeBot()
        feed_service = FakeFeedService()
        runner = ReminderRunner(
            bot=bot,
            incubation_service=FakeIncubationService(),
            feed_service=feed_service,
            timezone="Europe/Moscow",
        )

        await runner._send_due_reminders(datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc))

        self.assertEqual(bot.sent_to, [2])
        self.assertEqual(feed_service.marked, [2])

    async def test_user_notification_time_and_timezone_drive_incubation_due(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "test.db")
            database.initialize()
            users = UserRepository(database)
            service = IncubationService(
                BatchRepository(database),
                ReminderRepository(database),
                users,
                AnalyticsRepository(database),
            )
            notifications = NotificationRepository(database)
            service.register_user(user_id=10)
            service.update_user_settings(
                10,
                timezone="Asia/Yekaterinburg",
                notification_time="08:30",
                notify_incubation=True,
            )
            service.create_batch(
                user_id=10,
                species="chicken",
                eggs_count=10,
                start_date=datetime(2026, 5, 20).date(),
            )
            bot = FakeBot()
            runner = ReminderRunner(
                bot=bot,
                incubation_service=service,
                notifications=notifications,
                timezone="UTC",
            )

            await runner._send_due_reminders(datetime(2026, 5, 25, 2, 0, tzinfo=timezone.utc))
            self.assertEqual(bot.sent_to, [])

            await runner._send_due_reminders(datetime(2026, 5, 25, 3, 31, tzinfo=timezone.utc))
            self.assertEqual(bot.sent_to, [10])

            with database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT batch_id, type, event_key, status
                    FROM notification_log
                    WHERE type = 'incubation'
                    """
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertIsNotNone(row["batch_id"])
            self.assertIn("incubation:batch_", row["event_key"])
            self.assertEqual(row["status"], "sent")

            await runner._send_due_reminders(datetime(2026, 5, 25, 4, 0, tzinfo=timezone.utc))
            self.assertEqual(bot.sent_to, [10])

    async def test_disabled_or_inactive_users_do_not_receive_feed_reminders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "test.db")
            database.initialize()
            users = UserRepository(database)
            analytics = AnalyticsRepository(database)
            incubation = IncubationService(
                BatchRepository(database),
                ReminderRepository(database),
                users,
                analytics,
            )
            feed_service = FeedService(FeedRepository(database), analytics)
            users.upsert(user_id=1)
            users.upsert(user_id=2)
            users.update_settings(1, notify_feed=False)
            users.mark_inactive(2, "blocked")
            feed_service.create_feed(
                user_id=1,
                name="Feed 1",
                amount_kg=1,
                bird_count=10,
                daily_per_bird_g=100,
                low_threshold_kg=5,
            )
            feed_service.create_feed(
                user_id=2,
                name="Feed 2",
                amount_kg=1,
                bird_count=10,
                daily_per_bird_g=100,
                low_threshold_kg=5,
            )
            bot = FakeBot()
            runner = ReminderRunner(
                bot=bot,
                incubation_service=incubation,
                feed_service=feed_service,
                notifications=NotificationRepository(database),
                timezone="UTC",
            )

            await runner._send_due_reminders(datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc))

            self.assertEqual(bot.sent_to, [])

    async def test_post_hatch_reminder_is_sent_once_with_batch_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "test.db")
            database.initialize()
            users = UserRepository(database)
            service = IncubationService(
                BatchRepository(database),
                ReminderRepository(database),
                users,
            )
            notifications = NotificationRepository(database)
            users.upsert(user_id=30)
            users.update_settings(
                30,
                notification_time="09:00",
                notify_incubation=False,
                notify_post_hatch_care=True,
            )
            batch = service.create_batch(
                user_id=30,
                species="quail",
                eggs_count=20,
                start_date=datetime(2026, 5, 1).date(),
            )
            bot = FakeBot()
            runner = ReminderRunner(
                bot=bot,
                incubation_service=service,
                notifications=notifications,
                timezone="UTC",
            )

            await runner._send_due_reminders(datetime(2026, 5, 19, 9, 5, tzinfo=timezone.utc))
            await runner._send_due_reminders(datetime(2026, 5, 19, 10, 5, tzinfo=timezone.utc))

            self.assertEqual(bot.sent_to, [30])
            with database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT batch_id, type, status
                    FROM notification_log
                    WHERE type = 'post_hatch_care'
                    """
                ).fetchone()
            self.assertEqual(row["batch_id"], batch.id)
            self.assertEqual(row["status"], "sent")

    async def test_disabled_post_hatch_reminder_is_not_sent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "test.db")
            database.initialize()
            users = UserRepository(database)
            service = IncubationService(
                BatchRepository(database),
                ReminderRepository(database),
                users,
            )
            users.upsert(user_id=40)
            users.update_settings(
                40,
                notification_time="09:00",
                notify_incubation=False,
                notify_post_hatch_care=False,
            )
            service.create_batch(
                user_id=40,
                species="quail",
                eggs_count=20,
                start_date=datetime(2026, 5, 1).date(),
            )
            bot = FakeBot()
            runner = ReminderRunner(
                bot=bot,
                incubation_service=service,
                notifications=NotificationRepository(database),
                timezone="UTC",
            )

            await runner._send_due_reminders(datetime(2026, 5, 19, 9, 5, tzinfo=timezone.utc))

            self.assertEqual(bot.sent_to, [])


if __name__ == "__main__":
    unittest.main()
