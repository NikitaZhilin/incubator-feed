"""Farm ledger: bird losses, eggs that left the house, prices and the cost of an egg."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.services.feeds import FeedService
from app.storage.database import Database
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.ledger import (
    BirdLoss,
    EggOutflow,
    LedgerRepository,
    feed_items_between,
)


LOSS_REASONS = {
    "died": "Падёж",
    "culled": "Выбраковка / на мясо",
    "predator": "Хищник",
    "sold": "Продажа птицы",
    "other": "Другое",
}

OUTFLOW_KINDS = {
    "sold": "Продал",
    "given": "Отдал",
    "eaten": "Съели",
    "incubated": "В инкубатор",
}

MAX_BIRDS = 10_000
MAX_EGGS = 100_000
MAX_RUB = 10_000_000


def parse_rub(text: str) -> float:
    raw = (text or "").lower().replace("руб", "").replace("р.", "").replace("₽", "").replace("р", "")
    raw = raw.replace(" ", "").replace(",", ".").strip()
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("Нужна сумма в рублях, например 1250 или 1250,50.") from None
    if not 0 <= value <= MAX_RUB:
        raise ValueError("Сумма должна быть от 0 до 10 000 000 ₽.")
    return round(value, 2)


def parse_count(text: str, *, limit: int, what: str) -> int:
    raw = (text or "").strip().lower().replace("шт", "").replace(".", "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError(f"Нужно целое число {what} больше нуля.")
    value = int(raw)
    if value > limit:
        raise ValueError(f"Слишком большое число {what}.")
    return value


def format_rub(value: float) -> str:
    if abs(value - round(value)) < 0.005:
        return f"{round(value):,}".replace(",", " ") + " ₽"
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


@dataclass(frozen=True)
class LossSummary:
    total: int
    by_reason: dict[str, int]
    previous_total: int
    days: int

    @property
    def rising(self) -> bool:
        return self.total >= 2 and self.total > self.previous_total


@dataclass(frozen=True)
class EggOutSummary:
    sold: int
    revenue_rub: float
    given: int
    eaten: int
    incubated: int

    @property
    def total(self) -> int:
        return self.sold + self.given + self.eaten + self.incubated


@dataclass(frozen=True)
class EggBalance:
    since: date
    collected: int
    gone: int

    @property
    def at_home(self) -> int:
        return max(self.collected - self.gone, 0)


@dataclass(frozen=True)
class CostReport:
    days: int
    feed_cost_rub: float
    priced_kg: float
    unpriced_names: tuple[str, ...]
    eggs: int
    cup_cost_rub: float | None

    @property
    def per_egg_rub(self) -> float | None:
        return self.feed_cost_rub / self.eggs if self.eggs and self.feed_cost_rub > 0 else None

    @property
    def per_month_rub(self) -> float:
        return self.feed_cost_rub / self.days * 30 if self.days else 0.0


class LedgerService:
    def __init__(
        self,
        database: Database,
        feed_service: FeedService,
        *,
        feeding_service=None,
        stock_service=None,
    ) -> None:
        self.database = database
        self.ledger = LedgerRepository(database)
        self.eggs = EggRepository(database)
        self.feed_service = feed_service
        self.feeding_service = feeding_service
        self.stock_service = stock_service

    # --- losses -----------------------------------------------------------

    def record_loss(
        self,
        *,
        user_id: int,
        bird_group_id: int,
        count: int,
        reason: str,
        occurred_on: date,
        note: str = "",
    ) -> BirdLoss:
        if reason not in LOSS_REASONS:
            raise ValueError("Выберите причину из списка.")
        group = self.feed_service.get_bird_group(bird_group_id, user_id)
        if group is None or not group.is_active:
            raise ValueError("Группа поголовья не найдена.")
        if not 0 < count <= group.bird_count:
            raise ValueError(f"В группе «{group.name}» {group.bird_count} птиц: столько не может выбыть.")
        archived = count == group.bird_count
        if archived:
            self.feed_service.archive_bird_group(group.id, user_id)
        else:
            self.feed_service.update_bird_group(
                group_id=group.id, user_id=user_id, bird_count=group.bird_count - count
            )
        return self.ledger.add_loss(
            user_id=user_id,
            bird_group_id=group.id,
            group_name=group.name,
            count=count,
            reason=reason,
            occurred_on=occurred_on,
            note=note,
            group_archived=archived,
        )

    def undo_loss(self, user_id: int, loss_id: int) -> BirdLoss | None:
        loss = self.ledger.get_loss(loss_id, user_id)
        if loss is None:
            return None
        group = self.feed_service.get_bird_group(loss.bird_group_id, user_id)
        if group is not None:
            if loss.group_archived and not group.is_active:
                self.feed_service._ration_will_change(user_id)
                self.ledger.reactivate_group(group.id, user_id)
            else:
                self.feed_service.update_bird_group(
                    group_id=group.id, user_id=user_id, bird_count=group.bird_count + loss.count
                )
        self.ledger.delete_loss(loss_id, user_id)
        return loss

    def recent_losses(self, user_id: int, *, limit: int = 10) -> list[BirdLoss]:
        return self.ledger.recent_losses(user_id, limit=limit)

    def loss_summary(self, user_id: int, *, today: date, days: int = 30) -> LossSummary:
        start = today - timedelta(days=days - 1)
        current = self.ledger.losses_between(user_id, start_date=start, end_date=today)
        previous = self.ledger.losses_between(
            user_id, start_date=start - timedelta(days=days), end_date=start - timedelta(days=1)
        )
        by_reason: dict[str, int] = {}
        for loss in current:
            by_reason[loss.reason] = by_reason.get(loss.reason, 0) + loss.count
        return LossSummary(
            total=sum(loss.count for loss in current),
            by_reason=by_reason,
            previous_total=sum(loss.count for loss in previous),
            days=days,
        )

    # --- eggs out ---------------------------------------------------------

    def record_outflow(
        self,
        *,
        user_id: int,
        kind: str,
        eggs_count: int,
        amount_rub: float | None,
        occurred_on: date,
        note: str = "",
    ) -> EggOutflow:
        if kind not in OUTFLOW_KINDS:
            raise ValueError("Выберите, куда ушли яйца.")
        if not 0 < eggs_count <= MAX_EGGS:
            raise ValueError("Нужно число яиц больше нуля.")
        if kind != "sold":
            amount_rub = None
        return self.ledger.add_outflow(
            user_id=user_id,
            kind=kind,
            eggs_count=eggs_count,
            amount_rub=amount_rub,
            occurred_on=occurred_on,
            note=note,
        )

    def undo_outflow(self, user_id: int, outflow_id: int) -> EggOutflow | None:
        outflow = self.ledger.get_outflow(outflow_id, user_id)
        if outflow is None or not self.ledger.delete_outflow(outflow_id, user_id):
            return None
        return outflow

    def recent_outflows(self, user_id: int, *, today: date, days: int = 30) -> list[EggOutflow]:
        return self.ledger.outflows_between(
            user_id, start_date=today - timedelta(days=days - 1), end_date=today
        )

    def outflow_summary(self, user_id: int, *, start_date: date, end_date: date) -> EggOutSummary:
        rows = self.ledger.outflows_between(user_id, start_date=start_date, end_date=end_date)

        def count(kind: str) -> int:
            return sum(row.eggs_count for row in rows if row.kind == kind)

        return EggOutSummary(
            sold=count("sold"),
            revenue_rub=round(sum(row.amount_rub or 0 for row in rows if row.kind == "sold"), 2),
            given=count("given"),
            eaten=count("eaten"),
            incubated=count("incubated"),
        )

    def egg_balance(self, user_id: int, *, today: date) -> EggBalance | None:
        """Eggs at home, counted from the first record of eggs leaving the house."""
        since = self.ledger.first_outflow_date(user_id)
        if since is None:
            return None
        collected = self.eggs.sum_between(user_id, start_date=since, end_date=today)
        gone = sum(
            row.eggs_count for row in self.ledger.outflows_between(user_id, start_date=since, end_date=today)
        )
        return EggBalance(since=since, collected=collected, gone=gone)

    # --- prices and cost ----------------------------------------------------

    def set_purchase_price(self, user_id: int, transaction_id: int, price_rub: float | None) -> bool:
        return self.ledger.set_purchase_price(transaction_id, user_id, price_rub)

    def price_per_kg(self, user_id: int) -> dict[int, float]:
        """Rubles per kilogram by stock item: the last three priced purchases, weighted by weight."""
        by_item: dict[int, list] = {}
        for purchase in self.ledger.priced_purchases(user_id):
            by_item.setdefault(purchase.stock_item_id, []).append(purchase)
        prices = {}
        for item_id, purchases in by_item.items():
            recent = purchases[-3:]
            kg = sum(p.amount_kg for p in recent)
            if kg > 0:
                prices[item_id] = sum(p.price_rub for p in recent) / kg
        return prices

    def _item_id_for(self, user_id: int, name: str, aliases: tuple[str, ...] = ()) -> int | None:
        if self.stock_service is None:
            return None
        item = self.stock_service._find_stock_item_by_names(user_id=user_id, names=(name, *aliases))
        return item.id if item is not None else None

    def cup_cost(self, user_id: int, prices: dict[int, float] | None = None) -> float | None:
        if self.feeding_service is None:
            return None
        prices = self.price_per_kg(user_id) if prices is None else prices
        total = 0.0
        for part, kg in self.feeding_service.split_cups(user_id, 1):
            item_id = self._item_id_for(user_id, part.name, tuple(part.aliases))
            if item_id is None or item_id not in prices:
                return None
            total += kg * prices[item_id]
        return round(total, 2)

    def cost_report(self, user_id: int, *, today: date, days: int = 30) -> CostReport:
        start = today - timedelta(days=days - 1)
        prices = self.price_per_kg(user_id)
        cost = priced_kg = 0.0
        unpriced: list[str] = []
        for item in feed_items_between(self.database, user_id, start_date=start, end_date=today):
            item_id = item.stock_item_id or self._item_id_for(user_id, item.name)
            if item_id is not None and item_id in prices:
                cost += item.kg * prices[item_id]
                priced_kg += item.kg
            elif item.kg > 0 and item.name not in unpriced:
                unpriced.append(item.name)
        return CostReport(
            days=days,
            feed_cost_rub=round(cost, 2),
            priced_kg=round(priced_kg, 3),
            unpriced_names=tuple(unpriced),
            eggs=self.eggs.sum_between(user_id, start_date=start, end_date=today),
            cup_cost_rub=self.cup_cost(user_id, prices),
        )


def format_cost_report(report: CostReport, outflow: EggOutSummary | None = None) -> list[str]:
    lines = []
    if report.cup_cost_rub is not None:
        lines.append(f"- Кружка смеси стоит ≈ {format_rub(report.cup_cost_rub)}.")
    if report.feed_cost_rub > 0:
        lines.append(
            f"- На корм за {report.days} дн.: ≈ {format_rub(report.feed_cost_rub)} "
            f"(≈ {format_rub(report.per_month_rub)} в месяц)."
        )
        if report.per_egg_rub is not None:
            lines.append(
                f"- Корм на одно яйцо: ≈ {format_rub(report.per_egg_rub)} "
                f"(десяток ≈ {format_rub(report.per_egg_rub * 10)}; яиц за {report.days} дн.: {report.eggs})."
            )
    if report.unpriced_names:
        lines.append("- Нет цены для: " + ", ".join(report.unpriced_names) + " — расчёт неполный.")
    if outflow is not None and outflow.sold:
        lines.append(f"- Продано яиц: {outflow.sold} на {format_rub(outflow.revenue_rub)}.")
        if report.feed_cost_rub > 0:
            balance = outflow.revenue_rub - report.feed_cost_rub
            word = "окупили корм с запасом" if balance >= 0 else "не хватило на корм"
            lines.append(f"- Выручка минус корм: {format_rub(balance)} ({word}).")
    if not lines:
        lines.append("- Цен пока нет: укажите сумму при внесении покупки, и бот посчитает себестоимость.")
    return lines
