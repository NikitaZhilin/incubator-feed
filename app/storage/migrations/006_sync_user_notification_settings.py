import sqlite3


def up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO users (
            user_id, timezone, notification_time, notify_incubation,
            created_at, last_seen_at
        )
        SELECT
            rs.user_id,
            'Europe/Moscow',
            printf('%02d:%02d', rs.hour, rs.minute),
            rs.is_enabled,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM reminder_settings AS rs
        WHERE NOT EXISTS (
            SELECT 1 FROM users AS u WHERE u.user_id = rs.user_id
        )
        """
    )
    connection.execute(
        """
        UPDATE users
        SET notification_time = (
                SELECT printf('%02d:%02d', rs.hour, rs.minute)
                FROM reminder_settings AS rs
                WHERE rs.user_id = users.user_id
            ),
            notify_incubation = (
                SELECT rs.is_enabled
                FROM reminder_settings AS rs
                WHERE rs.user_id = users.user_id
            )
        WHERE EXISTS (
            SELECT 1 FROM reminder_settings AS rs WHERE rs.user_id = users.user_id
        )
        """
    )
