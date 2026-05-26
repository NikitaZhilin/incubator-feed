from datetime import date, datetime, timezone
import sqlite3

from app.domain import DailyWeather, EggEntry, HenLayingExclusion, WeatherSettings
from app.storage.database import Database


class EggRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_entry(
        self,
        *,
        user_id: int,
        entry_date: date,
        eggs_count: int,
        active_hens_count: int,
        total_hens_count: int,
        excluded_hens_count: int,
        note: str = "",
    ) -> EggEntry:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO egg_entries (
                    user_id, entry_date, eggs_count, active_hens_count,
                    total_hens_count, excluded_hens_count, note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    entry_date.isoformat(),
                    eggs_count,
                    active_hens_count,
                    total_hens_count,
                    excluded_hens_count,
                    note[:255],
                    now,
                ),
            )
            entry_id = int(cursor.lastrowid)
        return self.get_entry(entry_id, user_id)

    def get_entry(self, entry_id: int, user_id: int) -> EggEntry | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, entry_date, eggs_count, active_hens_count,
                       total_hens_count, excluded_hens_count, note, created_at
                FROM egg_entries
                WHERE id = ? AND user_id = ?
                """,
                (entry_id, user_id),
            ).fetchone()
        return self._entry_from_row(row) if row else None

    def list_entries(self, user_id: int, *, limit: int = 20) -> list[EggEntry]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, entry_date, eggs_count, active_hens_count,
                       total_hens_count, excluded_hens_count, note, created_at
                FROM egg_entries
                WHERE user_id = ?
                ORDER BY entry_date DESC, created_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._entry_from_row(row) for row in rows]

    def sum_between(self, user_id: int, *, start_date: date, end_date: date) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(eggs_count), 0) AS total
                FROM egg_entries
                WHERE user_id = ? AND entry_date BETWEEN ? AND ?
                """,
                (user_id, start_date.isoformat(), end_date.isoformat()),
            ).fetchone()
        return int(row["total"] or 0)

    def daily_totals(self, user_id: int, *, start_date: date, end_date: date) -> dict[date, int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT entry_date, SUM(eggs_count) AS total
                FROM egg_entries
                WHERE user_id = ? AND entry_date BETWEEN ? AND ?
                GROUP BY entry_date
                ORDER BY entry_date DESC
                """,
                (user_id, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return {date.fromisoformat(str(row["entry_date"])): int(row["total"] or 0) for row in rows}

    def create_exclusion(
        self,
        *,
        user_id: int,
        hens_count: int,
        reason: str,
        started_at: date,
        expected_until: date | None = None,
        bird_group_id: int | None = None,
        note: str = "",
    ) -> HenLayingExclusion:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO hen_laying_exclusions (
                    user_id, bird_group_id, hens_count, reason, started_at,
                    expected_until, note, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    bird_group_id,
                    hens_count,
                    reason[:80],
                    started_at.isoformat(),
                    expected_until.isoformat() if expected_until else None,
                    note[:255],
                    now,
                    now,
                ),
            )
            exclusion_id = int(cursor.lastrowid)
        return self.get_exclusion(exclusion_id, user_id)

    def get_exclusion(self, exclusion_id: int, user_id: int) -> HenLayingExclusion | None:
        with self.database.connect() as connection:
            row = connection.execute(
                self._exclusion_select_sql("WHERE hle.id = ? AND hle.user_id = ?"),
                (exclusion_id, user_id),
            ).fetchone()
        return self._exclusion_from_row(row) if row else None

    def list_active_exclusions(self, user_id: int, *, on_date: date) -> list[HenLayingExclusion]:
        with self.database.connect() as connection:
            rows = connection.execute(
                self._exclusion_select_sql(
                    """
                    WHERE hle.user_id = ?
                      AND hle.is_active = 1
                      AND hle.started_at <= ?
                      AND hle.actual_ended_at IS NULL
                      AND (hle.expected_until IS NULL OR hle.expected_until >= ?)
                    ORDER BY hle.started_at DESC, hle.id DESC
                    """
                ),
                (user_id, on_date.isoformat(), on_date.isoformat()),
            ).fetchall()
        return [self._exclusion_from_row(row) for row in rows]

    def list_open_exclusions(self, user_id: int) -> list[HenLayingExclusion]:
        with self.database.connect() as connection:
            rows = connection.execute(
                self._exclusion_select_sql(
                    """
                    WHERE hle.user_id = ?
                      AND hle.is_active = 1
                      AND hle.actual_ended_at IS NULL
                    ORDER BY hle.started_at DESC, hle.id DESC
                    """
                ),
                (user_id,),
            ).fetchall()
        return [self._exclusion_from_row(row) for row in rows]

    def finish_exclusion(self, *, exclusion_id: int, user_id: int, ended_at: date) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE hen_laying_exclusions
                SET actual_ended_at = ?,
                    is_active = 0,
                    updated_at = ?
                WHERE id = ? AND user_id = ? AND is_active = 1
                """,
                (ended_at.isoformat(), now, exclusion_id, user_id),
            )
        return cursor.rowcount > 0

    def get_weather_settings(self, user_id: int) -> WeatherSettings:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, city, latitude, longitude, provider, updated_at
                FROM weather_settings
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if row is None:
                now = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    """
                    INSERT INTO weather_settings (user_id, city, provider, updated_at)
                    VALUES (?, 'Курск', 'manual', ?)
                    """,
                    (user_id, now),
                )
                row = connection.execute(
                    """
                    SELECT user_id, city, latitude, longitude, provider, updated_at
                    FROM weather_settings
                    WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
        return self._weather_from_row(row)

    def update_weather_city(
        self,
        *,
        user_id: int,
        city: str,
        latitude: float | None = None,
        longitude: float | None = None,
        provider: str = "manual",
    ) -> WeatherSettings:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO weather_settings (
                    user_id, city, latitude, longitude, provider, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    city = excluded.city,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    provider = excluded.provider,
                    updated_at = excluded.updated_at
                """,
                (user_id, city[:120], latitude, longitude, provider[:80], now),
            )
        return self.get_weather_settings(user_id)

    def upsert_daily_weather(
        self,
        *,
        user_id: int,
        weather_date: date,
        city: str,
        temperature_avg_c: float | None,
        temperature_min_c: float | None,
        temperature_max_c: float | None,
        humidity_avg_percent: float | None = None,
        precipitation_mm: float | None = None,
        condition: str = "",
        provider: str = "open-meteo",
    ) -> DailyWeather:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_weather (
                    user_id, weather_date, city, temperature_avg_c,
                    temperature_min_c, temperature_max_c, humidity_avg_percent,
                    precipitation_mm, condition, provider, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, weather_date) DO UPDATE SET
                    city = excluded.city,
                    temperature_avg_c = excluded.temperature_avg_c,
                    temperature_min_c = excluded.temperature_min_c,
                    temperature_max_c = excluded.temperature_max_c,
                    humidity_avg_percent = excluded.humidity_avg_percent,
                    precipitation_mm = excluded.precipitation_mm,
                    condition = excluded.condition,
                    provider = excluded.provider,
                    created_at = excluded.created_at
                """,
                (
                    user_id,
                    weather_date.isoformat(),
                    city[:120],
                    temperature_avg_c,
                    temperature_min_c,
                    temperature_max_c,
                    humidity_avg_percent,
                    precipitation_mm,
                    condition[:120],
                    provider[:80],
                    now,
                ),
            )
        return self.get_daily_weather(user_id=user_id, weather_date=weather_date)

    def get_daily_weather(self, *, user_id: int, weather_date: date) -> DailyWeather | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, weather_date, city, temperature_avg_c,
                       temperature_min_c, temperature_max_c, humidity_avg_percent,
                       precipitation_mm, condition, provider, created_at
                FROM daily_weather
                WHERE user_id = ? AND weather_date = ?
                """,
                (user_id, weather_date.isoformat()),
            ).fetchone()
        return self._daily_weather_from_row(row) if row else None

    @staticmethod
    def _exclusion_select_sql(where_sql: str) -> str:
        return (
            """
            SELECT hle.id, hle.user_id, hle.bird_group_id, hle.hens_count,
                   hle.reason, hle.started_at, hle.expected_until,
                   hle.actual_ended_at, hle.note, hle.is_active,
                   hle.created_at, hle.updated_at, bg.name AS bird_group_name
            FROM hen_laying_exclusions AS hle
            LEFT JOIN bird_groups AS bg ON bg.id = hle.bird_group_id
            """
            + where_sql
        )

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> EggEntry:
        return EggEntry(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            entry_date=date.fromisoformat(str(row["entry_date"])),
            eggs_count=int(row["eggs_count"]),
            active_hens_count=int(row["active_hens_count"]),
            total_hens_count=int(row["total_hens_count"]),
            excluded_hens_count=int(row["excluded_hens_count"]),
            note=str(row["note"] or ""),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _exclusion_from_row(row: sqlite3.Row) -> HenLayingExclusion:
        return HenLayingExclusion(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            bird_group_id=int(row["bird_group_id"]) if row["bird_group_id"] is not None else None,
            hens_count=int(row["hens_count"]),
            reason=str(row["reason"]),
            started_at=date.fromisoformat(str(row["started_at"])),
            expected_until=date.fromisoformat(str(row["expected_until"])) if row["expected_until"] else None,
            actual_ended_at=date.fromisoformat(str(row["actual_ended_at"])) if row["actual_ended_at"] else None,
            note=str(row["note"] or ""),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            bird_group_name=str(row["bird_group_name"]) if row["bird_group_name"] else None,
        )

    @staticmethod
    def _weather_from_row(row: sqlite3.Row) -> WeatherSettings:
        return WeatherSettings(
            user_id=int(row["user_id"]),
            city=str(row["city"]),
            latitude=float(row["latitude"]) if row["latitude"] is not None else None,
            longitude=float(row["longitude"]) if row["longitude"] is not None else None,
            provider=str(row["provider"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _daily_weather_from_row(row: sqlite3.Row) -> DailyWeather:
        return DailyWeather(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            weather_date=date.fromisoformat(str(row["weather_date"])),
            city=str(row["city"]),
            temperature_avg_c=(
                float(row["temperature_avg_c"]) if row["temperature_avg_c"] is not None else None
            ),
            temperature_min_c=(
                float(row["temperature_min_c"]) if row["temperature_min_c"] is not None else None
            ),
            temperature_max_c=(
                float(row["temperature_max_c"]) if row["temperature_max_c"] is not None else None
            ),
            humidity_avg_percent=(
                float(row["humidity_avg_percent"]) if row["humidity_avg_percent"] is not None else None
            ),
            precipitation_mm=(
                float(row["precipitation_mm"]) if row["precipitation_mm"] is not None else None
            ),
            condition=str(row["condition"] or ""),
            provider=str(row["provider"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )
