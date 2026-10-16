"""Charts page: eggs per day, feed per day, sales per week — server-drawn SVG, with a table view."""

from __future__ import annotations

from datetime import date, timedelta
from html import escape
import math

from fastapi import Depends, FastAPI, Query
from fastapi.responses import HTMLResponse

from app.storage.database import Database


W, H = 720, 220
PAD_L, PAD_R, PAD_T, PAD_B = 44, 12, 14, 28


def _nice_max(value: float) -> float:
    """Top of the axis so that 4 equal ticks land on round numbers (1, 2, 5 × 10^k)."""
    if value <= 0:
        return 4.0
    raw_step = value / 4
    exp = 10 ** math.floor(math.log10(raw_step))
    for step in (1, 2, 5, 10):
        if raw_step <= step * exp:
            return step * exp * 4
    return 40 * exp


def _fmt(value: float, unit: str) -> str:
    if unit == "₽":
        return f"{round(value):,}".replace(",", " ") + " ₽"
    if unit == "кг":
        return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " кг"
    return f"{value:g}"


def column_chart(
    labels: list[str],
    values: list[float],
    *,
    unit: str,
    title: str,
    tips: list[str] | None = None,
    line: list[float | None] | None = None,
    line_name: str = "",
    bar_name: str = "",
) -> str:
    """Columns from one baseline (4px rounded tops, 2px gaps), optional 2px line, hairline grid."""
    n = len(values)
    if n == 0:
        return "<p class=\"small\">Данных пока нет.</p>"
    top = _nice_max(max([*values, *[v for v in (line or []) if v is not None], 0]))
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    slot = plot_w / n
    bar_w = max(min(slot - 2, 24), 1.5)

    def y(value: float) -> float:
        return PAD_T + plot_h * (1 - value / top)

    parts = [
        f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">'
    ]
    for i in range(5):
        tick = top * i / 4
        ty = y(tick)
        parts.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
        parts.append(f'<text class="axis" x="{PAD_L - 6}" y="{ty + 4:.1f}" text-anchor="end">{escape(_fmt(tick, unit) if unit != "₽" else f"{round(tick):,}".replace(",", " "))}</text>')
    label_every = max(1, math.ceil(n / 10))
    for i, value in enumerate(values):
        x = PAD_L + slot * i + (slot - bar_w) / 2
        tip = escape((tips or labels)[i] + ": " + _fmt(value, unit))
        parts.append(f'<g class="mark"><title>{tip}</title>')
        parts.append(f'<rect class="hit" x="{PAD_L + slot * i:.1f}" y="{PAD_T}" width="{slot:.1f}" height="{plot_h}"/>')
        if value > 0:
            top_y, base = y(value), y(0)
            r = min(4, bar_w / 2, base - top_y)
            parts.append(
                f'<path class="bar" d="M{x:.1f},{base:.1f} V{top_y + r:.1f} Q{x:.1f},{top_y:.1f} {x + r:.1f},{top_y:.1f} '
                f'H{x + bar_w - r:.1f} Q{x + bar_w:.1f},{top_y:.1f} {x + bar_w:.1f},{top_y + r:.1f} V{base:.1f} Z"/>'
            )
        parts.append("</g>")
        if i % label_every == 0 or i == n - 1:
            parts.append(f'<text class="axis" x="{PAD_L + slot * i + slot / 2:.1f}" y="{H - 8}" text-anchor="middle">{escape(labels[i])}</text>')
    if line:
        points = [
            f"{PAD_L + slot * i + slot / 2:.1f},{y(v):.1f}" for i, v in enumerate(line) if v is not None
        ]
        if len(points) > 1:
            parts.append(f'<polyline class="trend" points="{" ".join(points)}"/>')
    parts.append(f'<line class="base" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    parts.append("</svg>")
    legend = ""
    if line:
        legend = (
            '<div class="legend"><span><i class="key bar-key"></i>' + escape(bar_name) + "</span>"
            '<span><i class="key line-key"></i>' + escape(line_name) + "</span></div>"
        )
    rows = "".join(
        f"<tr><td>{escape((tips or labels)[i])}</td><td>{escape(_fmt(v, unit))}</td></tr>" for i, v in enumerate(values)
    )
    table = (
        f'<details><summary>Таблица</summary><table><thead><tr><th>Период</th><th>{escape(title)}</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></details>"
    )
    return legend + '<div class="chart-wrap">' + "".join(parts) + "</div>" + table


CHART_STYLE = """
  <style>
    .chart-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .chart { width: 100%; min-width: 560px; height: auto; display: block; }
    .chart .grid { stroke: var(--line); stroke-width: 1; }
    .chart .base { stroke: var(--muted); stroke-width: 1; }
    .chart .axis { fill: var(--muted); font-size: 11px; }
    .chart .bar { fill: var(--accent); }
    .chart .hit { fill: transparent; }
    .chart .mark:hover .bar { filter: brightness(1.2); }
    .chart .mark:hover .hit { fill: color-mix(in srgb, var(--accent) 10%, transparent); }
    .chart .trend { fill: none; stroke: var(--ink, #1f2a24); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
    .legend { display: flex; gap: 16px; font-size: 13px; color: var(--muted); margin: 0 0 6px; }
    .legend .key { display: inline-block; width: 12px; height: 12px; margin-right: 6px; vertical-align: -1px; border-radius: 3px; }
    .legend .bar-key { background: var(--accent); }
    .legend .line-key { height: 2px; vertical-align: 4px; background: var(--ink, #1f2a24); }
    .range a { margin-right: 10px; }
    .range a.active { font-weight: 700; text-decoration: none; color: inherit; }
  </style>"""


def _series(database: Database, user_id: int, *, start: date, end: date) -> dict:
    with database.connect() as c:
        eggs = {
            date.fromisoformat(r["d"]): int(r["n"])
            for r in c.execute(
                "SELECT entry_date AS d, SUM(eggs_count) AS n FROM egg_entries WHERE user_id = ? AND entry_date BETWEEN ? AND ? GROUP BY entry_date",
                (user_id, start.isoformat(), end.isoformat()),
            )
        }
        feed = {}
        for r in c.execute(
            """
            SELECT fed_date AS d, SUM(COALESCE(mix_kg, 0)) AS kg, MAX(daily_norm_kg) AS norm, COUNT(mix_kg) AS measured
            FROM feeding_events WHERE user_id = ? AND fed_date BETWEEN ? AND ? GROUP BY fed_date
            """,
            (user_id, start.isoformat(), end.isoformat()),
        ):
            feed[date.fromisoformat(r["d"])] = float(r["kg"]) if r["measured"] else float(r["norm"] or 0)
        sales = [
            (date.fromisoformat(r["occurred_on"]), float(r["amount_rub"] or 0), int(r["eggs_count"]))
            for r in c.execute(
                "SELECT occurred_on, amount_rub, eggs_count FROM egg_outflows WHERE user_id = ? AND kind = 'sold' AND occurred_on BETWEEN ? AND ?",
                (user_id, start.isoformat(), end.isoformat()),
            )
        ]
    return {"eggs": eggs, "feed": feed, "sales": sales}


def charts_body(database: Database, user_id: int, *, today: date, days: int, auth_token: str) -> str:
    from app.web.main import _link

    start = today - timedelta(days=days - 1)
    data = _series(database, user_id, start=start, end=today)
    day_list = [start + timedelta(days=i) for i in range(days)]
    labels = [d.strftime("%d.%m") for d in day_list]
    egg_values = [float(data["eggs"].get(d, 0)) for d in day_list]
    avg = []
    for i, d in enumerate(day_list):
        window = [data["eggs"][x] for x in day_list[max(0, i - 6): i + 1] if x in data["eggs"]]
        avg.append(sum(window) / len(window) if len(window) >= 3 else None)
    total_eggs = sum(egg_values)
    recorded = len(data["eggs"])
    feed_values = [round(data["feed"].get(d, 0.0), 2) for d in day_list]
    weeks = max(days // 7, 1)
    week_starts = [today - timedelta(days=7 * (weeks - 1 - i) + 6) for i in range(weeks)]
    week_labels = [w.strftime("%d.%m") for w in week_starts]
    revenue = [0.0] * weeks
    sold = [0] * weeks
    for occurred, amount, count in data["sales"]:
        for i, w in enumerate(week_starts):
            if w <= occurred <= w + timedelta(days=6):
                revenue[i] += amount
                sold[i] += count
    range_links = " ".join(
        f'<a href="{escape(_link("/charts", auth_token) + ("&" if auth_token else "?") + f"days={n}")}" '
        f'class="{"active" if n == days else ""}">{n} дней</a>'
        for n in (30, 90)
    )
    sales_block = (
        column_chart(
            week_labels,
            revenue,
            unit="₽",
            title="Выручка",
            tips=[f"Неделя с {w.strftime('%d.%m')} (продано {sold[i]} яиц)" for i, w in enumerate(week_starts)],
        )
        if any(revenue)
        else '<p class="small">Продаж за этот период не записано. Записывайте их в «Яйца → Продажа и раздача».</p>'
    )
    feed_block = (
        column_chart(labels, feed_values, unit="кг", title="Смеси за день", tips=[d.strftime("%d.%m.%Y") for d in day_list])
        if any(feed_values)
        else '<p class="small">Отметок «Покормил» за этот период нет.</p>'
    )
    return f"""
  {CHART_STYLE}
  <p class="range">Период: {range_links}</p>
  <h2>Яйца по дням</h2>
  <p class="small">За {days} дн. собрано {int(total_eggs)} яиц, записи есть за {recorded} дн.; в среднем {f"{total_eggs / recorded if recorded else 0:.1f}".replace(".", ",")} в день в дни с записью.</p>
  {column_chart(labels, egg_values, unit="шт", title="Яиц за день", tips=[d.strftime("%d.%m.%Y") for d in day_list], line=avg, line_name="среднее за 7 дней", bar_name="яиц за день")}
  <h2>Расход смеси</h2>
  <p class="small">По отметкам «Покормил»: по кружкам, а если количество не указано — по норме стада.</p>
  {feed_block}
  <h2>Продажи яиц по неделям, ₽</h2>
  {sales_block}
  <script>document.querySelectorAll('.chart-wrap').forEach(function (el) {{ el.scrollLeft = el.scrollWidth; }});</script>"""


def register_chart_routes(app: FastAPI, require_web_access) -> None:
    from app.web import main as web
    from app.web.parity import _local_today, _page

    @app.get("/charts", dependencies=[Depends(require_web_access)], response_class=HTMLResponse)
    async def charts_page(
        auth: str | None = Query(default=None),
        user_id: int | None = Query(default=None),
        days: int = Query(default=30),
    ):
        current = app.state.web_config
        days = 90 if days >= 90 else 30
        selected = web._selected_user_for_write(current, user_id=user_id) if current.db_path.exists() else None
        if selected is None:
            body = "<p>Пользователь не выбран или база данных недоступна.</p>"
        else:
            body = charts_body(
                Database(current.db_path),
                selected,
                today=_local_today(current.timezone_name),
                days=days,
                auth_token=auth or "",
            )
        return HTMLResponse(_page("Графики", "Яйца, корм и продажи по дням.", auth or "", "/charts", body))
