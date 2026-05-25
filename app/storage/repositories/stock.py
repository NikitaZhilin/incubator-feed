from datetime import datetime, timezone
import sqlite3

from app.domain import (
    FeedingAssignment,
    MixProduction,
    MixProductionItem,
    StockItem,
    StockTransaction,
)
from app.storage.database import Database


class StockRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_or_create_item(
        self,
        *,
        user_id: int,
        name: str,
        kind: str,
        low_threshold_kg: float = 5,
    ) -> StockItem:
        clean_name = name.strip()[:255]
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, name, kind, unit, low_threshold_kg, is_active,
                       created_at, updated_at
                FROM stock_items
                WHERE user_id = ? AND lower(name) = lower(?)
                """,
                (user_id, clean_name),
            ).fetchone()
            if row:
                return self._item_from_row(row)
            now = datetime.now(timezone.utc).isoformat()
            cursor = connection.execute(
                """
                INSERT INTO stock_items (
                    user_id, name, kind, unit, low_threshold_kg, created_at, updated_at
                )
                VALUES (?, ?, ?, 'kg', ?, ?, ?)
                """,
                (user_id, clean_name, kind, low_threshold_kg, now, now),
            )
            item_id = int(cursor.lastrowid)
        return self.get_item(item_id, user_id)

    def find_item_by_name(self, *, user_id: int, name: str) -> StockItem | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, name, kind, unit, low_threshold_kg, is_active,
                       created_at, updated_at
                FROM stock_items
                WHERE user_id = ? AND lower(name) = lower(?)
                """,
                (user_id, name.strip()),
            ).fetchone()
        return self._item_from_row(row) if row else None

    def get_item(self, item_id: int, user_id: int) -> StockItem | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, name, kind, unit, low_threshold_kg, is_active,
                       created_at, updated_at
                FROM stock_items
                WHERE id = ? AND user_id = ?
                """,
                (item_id, user_id),
            ).fetchone()
        return self._item_from_row(row) if row else None

    def list_items(self, user_id: int) -> list[StockItem]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, name, kind, unit, low_threshold_kg, is_active,
                       created_at, updated_at
                FROM stock_items
                WHERE user_id = ? AND is_active = 1
                ORDER BY kind, name
                """,
                (user_id,),
            ).fetchall()
        return [self._item_from_row(row) for row in rows]

    def add_transaction(
        self,
        *,
        user_id: int,
        stock_item_id: int,
        transaction_type: str,
        amount_kg: float,
        balance_after_kg: float,
        note: str = "",
        related_mix_id: int | None = None,
        created_at: datetime | None = None,
    ) -> StockTransaction:
        timestamp = created_at or datetime.now(timezone.utc)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO stock_transactions (
                    user_id, stock_item_id, type, amount_kg, balance_after_kg,
                    note, related_mix_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    stock_item_id,
                    transaction_type,
                    amount_kg,
                    balance_after_kg,
                    note[:255],
                    related_mix_id,
                    timestamp.isoformat(),
                ),
            )
            transaction_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE stock_items SET updated_at = ? WHERE id = ?",
                (timestamp.isoformat(), stock_item_id),
            )
        return self.get_transaction(transaction_id)

    def get_transaction(self, transaction_id: int) -> StockTransaction:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, stock_item_id, type, amount_kg, balance_after_kg,
                       note, related_mix_id, created_at
                FROM stock_transactions
                WHERE id = ?
                """,
                (transaction_id,),
            ).fetchone()
        return self._transaction_from_row(row)

    def last_transaction(self, stock_item_id: int, user_id: int) -> StockTransaction | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, stock_item_id, type, amount_kg, balance_after_kg,
                       note, related_mix_id, created_at
                FROM stock_transactions
                WHERE stock_item_id = ? AND user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (stock_item_id, user_id),
            ).fetchone()
        return self._transaction_from_row(row) if row else None

    def list_transactions(self, user_id: int, limit: int = 20) -> list[StockTransaction]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, stock_item_id, type, amount_kg, balance_after_kg,
                       note, related_mix_id, created_at
                FROM stock_transactions
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._transaction_from_row(row) for row in rows]

    def create_mix_production(
        self,
        *,
        user_id: int,
        recipe_code: str,
        recipe_version: str,
        mix_count: float,
        output_stock_item_id: int,
        output_kg: float,
        created_at: datetime | None = None,
    ) -> MixProduction:
        timestamp = created_at or datetime.now(timezone.utc)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO mix_productions (
                    user_id, recipe_code, recipe_version, mix_count,
                    output_stock_item_id, output_kg, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    recipe_code,
                    recipe_version,
                    mix_count,
                    output_stock_item_id,
                    output_kg,
                    timestamp.isoformat(),
                ),
            )
            mix_id = int(cursor.lastrowid)
        return self.get_mix_production(mix_id)

    def get_mix_production(self, mix_id: int) -> MixProduction:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, recipe_code, recipe_version, mix_count,
                       output_stock_item_id, output_kg, created_at
                FROM mix_productions
                WHERE id = ?
                """,
                (mix_id,),
            ).fetchone()
        return self._mix_from_row(row)

    def add_mix_item(
        self,
        *,
        mix_production_id: int,
        ingredient_stock_item_id: int,
        ingredient_name: str,
        amount_kg: float,
    ) -> MixProductionItem:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO mix_production_items (
                    mix_production_id, ingredient_stock_item_id, ingredient_name, amount_kg
                )
                VALUES (?, ?, ?, ?)
                """,
                (mix_production_id, ingredient_stock_item_id, ingredient_name, amount_kg),
            )
            item_id = int(cursor.lastrowid)
            row = connection.execute(
                """
                SELECT id, mix_production_id, ingredient_stock_item_id, ingredient_name, amount_kg
                FROM mix_production_items
                WHERE id = ?
                """,
                (item_id,),
            ).fetchone()
        return self._mix_item_from_row(row)

    def create_assignment(
        self,
        *,
        user_id: int,
        bird_group_id: int,
        stock_item_id: int,
        daily_per_bird_g: float = 120,
        reserve_percent: float = 0,
        started_at: datetime | None = None,
    ) -> FeedingAssignment:
        timestamp = started_at or datetime.now(timezone.utc)
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE feeding_assignments
                SET is_active = 0, ended_at = ?
                WHERE user_id = ? AND bird_group_id = ? AND is_active = 1
                """,
                (timestamp.isoformat(), user_id, bird_group_id),
            )
            cursor = connection.execute(
                """
                INSERT INTO feeding_assignments (
                    user_id, bird_group_id, stock_item_id, daily_per_bird_g,
                    reserve_percent, started_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    bird_group_id,
                    stock_item_id,
                    daily_per_bird_g,
                    reserve_percent,
                    timestamp.isoformat(),
                ),
            )
            assignment_id = int(cursor.lastrowid)
        return self.get_assignment(assignment_id)

    def get_assignment(self, assignment_id: int) -> FeedingAssignment:
        with self.database.connect() as connection:
            row = connection.execute(
                self._assignment_sql("fa.id = ?"),
                (assignment_id,),
            ).fetchone()
        return self._assignment_from_row(row)

    def list_assignments(self, user_id: int) -> list[FeedingAssignment]:
        with self.database.connect() as connection:
            rows = connection.execute(
                self._assignment_sql("fa.user_id = ? AND fa.is_active = 1"),
                (user_id,),
            ).fetchall()
        return [self._assignment_from_row(row) for row in rows]

    def list_assignments_for_item(self, user_id: int, stock_item_id: int) -> list[FeedingAssignment]:
        with self.database.connect() as connection:
            rows = connection.execute(
                self._assignment_sql(
                    "fa.user_id = ? AND fa.stock_item_id = ? AND fa.is_active = 1"
                ),
                (user_id, stock_item_id),
            ).fetchall()
        return [self._assignment_from_row(row) for row in rows]

    @staticmethod
    def _assignment_sql(where: str) -> str:
        return f"""
            SELECT fa.id, fa.user_id, fa.bird_group_id, fa.stock_item_id,
                   fa.is_active, fa.started_at, fa.ended_at,
                   fa.daily_per_bird_g, fa.reserve_percent,
                   bg.name AS bird_group_name, si.name AS stock_item_name
            FROM feeding_assignments AS fa
            LEFT JOIN bird_groups AS bg ON bg.id = fa.bird_group_id
            LEFT JOIN stock_items AS si ON si.id = fa.stock_item_id
            WHERE {where}
            ORDER BY fa.started_at DESC, fa.id DESC
        """

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> StockItem:
        return StockItem(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            unit=str(row["unit"]),
            low_threshold_kg=float(row["low_threshold_kg"]),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _transaction_from_row(row: sqlite3.Row) -> StockTransaction:
        return StockTransaction(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            stock_item_id=int(row["stock_item_id"]),
            type=str(row["type"]),
            amount_kg=float(row["amount_kg"]),
            balance_after_kg=float(row["balance_after_kg"]),
            note=str(row["note"] or ""),
            related_mix_id=int(row["related_mix_id"]) if row["related_mix_id"] else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _mix_from_row(row: sqlite3.Row) -> MixProduction:
        return MixProduction(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            recipe_code=str(row["recipe_code"]),
            recipe_version=str(row["recipe_version"]),
            mix_count=float(row["mix_count"]),
            output_stock_item_id=int(row["output_stock_item_id"]),
            output_kg=float(row["output_kg"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _mix_item_from_row(row: sqlite3.Row) -> MixProductionItem:
        return MixProductionItem(
            id=int(row["id"]),
            mix_production_id=int(row["mix_production_id"]),
            ingredient_stock_item_id=int(row["ingredient_stock_item_id"]),
            ingredient_name=str(row["ingredient_name"]),
            amount_kg=float(row["amount_kg"]),
        )

    @staticmethod
    def _assignment_from_row(row: sqlite3.Row) -> FeedingAssignment:
        return FeedingAssignment(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            bird_group_id=int(row["bird_group_id"]),
            stock_item_id=int(row["stock_item_id"]),
            is_active=bool(row["is_active"]),
            started_at=datetime.fromisoformat(str(row["started_at"])),
            ended_at=(
                datetime.fromisoformat(str(row["ended_at"]))
                if row["ended_at"] is not None
                else None
            ),
            daily_per_bird_g=float(row["daily_per_bird_g"]),
            reserve_percent=float(row["reserve_percent"]),
            bird_group_name=str(row["bird_group_name"]) if row["bird_group_name"] else None,
            stock_item_name=str(row["stock_item_name"]) if row["stock_item_name"] else None,
        )
