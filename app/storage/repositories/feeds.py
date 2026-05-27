from datetime import date, datetime, timezone
import sqlite3

from app.domain import BirdGroup, FeedStock, FeedTransaction, Flock, FlockMember
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
        hen_count: int | None = None,
        rooster_count: int | None = None,
        hen_daily_g: float | None = None,
        rooster_daily_g: float | None = None,
    ) -> FeedStock:
        created_at = datetime.now(timezone.utc).isoformat()
        hen_count = bird_count if hen_count is None and rooster_count is None else int(hen_count or 0)
        rooster_count = int(rooster_count or 0)
        hen_daily_g = daily_per_bird_g if hen_daily_g is None else hen_daily_g
        rooster_daily_g = daily_per_bird_g if rooster_daily_g is None else rooster_daily_g
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO feed_stocks (
                    user_id, name, amount_kg, bird_count, daily_per_bird_g, low_threshold_kg,
                    bird_group_id, hen_count, rooster_count, hen_daily_g, rooster_daily_g,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    name,
                    amount_kg,
                    bird_count,
                    daily_per_bird_g,
                    low_threshold_kg,
                    bird_group_id,
                    hen_count,
                    rooster_count,
                    hen_daily_g,
                    rooster_daily_g,
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
                       fs.daily_per_bird_g, fs.low_threshold_kg, fs.hen_count,
                       fs.rooster_count, fs.hen_daily_g, fs.rooster_daily_g,
                       fs.purchase_reminded_at,
                       fs.created_at, fs.updated_at, fs.bird_group_id, bg.name AS bird_group_name,
                       bg.group_kind AS bird_group_kind, bg.hatched_at AS bird_group_hatched_at,
                       bg.joined_at AS bird_group_joined_at,
                       bg.reserve_percent AS bird_group_reserve_percent,
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
                       fs.daily_per_bird_g, fs.low_threshold_kg, fs.hen_count,
                       fs.rooster_count, fs.hen_daily_g, fs.rooster_daily_g,
                       fs.purchase_reminded_at,
                       fs.created_at, fs.updated_at, fs.bird_group_id, bg.name AS bird_group_name,
                       bg.group_kind AS bird_group_kind, bg.hatched_at AS bird_group_hatched_at,
                       bg.joined_at AS bird_group_joined_at,
                       bg.reserve_percent AS bird_group_reserve_percent,
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
                       fs.daily_per_bird_g, fs.low_threshold_kg, fs.hen_count,
                       fs.rooster_count, fs.hen_daily_g, fs.rooster_daily_g,
                       fs.purchase_reminded_at,
                       fs.created_at, fs.updated_at, fs.bird_group_id, bg.name AS bird_group_name,
                       bg.group_kind AS bird_group_kind, bg.hatched_at AS bird_group_hatched_at,
                       bg.joined_at AS bird_group_joined_at,
                       bg.reserve_percent AS bird_group_reserve_percent,
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
        hen_count: int | None = None,
        rooster_count: int | None = None,
        hen_daily_g: float | None = None,
        rooster_daily_g: float | None = None,
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
                    hen_count = ?,
                    rooster_count = ?,
                    hen_daily_g = ?,
                    rooster_daily_g = ?,
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
                    hen_count if hen_count is not None else current.hen_count,
                    rooster_count if rooster_count is not None else current.rooster_count,
                    hen_daily_g if hen_daily_g is not None else current.hen_daily_g,
                    rooster_daily_g if rooster_daily_g is not None else current.rooster_daily_g,
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
        group_kind: str = "adult",
        role: str = "mixed",
        hatched_at: date | None = None,
        joined_at: date | None = None,
        reserve_percent: float = 0.0,
    ) -> BirdGroup:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO bird_groups (
                    user_id, name, bird_count, species, group_kind, hatched_at,
                    joined_at, reserve_percent, role, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    name,
                    bird_count,
                    species,
                    group_kind,
                    hatched_at.isoformat() if hatched_at else None,
                    joined_at.isoformat() if joined_at else None,
                    reserve_percent,
                    role,
                    now,
                    now,
                ),
            )
            group_id = int(cursor.lastrowid)
        return self.get_bird_group(group_id, user_id)

    def get_bird_group(self, group_id: int, user_id: int) -> BirdGroup | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, name, bird_count, species, group_kind, hatched_at,
                       joined_at, reserve_percent, role, is_active, created_at, updated_at
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
                SELECT id, user_id, name, bird_count, species, group_kind, hatched_at,
                       joined_at, reserve_percent, role, is_active, created_at, updated_at
                FROM bird_groups
                WHERE user_id = ? AND is_active = 1
                ORDER BY created_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._bird_group_from_row(row) for row in rows]

    def update_bird_group(
        self,
        *,
        group_id: int,
        user_id: int,
        name: str | None = None,
        bird_count: int | None = None,
        role: str | None = None,
        hatched_at: date | None = None,
        joined_at: date | None = None,
        reserve_percent: float | None = None,
    ) -> BirdGroup | None:
        current = self.get_bird_group(group_id, user_id)
        if current is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE bird_groups
                SET name = ?,
                    bird_count = ?,
                    role = ?,
                    hatched_at = ?,
                    joined_at = ?,
                    reserve_percent = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    name if name is not None else current.name,
                    bird_count if bird_count is not None else current.bird_count,
                    role if role is not None else current.role,
                    (hatched_at if hatched_at is not None else current.hatched_at).isoformat()
                    if (hatched_at if hatched_at is not None else current.hatched_at)
                    else None,
                    (joined_at if joined_at is not None else current.joined_at).isoformat()
                    if (joined_at if joined_at is not None else current.joined_at)
                    else None,
                    reserve_percent if reserve_percent is not None else current.reserve_percent,
                    now,
                    group_id,
                    user_id,
                ),
            )
        return self.get_bird_group(group_id, user_id)

    def archive_bird_group(self, group_id: int, user_id: int) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE bird_groups
                SET is_active = 0, updated_at = ?
                WHERE id = ? AND user_id = ? AND is_active = 1
                """,
                (now, group_id, user_id),
            )
            connection.execute(
                """
                UPDATE flock_members
                SET is_active = 0, left_at = ?
                WHERE user_id = ? AND bird_group_id = ? AND is_active = 1
                """,
                (now, user_id, group_id),
            )
        return cursor.rowcount > 0

    def create_flock(self, *, user_id: int, name: str) -> Flock:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO flocks (user_id, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, name, now, now),
            )
            flock_id = int(cursor.lastrowid)
        return self.get_flock(flock_id, user_id)

    def get_flock(self, flock_id: int, user_id: int) -> Flock | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, name, is_active, created_at, updated_at
                FROM flocks
                WHERE id = ? AND user_id = ?
                """,
                (flock_id, user_id),
            ).fetchone()
        return self._flock_from_row(row) if row else None

    def list_flocks(self, user_id: int) -> list[Flock]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, name, is_active, created_at, updated_at
                FROM flocks
                WHERE user_id = ? AND is_active = 1
                ORDER BY created_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._flock_from_row(row) for row in rows]

    def update_flock(
        self,
        *,
        flock_id: int,
        user_id: int,
        name: str | None = None,
    ) -> Flock | None:
        current = self.get_flock(flock_id, user_id)
        if current is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE flocks
                SET name = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    name if name is not None else current.name,
                    now,
                    flock_id,
                    user_id,
                ),
            )
        return self.get_flock(flock_id, user_id)

    def archive_flock(self, flock_id: int, user_id: int) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE flocks
                SET is_active = 0, updated_at = ?
                WHERE id = ? AND user_id = ? AND is_active = 1
                """,
                (now, flock_id, user_id),
            )
            connection.execute(
                """
                UPDATE flock_members
                SET is_active = 0, left_at = ?
                WHERE user_id = ? AND flock_id = ? AND is_active = 1
                """,
                (now, user_id, flock_id),
            )
            connection.execute(
                """
                UPDATE flock_feed_assignments
                SET is_active = 0, ended_at = ?
                WHERE user_id = ? AND flock_id = ? AND is_active = 1
                """,
                (now, user_id, flock_id),
            )
        return cursor.rowcount > 0

    def add_flock_member(self, *, user_id: int, flock_id: int, bird_group_id: int) -> FlockMember | None:
        now = datetime.now(timezone.utc).isoformat()
        flock = self.get_flock(flock_id, user_id)
        group = self.get_bird_group(bird_group_id, user_id)
        if flock is None or group is None or not flock.is_active or not group.is_active:
            return None
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO flock_members (user_id, flock_id, bird_group_id, joined_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, flock_id, bird_group_id, now),
            )
            connection.execute("UPDATE flocks SET updated_at = ? WHERE id = ?", (now, flock_id))
        members = [member for member in self.list_flock_members(flock_id, user_id) if member.bird_group_id == bird_group_id]
        return members[0] if members else None

    def remove_flock_member(self, *, user_id: int, flock_id: int, bird_group_id: int) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE flock_members
                SET is_active = 0, left_at = ?
                WHERE user_id = ? AND flock_id = ? AND bird_group_id = ? AND is_active = 1
                """,
                (now, user_id, flock_id, bird_group_id),
            )
            connection.execute("UPDATE flocks SET updated_at = ? WHERE id = ?", (now, flock_id))
        return cursor.rowcount > 0

    def list_flock_members(self, flock_id: int, user_id: int) -> list[FlockMember]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT fm.id, fm.user_id, fm.flock_id, fm.bird_group_id, fm.is_active,
                       fm.joined_at, fm.left_at,
                       bg.name AS bird_group_name, bg.bird_count, bg.group_kind, bg.role,
                       bg.hatched_at, bg.joined_at AS group_joined_at, bg.reserve_percent
                FROM flock_members AS fm
                LEFT JOIN bird_groups AS bg ON bg.id = fm.bird_group_id
                WHERE fm.user_id = ? AND fm.flock_id = ? AND fm.is_active = 1
                ORDER BY fm.joined_at, fm.id
                """,
                (user_id, flock_id),
            ).fetchall()
        return [self._flock_member_from_row(row) for row in rows]

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
            hen_count=int(row["hen_count"]) if "hen_count" in row.keys() else int(row["bird_count"]),
            rooster_count=int(row["rooster_count"]) if "rooster_count" in row.keys() else 0,
            hen_daily_g=(
                float(row["hen_daily_g"])
                if "hen_daily_g" in row.keys() and row["hen_daily_g"] is not None
                else float(row["daily_per_bird_g"])
            ),
            rooster_daily_g=(
                float(row["rooster_daily_g"])
                if "rooster_daily_g" in row.keys() and row["rooster_daily_g"] is not None
                else float(row["daily_per_bird_g"])
            ),
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
            bird_group_kind=(
                str(row["bird_group_kind"])
                if "bird_group_kind" in row.keys() and row["bird_group_kind"] is not None
                else None
            ),
            bird_group_hatched_at=(
                date.fromisoformat(str(row["bird_group_hatched_at"]))
                if "bird_group_hatched_at" in row.keys()
                and row["bird_group_hatched_at"] is not None
                else None
            ),
            bird_group_joined_at=(
                date.fromisoformat(str(row["bird_group_joined_at"]))
                if "bird_group_joined_at" in row.keys()
                and row["bird_group_joined_at"] is not None
                else None
            ),
            bird_group_reserve_percent=(
                float(row["bird_group_reserve_percent"])
                if "bird_group_reserve_percent" in row.keys()
                and row["bird_group_reserve_percent"] is not None
                else 0.0
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
            group_kind=(
                str(row["group_kind"])
                if "group_kind" in row.keys() and row["group_kind"] is not None
                else "adult"
            ),
            role=(
                str(row["role"])
                if "role" in row.keys() and row["role"] is not None
                else ("chicks" if row["group_kind"] == "chicks" else "mixed")
            ),
            hatched_at=(
                date.fromisoformat(str(row["hatched_at"]))
                if "hatched_at" in row.keys() and row["hatched_at"] is not None
                else None
            ),
            joined_at=(
                date.fromisoformat(str(row["joined_at"]))
                if "joined_at" in row.keys() and row["joined_at"] is not None
                else None
            ),
            reserve_percent=(
                float(row["reserve_percent"])
                if "reserve_percent" in row.keys() and row["reserve_percent"] is not None
                else 0.0
            ),
        )

    @staticmethod
    def _flock_from_row(row: sqlite3.Row) -> Flock:
        return Flock(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            name=str(row["name"]),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _flock_member_from_row(row: sqlite3.Row) -> FlockMember:
        return FlockMember(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            flock_id=int(row["flock_id"]),
            bird_group_id=int(row["bird_group_id"]),
            is_active=bool(row["is_active"]),
            joined_at=datetime.fromisoformat(str(row["joined_at"])),
            left_at=datetime.fromisoformat(str(row["left_at"])) if row["left_at"] else None,
            bird_group_name=str(row["bird_group_name"]) if row["bird_group_name"] else None,
            bird_count=int(row["bird_count"] or 0),
            group_kind=str(row["group_kind"] or "adult"),
            role=str(row["role"] or ("chicks" if row["group_kind"] == "chicks" else "mixed")),
            hatched_at=date.fromisoformat(str(row["hatched_at"])) if row["hatched_at"] else None,
            group_joined_at=date.fromisoformat(str(row["group_joined_at"])) if row["group_joined_at"] else None,
            reserve_percent=float(row["reserve_percent"] or 0),
        )
