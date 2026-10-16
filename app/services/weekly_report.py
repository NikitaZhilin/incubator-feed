"""Sunday report: the week's eggs, feed, money and what runs out soon."""

from __future__ import annotations

from datetime import date, timedelta

from app.services.feeding import FeedingService, format_kg
from app.services.ledger import LOSS_REASONS, LedgerService, format_rub
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.ledger import feed_items_between


WEEKLY_REPORT_WEEKDAY = 6  # Sunday
WEEKLY_REPORT_HOUR = 20


def _change(current: float, previous: float) -> str:
    if previous <= 0:
        return ""
    delta = (current - previous) / previous
    if abs(delta) < 0.03:
        return " (как на прошлой неделе)"
    arrow = "▲" if delta > 0 else "▼"
    return f" ({arrow} {abs(delta):.0%} к прошлой неделе: {previous:g})"


def build_weekly_report(
    *,
    user_id: int,
    today: date,
    eggs: EggRepository,
    feeding_service: FeedingService | None,
    ledger_service: LedgerService | None,
) -> str:
    start = today - timedelta(days=6)
    prev_start, prev_end = start - timedelta(days=7), start - timedelta(days=1)
    lines = [f"📅 Итоги недели {start.strftime('%d.%m')}–{today.strftime('%d.%m')}", ""]

    week_eggs = eggs.sum_between(user_id, start_date=start, end_date=today)
    prev_eggs = eggs.sum_between(user_id, start_date=prev_start, end_date=prev_end)
    recorded_days = len(eggs.entry_dates_between(user_id, start_date=start, end_date=today))
    lines.append("🥚 Яйца:")
    lines.append(f"- Собрано {week_eggs}{_change(week_eggs, prev_eggs)}; в среднем {week_eggs / 7:.1f} в день.")
    if recorded_days < 7:
        lines.append(f"- Сбор записан за {recorded_days} из 7 дней — недостающие дни можно внести «за несколько дней».")

    feed_kg = 0.0
    if feeding_service is not None:
        events = feeding_service.feeding.between(user_id, start_date=start, end_date=today)
        fed_days = len({event.fed_date for event in events})
        cups_kg = sum(event.mix_kg or 0 for event in events)
        feed_kg = cups_kg or feeding_service.week(user_id, today=today).estimated_kg
        prev_events = feeding_service.feeding.between(user_id, start_date=prev_start, end_date=prev_end)
        prev_kg = sum(event.mix_kg or 0 for event in prev_events)
        lines.extend(["", "🌾 Корм:"])
        if events:
            source = "по кружкам" if cups_kg else "по норме"
            lines.append(
                f"- Кормили {fed_days} из 7 дней, ушло ≈ {format_kg(feed_kg)} смеси ({source})"
                + (_change(round(cups_kg, 1), round(prev_kg, 1)) if cups_kg and prev_kg else "")
                + "."
            )
            if week_eggs and feed_kg:
                lines.append(f"- На десяток яиц ушло ≈ {format_kg(feed_kg / week_eggs * 10)} корма.")
        else:
            lines.append("- Отметок «✅ Покормил» за неделю нет.")
        pace = feeding_service.pace(user_id, today=today)
        if pace is not None and pace.soon_out:
            lines.append(
                "- ⚠️ Скоро закончится: "
                + "; ".join(f"{item.name} — {item.days_left} дн." for item in pace.soon_out)
            )

    if ledger_service is not None:
        prices = ledger_service.price_per_kg(user_id)
        cost = 0.0
        for item in feed_items_between(ledger_service.database, user_id, start_date=start, end_date=today):
            item_id = item.stock_item_id or ledger_service._item_id_for(user_id, item.name)
            if item_id in prices:
                cost += item.kg * prices[item_id]
        outflow = ledger_service.outflow_summary(user_id, start_date=start, end_date=today)
        money = []
        if cost > 0:
            money.append(f"- Корм за неделю ≈ {format_rub(cost)}" + (f", яйцо ≈ {format_rub(cost / week_eggs)}." if week_eggs else "."))
        if outflow.sold:
            money.append(f"- Продано {outflow.sold} яиц на {format_rub(outflow.revenue_rub)}.")
            if cost > 0:
                money.append(f"- Выручка минус корм: {format_rub(outflow.revenue_rub - cost)}.")
        if outflow.given or outflow.eaten or outflow.incubated:
            money.append(
                f"- Отдано {outflow.given}, съели {outflow.eaten}, в инкубатор {outflow.incubated}."
            )
        if money:
            lines.extend(["", "💰 Деньги и яйца:"])
            lines.extend(money)

        losses = ledger_service.ledger.losses_between(user_id, start_date=start, end_date=today)
        if losses:
            lines.extend(["", "📉 Поголовье:"])
            for loss in losses:
                lines.append(
                    f"- {loss.occurred_on.strftime('%d.%m')}: «{loss.group_name}» −{loss.count}, "
                    f"{LOSS_REASONS.get(loss.reason, loss.reason).lower()}."
                )

    return "\n".join(lines)
