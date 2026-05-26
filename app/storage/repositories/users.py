from app.storage.database import Database


DEFAULT_NOTIFICATION_TIME = "09:00"


class UserRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(
        self,
        *,
        user_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> dict:
        previous = self.get_user_meta(user_id)
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    is_active = 1,
                    inactive_reason = NULL,
                    deactivated_at = NULL,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (user_id, username, first_name, last_name),
            )
        return {
            "existed": previous is not None,
            "was_inactive": bool(previous and not previous["is_active"]),
            "last_seen_at": previous["last_seen_at"] if previous else None,
        }

    def get_user_meta(self, user_id: int) -> dict | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, is_active, last_seen_at
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_known_users(self) -> list[int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id
                FROM users
                ORDER BY last_seen_at DESC
                """
            ).fetchall()
        return [int(row["user_id"]) for row in rows]

    def list_active_users(self) -> list[int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id
                FROM users
                WHERE is_active = 1
                ORDER BY last_seen_at DESC
                """
            ).fetchall()
        return [int(row["user_id"]) for row in rows]

    def list_users_with_settings(self) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id, timezone, notification_time, notify_incubation,
                       notify_feed, notify_eggs, notify_post_hatch_care, notify_service,
                       units, farm_name, is_active
                FROM users
                ORDER BY user_id
                """
            ).fetchall()
        return [self._settings_from_row(row) for row in rows]

    def mark_inactive(self, user_id: int, reason: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET is_active = 0,
                    inactive_reason = ?,
                    deactivated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (reason[:255], user_id),
            )

    def get_settings(self, user_id: int) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, timezone, notification_time, notify_incubation,
                       notify_feed, notify_eggs, notify_post_hatch_care, notify_service,
                       units, farm_name, is_active
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return {
                "user_id": user_id,
                "timezone": "Europe/Moscow",
                "notification_time": DEFAULT_NOTIFICATION_TIME,
                "notify_incubation": True,
                "notify_feed": True,
                "notify_eggs": True,
                "notify_post_hatch_care": True,
                "notify_service": True,
                "units": "metric",
                "farm_name": "",
                "is_active": True,
            }
        return self._settings_from_row(row)

    def update_settings(self, user_id: int, **fields) -> dict:
        allowed = {
            "timezone",
            "notification_time",
            "notify_incubation",
            "notify_feed",
            "notify_eggs",
            "notify_post_hatch_care",
            "notify_service",
            "units",
            "farm_name",
        }
        self.upsert(user_id=user_id)
        clean = {key: value for key, value in fields.items() if key in allowed}
        if clean:
            assignments = ", ".join(f"{key} = ?" for key in clean)
            values = [
                int(value) if key.startswith("notify_") else value
                for key, value in clean.items()
            ]
            values.append(user_id)
            with self.database.connect() as connection:
                connection.execute(
                    f"UPDATE users SET {assignments} WHERE user_id = ?",
                    values,
                )
        return self.get_settings(user_id)

    @staticmethod
    def _settings_from_row(row) -> dict:
        return {
            "user_id": int(row["user_id"]),
            "timezone": str(row["timezone"]),
            "notification_time": str(row["notification_time"]),
            "notify_incubation": bool(row["notify_incubation"]),
            "notify_feed": bool(row["notify_feed"]),
            "notify_eggs": bool(row["notify_eggs"]) if "notify_eggs" in row.keys() else True,
            "notify_post_hatch_care": bool(row["notify_post_hatch_care"]),
            "notify_service": bool(row["notify_service"]),
            "units": str(row["units"]),
            "farm_name": str(row["farm_name"] or ""),
            "is_active": bool(row["is_active"]),
        }

    def stats(self) -> dict:
        with self.database.connect() as connection:
            total = connection.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            active = connection.execute(
                "SELECT COUNT(*) AS c FROM users WHERE is_active = 1"
            ).fetchone()["c"]
            recent = connection.execute(
                """
                SELECT user_id, username, first_name, created_at
                FROM users
                ORDER BY created_at DESC
                LIMIT 5
                """
            ).fetchall()
        return {
            "total": int(total),
            "active": int(active),
            "recent": [dict(row) for row in recent],
        }
