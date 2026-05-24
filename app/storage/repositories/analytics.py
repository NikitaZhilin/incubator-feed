import json
import traceback

from app.storage.database import Database


class AnalyticsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def track(
        self,
        event_name: str,
        *,
        user_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        payload: dict | None = None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO analytics_events (
                    user_id, event_name, entity_type, entity_id, payload_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    event_name,
                    entity_type,
                    entity_id,
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )

    def log_critical(self, source: str, exc: BaseException | str) -> None:
        if isinstance(exc, BaseException):
            message = str(exc)
            tb = "".join(traceback.format_exception(exc))
        else:
            message = exc
            tb = None
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO critical_errors (source, message, traceback)
                VALUES (?, ?, ?)
                """,
                (source, message[:500], tb),
            )

    def recent_critical_errors(self, limit: int = 5) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT source, message, created_at
                FROM critical_errors
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def counts_by_event(self) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT event_name, COUNT(*) AS count
                FROM analytics_events
                GROUP BY event_name
                ORDER BY count DESC, event_name
                """
            ).fetchall()
        return [dict(row) for row in rows]
