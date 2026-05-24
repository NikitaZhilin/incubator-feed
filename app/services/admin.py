from __future__ import annotations

from dataclasses import dataclass
import csv
import io
import shutil

from app.config import AppConfig
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.users import UserRepository


@dataclass(frozen=True)
class AdminStats:
    total_users: int
    active_users: int
    active_batches: int
    active_feeds: int
    notification_failures: int
    free_disk_mb: int
    recent_users: list[dict]
    recent_errors: list[dict]


class AdminService:
    def __init__(
        self,
        *,
        database: Database,
        users: UserRepository,
        notifications: NotificationRepository,
        analytics: AnalyticsRepository,
        config: AppConfig,
    ) -> None:
        self.database = database
        self.users = users
        self.notifications = notifications
        self.analytics = analytics
        self.config = config

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.config.admin_ids

    def get_stats(self) -> AdminStats:
        user_stats = self.users.stats()
        with self.database.connect() as connection:
            active_batches = connection.execute(
                "SELECT COUNT(*) AS c FROM incubation_batches WHERE is_active = 1"
            ).fetchone()["c"]
            active_feeds = connection.execute(
                "SELECT COUNT(*) AS c FROM feed_stocks WHERE is_archived = 0"
            ).fetchone()["c"]
        usage = shutil.disk_usage(self.config.db_path.parent)
        return AdminStats(
            total_users=user_stats["total"],
            active_users=user_stats["active"],
            active_batches=int(active_batches),
            active_feeds=int(active_feeds),
            notification_failures=self.notifications.count_failures(),
            free_disk_mb=usage.free // 1024 // 1024,
            recent_users=user_stats["recent"],
            recent_errors=self.analytics.recent_critical_errors(),
        )

    def export_stats_csv(self) -> bytes:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["event_name", "count"])
        for row in self.analytics.counts_by_event():
            writer.writerow([row["event_name"], row["count"]])
        return output.getvalue().encode("utf-8-sig")
