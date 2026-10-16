"""Bird losses, eggs that left the house, and purchase prices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.storage.database import Database


@dataclass(frozen=True)
class BirdLoss:
    id: int
    user_id: int
    bird_group_id: int
    group_name: str
    count: int
    reason: str
    occurred_on: date
    note: str
    group_archived: bool


@dataclass(frozen=True)
class EggOutflow:
    id: int
    user_id: int
    kind: str
    eggs_count: int
    amount_rub: float | None
    occurred_on: date
    note: str


@dataclass(frozen=True)
class PricedPurchase:
    stock_item_id: int
    name: str
    amount_kg: float
    price_rub: float
    created_at: datetime


class LedgerRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    # Bird losses -------------------------------------------------------

    def add_loss(
        self,
        *,
        user_id: int,
        bird_group_id: int,
        group_name: str,
        count: int,
        reason: str,
        occurred_on: date,
        note: str = "",
        group_archived: bool = False,
    ) -> BirdLoss:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO bird_losses (
                    user_id, bird_group_id, group_name, count, reason, occurred_on, note, group_archived
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    bird_group_id,
                    group_name[:255],
                    count,
                    reason,
                    occurred_on.isoformat(),
                    note[:255],
                    int(group_archived),
                ),
            )
            loss_id = int(cursor.lastrowid)
        return self.get_loss(loss_id, user_id)

    def get_loss(self, loss_id: int, user_id: int) -> BirdLoss | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM bird_losses WHERE id = ? AND user_id = ?", (loss_id, user_id)
            ).fetchone()
        return _loss(row) if row else None

    def delete_loss(self, loss_id: int, user_id: int) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM bird_losses WHERE id = ? AND user_id = ?", (loss_id, user_id)
            )
        return cursor.rowcount > 0

    def losses_between(self, user_id: int, *, start_date: date, end_date: date) -> list[BirdLoss]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM bird_losses
                WHERE user_id = ? AND occurred_on BETWEEN ? AND ?
                ORDER BY occurred_on DESC, id DESC
                """,
                (user_id, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return [_loss(row) for row in rows]

    def recent_losses(self, user_id: int, *, limit: int = 10) -> list[BirdLoss]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM bird_losses WHERE user_id = ? ORDER BY occurred_on DESC, id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [_loss(row) for row in rows]

    def reactivate_group(self, group_id: int, user_id: int) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE bird_groups SET is_active = 1, updated_at = ?
                WHERE id = ? AND user_id = ? AND is_active = 0
                """,
                (datetime.now().astimezone().isoformat(), group_id, user_id),
            )
        return cursor.rowcount > 0

    # Eggs out ----------------------------------------------------------

    def add_outflow(
        self,
        *,
        user_id: int,
        kind: str,
        eggs_count: int,
        amount_rub: float | None,
        occurred_on: date,
        note: str = "",
    ) -> EggOutflow:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO egg_outflows (user_id, kind, eggs_count, amount_rub, occurred_on, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, kind, eggs_count, amount_rub, occurred_on.isoformat(), note[:255]),
            )
            outflow_id = int(cursor.lastrowid)
        return self.get_outflow(outflow_id, user_id)

    def get_outflow(self, outflow_id: int, user_id: int) -> EggOutflow | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM egg_outflows WHERE id = ? AND user_id = ?", (outflow_id, user_id)
            ).fetchone()
        return _outflow(row) if row else None

    def delete_outflow(self, outflow_id: int, user_id: int) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM egg_outflows WHERE id = ? AND user_id = ?", (outflow_id, user_id)
            )
        return cursor.rowcount > 0

    def outflows_between(self, user_id: int, *, start_date: date, end_date: date) -> list[EggOutflow]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM egg_outflows
                WHERE user_id = ? AND occurred_on BETWEEN ? AND ?
                ORDER BY occurred_on DESC, id DESC
                """,
                (user_id, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return [_outflow(row) for row in rows]

    def first_outflow_date(self, user_id: int) -> date | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT MIN(occurred_on) AS first FROM egg_outflows WHERE user_id = ?", (user_id,)
            ).fetchone()
        return date.fromisoformat(row["first"]) if row and row["first"] else None

    # Prices ------------------------------------------------------------

    def set_purchase_price(self, transaction_id: int, user_id: int, price_rub: float | None) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE stock_transactions SET price_rub = ?
                WHERE id = ? AND user_id = ? AND type = 'purchase'
                """,
                (price_rub, transaction_id, user_id),
            )
        return cursor.rowcount > 0

    def recent_purchases(self, user_id: int, *, limit: int = 8) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT st.id, si.name, st.amount_kg, st.price_rub, st.created_at
                FROM stock_transactions AS st
                JOIN stock_items AS si ON si.id = st.stock_item_id
                WHERE st.user_id = ? AND st.type = 'purchase'
                ORDER BY st.created_at DESC, st.id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "amount_kg": float(row["amount_kg"]),
                "price_rub": float(row["price_rub"]) if row["price_rub"] is not None else None,
                "created_at": _parse_dt(row["created_at"]),
            }
            for row in rows
        ]

    def priced_purchases(self, user_id: int) -> list[PricedPurchase]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT st.stock_item_id, si.name, st.amount_kg, st.price_rub, st.created_at
                FROM stock_transactions AS st
                JOIN stock_items AS si ON si.id = st.stock_item_id
                WHERE st.user_id = ? AND st.type = 'purchase' AND st.price_rub IS NOT NULL
                  AND st.amount_kg > 0
                ORDER BY st.created_at, st.id
                """,
                (user_id,),
            ).fetchall()
        return [
            PricedPurchase(
                stock_item_id=int(row["stock_item_id"]),
                name=str(row["name"]),
                amount_kg=float(row["amount_kg"]),
                price_rub=float(row["price_rub"]),
                created_at=_parse_dt(row["created_at"]),
            )
            for row in rows
        ]


@dataclass(frozen=True)
class FedItem:
    name: str
    kg: float
    stock_item_id: int | None


def feed_items_between(database: Database, user_id: int, *, start_date: date, end_date: date) -> list[FedItem]:
    """Ingredients given with «Покормил» in the period, one row per ingredient and stock item."""
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT i.name AS name, i.stock_item_id AS stock_item_id, SUM(i.kg) AS kg
            FROM feeding_event_items AS i
            JOIN feeding_events AS e ON e.id = i.event_id
            WHERE e.user_id = ? AND e.fed_date BETWEEN ? AND ?
            GROUP BY i.name, i.stock_item_id
            """,
            (user_id, start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
    return [
        FedItem(
            name=str(row["name"]),
            kg=float(row["kg"] or 0),
            stock_item_id=int(row["stock_item_id"]) if row["stock_item_id"] is not None else None,
        )
        for row in rows
    ]


def _loss(row) -> BirdLoss:
    return BirdLoss(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        bird_group_id=int(row["bird_group_id"]),
        group_name=str(row["group_name"]),
        count=int(row["count"]),
        reason=str(row["reason"]),
        occurred_on=date.fromisoformat(row["occurred_on"]),
        note=str(row["note"] or ""),
        group_archived=bool(row["group_archived"]),
    )


def _outflow(row) -> EggOutflow:
    return EggOutflow(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        kind=str(row["kind"]),
        eggs_count=int(row["eggs_count"]),
        amount_rub=float(row["amount_rub"]) if row["amount_rub"] is not None else None,
        occurred_on=date.fromisoformat(row["occurred_on"]),
        note=str(row["note"] or ""),
    )


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
