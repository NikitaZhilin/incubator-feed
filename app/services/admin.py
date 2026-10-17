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
    records_30d: dict | None = None
    top_events_7d: list | None = None
    last_backup: str = ""


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
        records, top_events = self._activity()
        last_backup = ""
        try:
            from app.services.backups import latest_backup_time

            moment = latest_backup_time(self.config.db_path, self.config.backup_dir)
            last_backup = moment.strftime("%d.%m.%Y %H:%M UTC") if moment else "нет"
        except Exception:
            last_backup = "не удалось проверить"
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
            records_30d=records,
            top_events_7d=top_events,
            last_backup=last_backup,
        )

    def _activity(self) -> tuple[dict, list]:
        """How much was recorded in 30 days by section, and the most used actions in 7 days."""
        queries = {
            "Сборов яиц": "SELECT COUNT(*) FROM egg_entries WHERE created_at >= datetime('now', '-30 days')",
            "Кормлений": "SELECT COUNT(*) FROM feeding_events WHERE created_at >= datetime('now', '-30 days')",
            "Покупок на склад": "SELECT COUNT(*) FROM stock_transactions WHERE type = 'purchase' AND created_at >= datetime('now', '-30 days')",
            "Продаж и раздач яиц": "SELECT COUNT(*) FROM egg_outflows WHERE created_at >= datetime('now', '-30 days')",
            "Записей о падеже": "SELECT COUNT(*) FROM bird_losses WHERE created_at >= datetime('now', '-30 days')",
            "Дел по уходу отмечено": "SELECT COUNT(*) FROM care_tasks WHERE last_done >= date('now', '-30 days')",
            "Инкубационных партий": "SELECT COUNT(*) FROM incubation_batches WHERE created_at >= datetime('now', '-30 days')",
        }
        records: dict = {}
        top: list = []
        with self.database.connect() as connection:
            for label, sql in queries.items():
                try:
                    records[label] = int(connection.execute(sql).fetchone()[0])
                except Exception:
                    records[label] = None
            try:
                top = [
                    (row[0], int(row[1]))
                    for row in connection.execute(
                        """
                        SELECT event_name, COUNT(*) FROM analytics_events
                        WHERE created_at >= datetime('now', '-7 days')
                        GROUP BY event_name ORDER BY COUNT(*) DESC LIMIT 8
                        """
                    )
                ]
            except Exception:
                top = []
        return records, top

    def export_stats_csv(self) -> bytes:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["event_name", "count"])
        for row in self.analytics.counts_by_event():
            writer.writerow([row["event_name"], row["count"]])
        return output.getvalue().encode("utf-8-sig")
