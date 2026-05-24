from datetime import datetime, timezone
import sqlite3

from app.domain import BirdGroup, FeedStock, FeedTransaction
from app.storage.database import Database


class FeedRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        user_id: int,
        name: str,
        amount_kg: float,
        bird_count: int,
        daily_per_bird_g: float,
        low_threshold_kg: float,
        bird_group_id: int | None = None,
    ) -> FeedStock:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO feed_stocks (
                    user_id, name, amount_kg, bird_count, daily_per_bird_g, low_threshold_kg,
                    bird_group_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    name,
                    amount_kg,
                    bird_count,
                    daily_per_bird_g,
                    low_threshold_kg,
                    bird_group_id,
                    created_at,
                    created_at,
                ),
            )
            feed_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO feed_transactions (
                    feed_id, user_id, type, amount_kg, balance_after_kg, note, created_at
                )
                VALUES (?, ?, 'initial', ?, ?, 'Начальный остаток', ?)
                """,
                (feed_id, user_id, amount_kg, amount_kg, created_at),
            )
        return self.get(feed_id, user_id)

    def get(self, feed_id: int, user_id: int) -> FeedStock | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT fs.id, fs.user_id, fs.name, fs.amount_kg, fs.bird_count,
                       fs.daily_per_bird_g, fs.low_threshold_kg, fs.purchase_reminded_at,
                       fs.created_at, fs.updated_at, fs.bird_group_id, bg.name AS bird_group_name,
                       fs.is_archived
                FROM feed_stocks
                AS fs
                LEFT JOIN bird_groups AS bg ON bg.id = fs.bird_group_id
                WHERE fs.id = ? AND fs.user_id = ?
                """,
                (feed_id, user_id),
            ).fetchone()
        return self._from_row(row) if row else None

    def list_for_user(self, user_id: int) -> list[FeedStock]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT fs.id, fs.user_id, fs.name, fs.amount_kg, fs.bird_count,
                       fs.daily_per_bird_g, fs.low_threshold_kg, fs.purchase_reminded_at,
                       fs.created_at, fs.updated_at, fs.bird_group_id, bg.name AS bird_group_name,
                       fs.is_archived
                FROM feed_stocks AS fs
                LEFT JOIN bird_groups AS bg ON bg.id = fs.bird_group_id
                WHERE fs.user_id = ? AND fs.is_archived = 0
                ORDER BY fs.created_at DESC, fs.id DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_all(self) -> list[FeedStock]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT fs.id, fs.user_id, fs.name, fs.amount_kg, fs.bird_count,
                       fs.daily_per_bird_g, fs.low_threshold_kg, fs.purchase_reminded_at,
                       fs.created_at, fs.updated_at, fs.bird_group_id, bg.name AS bird_group_name,
                       fs.is_archived
                FROM feed_stocks AS fs
                LEFT JOIN bird_groups AS bg ON bg.id = fs.bird_group_id
                WHERE fs.is_archived = 0
                ORDER BY fs.created_at DESC, fs.id DESC
                """
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def archive(self, feed_id: int, user_id: int) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE feed_stocks
                SET is_archived = 1, archived_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (feed_id, user_id),
            )
            return cursor.rowcount > 0

    def delete(self, feed_id: int, user_id: int) -> bool:
        return self.archive(feed_id, user_id)

    def update(
        self,
        *,
        feed_id: int,
        user_id: int,
        name: str | None = None,
        bird_count: int | None = None,
        daily_per_bird_g: float | None = None,
        low_threshold_kg: float | None = None,
        bird_group_id: int | None = None,
        clear_bird_group: bool = False,
    ) -> FeedStock | None:
        current = self.get(feed_id, user_id)
        if current is None:
            return None
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE feed_stocks
                SET name = ?,
                    bird_count = ?,
                    daily_per_bird_g = ?,
                    low_threshold_kg = ?,
                    bird_group_id = ?,
                    purchase_reminded_at = NULL
                WHERE id = ? AND user_id = ?
                """,
                (
                    name if name is not None else current.name,
                    bird_count if bird_count is not None else current.bird_count,
                    daily_per_bird_g if daily_per_bird_g is not None else current.daily_per_bird_g,
                    low_threshold_kg if low_threshold_kg is not None else current.low_threshold_kg,
                    None if clear_bird_group else (
                        bird_group_id if bird_group_id is not None else current.bird_group_id
                    ),
                    feed_id,
                    user_id,
                ),
            )
        return self.get(feed_id, user_id)

    def update_stock(
        self,
        *,
        feed_id: int,
        user_id: int,
        amount_kg: float,
        updated_at: datetime,
    ) -> FeedStock | None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE feed_stocks
                SET amount_kg = ?,
                    updated_at = ?,
                    purchase_reminded_at = NULL
                WHERE id = ? AND user_id = ?
                """,
                (amount_kg, updated_at.isoformat(), feed_id, user_id),
            )
            if cursor.rowcount == 0:
                return None
            connection.execute(
                """
                INSERT INTO feed_transactions (
                    feed_id, user_id, type, amount_kg, balance_after_kg, note, created_at
                )
                VALUES (?, ?, 'adjustment', ?, ?, 'Новый фактический остаток', ?)
                """,
                (feed_id, user_id, amount_kg, amount_kg, updated_at.isoformat()),
            )
        return self.get(feed_id, user_id)

    def change_stock(
        self,
        *,
        feed_id: int,
        user_id: int,
        delta_kg: float,
        transaction_type: str,
        note: str = "",
        created_at: datetime | None = None,
    ) -> FeedStock | None:
        timestamp = created_at or datetime.now(timezone.utc)
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT amount_kg
                FROM feed_stocks
                WHERE id = ? AND user_id = ? AND is_archived = 0
                """,
                (feed_id, user_id),
            ).fetchone()
            if row is None:
                return None
            balance_after = max(float(row["amount_kg"]) + delta_kg, 0)
            connection.execute(
                """
                UPDATE feed_stocks
                SET amount_kg = ?,
                    updated_at = ?,
                    purchase_reminded_at = NULL
                WHERE id = ? AND user_id = ?
                """,
                (balance_after, timestamp.isoformat(), feed_id, user_id),
            )
            connection.execute(
                """
                INSERT INTO feed_transactions (
                    feed_id, user_id, type, amount_kg, balance_after_kg, note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feed_id,
                    user_id,
                    transaction_type,
                    delta_kg,
                    balance_after,
                    note[:255],
                    timestamp.isoformat(),
                ),
            )
        return self.get(feed_id, user_id)

    def list_transactions(self, feed_id: int, user_id: int, limit: int = 20) -> list[FeedTransaction]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, feed_id, user_id, type, amount_kg, balance_after_kg, note, created_at
                FROM feed_transactions
                WHERE feed_id = ? AND user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (feed_id, user_id, limit),
            ).fetchall()
        return [self._transaction_from_row(row) for row in rows]

    def create_bird_group(
        self,
        *,
        user_id: int,
        name: str,
        bird_count: int,
        species: str | None = None,
    ) -> BirdGroup:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO bird_groups (user_id, name, bird_count, species, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, name, bird_count, species, now, now),
            )
            group_id = int(cursor.lastrowid)
        return self.get_bird_group(group_id, user_id)

    def get_bird_group(self, group_id: int, user_id: int) -> BirdGroup | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, name, bird_count, species, is_active, created_at, updated_at
                FROM bird_groups
                WHERE id = ? AND user_id = ?
                """,
                (group_id, user_id),
            ).fetchone()
        return self._bird_group_from_row(row) if row else None

    def list_bird_groups(self, user_id: int) -> list[BirdGroup]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, name, bird_count, species, is_active, created_at, updated_at
                FROM bird_groups
                WHERE user_id = ? AND is_active = 1
                ORDER BY created_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._bird_group_from_row(row) for row in rows]

    def mark_purchase_reminded(self, feed_id: int, reminded_at: datetime) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE feed_stocks
                SET purchase_reminded_at = ?
                WHERE id = ?
                """,
                (reminded_at.isoformat(), feed_id),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> FeedStock:
        purchase_reminded_at = row["purchase_reminded_at"]
        updated_at = row["updated_at"] if "updated_at" in row.keys() else None
        return FeedStock(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            name=str(row["name"]),
            amount_kg=float(row["amount_kg"]),
            bird_count=int(row["bird_count"]),
            daily_per_bird_g=float(row["daily_per_bird_g"]),
            low_threshold_kg=float(row["low_threshold_kg"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(updated_at)) if updated_at else None,
            purchase_reminded_at=(
                datetime.fromisoformat(str(purchase_reminded_at))
                if purchase_reminded_at
                else None
            ),
            bird_group_id=(
                int(row["bird_group_id"])
                if "bird_group_id" in row.keys() and row["bird_group_id"] is not None
                else None
            ),
            bird_group_name=(
                str(row["bird_group_name"])
                if "bird_group_name" in row.keys() and row["bird_group_name"] is not None
                else None
            ),
            is_archived=bool(row["is_archived"]) if "is_archived" in row.keys() else False,
        )

    @staticmethod
    def _transaction_from_row(row: sqlite3.Row) -> FeedTransaction:
        return FeedTransaction(
            id=int(row["id"]),
            feed_id=int(row["feed_id"]),
            user_id=int(row["user_id"]),
            type=str(row["type"]),
            amount_kg=float(row["amount_kg"]),
            balance_after_kg=float(row["balance_after_kg"]),
            note=str(row["note"] or ""),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _bird_group_from_row(row: sqlite3.Row) -> BirdGroup:
        return BirdGroup(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            name=str(row["name"]),
            bird_count=int(row["bird_count"]),
            species=str(row["species"]) if row["species"] else None,
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
