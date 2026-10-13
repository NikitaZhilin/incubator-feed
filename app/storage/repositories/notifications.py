from datetime import datetime, timedelta, timezone

from app.storage.database import Database


class NotificationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def was_sent(self, event_key: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM notification_log
                WHERE event_key = ? AND status = 'sent'
                """,
                (event_key,),
            ).fetchone()
        return row is not None

    def can_attempt(
        self,
        event_key: str,
        *,
        max_attempts: int = 5,
        retry_delay: timedelta = timedelta(minutes=10),
        now: datetime | None = None,
    ) -> bool:
        """False when the event was sent, failed too often, or failed too recently.

        Keeps a permanently failing message (bad text, rate limit) from being
        retried on every reminder tick.
        """
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT status, attempts, updated_at
                FROM notification_log
                WHERE event_key = ?
                """,
                (event_key,),
            ).fetchone()
        if row is None:
            return True
        if row["status"] == "sent":
            return False
        if row["status"] != "failed":
            return True
        if int(row["attempts"] or 0) >= max_attempts:
            return False
        last_try = _parse_sqlite_timestamp(row["updated_at"])
        if last_try is None:
            return True
        current = now or datetime.now(timezone.utc)
        return current - last_try >= retry_delay

    def record_attempt(
        self,
        *,
        user_id: int,
        type: str,
        event_key: str,
        scheduled_for: datetime,
        batch_id: int | None = None,
        feed_id: int | None = None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO notification_log (
                    user_id, batch_id, feed_id, type, event_key, scheduled_for,
                    status, attempts
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 1)
                ON CONFLICT(event_key) DO UPDATE SET
                    batch_id = excluded.batch_id,
                    feed_id = excluded.feed_id,
                    scheduled_for = excluded.scheduled_for,
                    attempts = notification_log.attempts + 1,
                    status = 'pending',
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    batch_id,
                    feed_id,
                    type,
                    event_key,
                    scheduled_for.isoformat(),
                ),
            )

    def mark_sent(self, event_key: str, sent_at: datetime) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE notification_log
                SET status = 'sent',
                    sent_at = ?,
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE event_key = ?
                """,
                (sent_at.isoformat(), event_key),
            )

    def mark_failed(self, event_key: str, *, error_code: str, error_message: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE notification_log
                SET status = 'failed',
                    error_code = ?,
                    error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE event_key = ?
                """,
                (error_code[:64], error_message[:500], event_key),
            )

    def count_failures(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS c FROM notification_log WHERE status = 'failed'"
            ).fetchone()
        return int(row["c"])

    def recent_failures(self, limit: int = 10) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id, type, event_key, error_code, error_message, updated_at
                FROM notification_log
                WHERE status = 'failed'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


def _parse_sqlite_timestamp(value) -> datetime | None:
    """Parse CURRENT_TIMESTAMP ('YYYY-MM-DD HH:MM:SS', UTC) or an ISO string."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
