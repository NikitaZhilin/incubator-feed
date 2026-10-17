"""Quick egg entry, flock age and replacement planning, incubation results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median


# --- quick egg entry ------------------------------------------------------------------


def usual_egg_counts(eggs, user_id: int, *, today: date, days: int = 14) -> list[int]:
    """Three one-tap choices around the usual daily collection (median of recent days)."""
    totals = eggs.daily_totals(user_id, start_date=today - timedelta(days=days), end_date=today - timedelta(days=1))
    if not totals:
        return []
    usual = round(median(totals.values()))
    return sorted({max(usual - 1, 0), usual, usual + 1})


def eggs_recorded_recently(eggs, user_id: int, *, today: date, days: int = 7) -> bool:
    return bool(eggs.daily_totals(user_id, start_date=today - timedelta(days=days), end_date=today - timedelta(days=1)))


def eggs_recorded_on(eggs, user_id: int, day: date) -> bool:
    return bool(eggs.daily_totals(user_id, start_date=day, end_date=day))


EGG_REMINDER_HOUR = 20


# --- flock age ------------------------------------------------------------------------

# Laying peaks in the first laying year and falls by roughly 10-20 % each following year.
REPLACE_AFTER_YEARS = 2.0
HATCH_SHARE = 0.7  # hatched chicks from set eggs, a realistic home-incubator figure
PULLET_SHARE = 0.5  # half of the chicks are cockerels


@dataclass(frozen=True)
class GroupAge:
    name: str
    role: str
    bird_count: int
    years: float


def adult_ages(groups, *, today: date) -> tuple[list[GroupAge], list]:
    """Adult groups with a hatch date, and the adult groups without one."""
    known, unknown = [], []
    for group in groups:
        if not group.is_active or group.group_kind != "adult":
            continue
        if group.hatched_at is None:
            unknown.append(group)
        else:
            known.append(GroupAge(group.name, group.role, group.bird_count, (today - group.hatched_at).days / 365.25))
    return known, unknown


def years_text(years: float) -> str:
    if years < 1:
        return f"{max(round(years * 12), 1)} мес."
    whole = int(years)
    half = years - whole >= 0.5
    if whole == 1:
        return "1,5 года" if half else "1 год"
    if 2 <= whole <= 4:
        return f"{whole},5 года" if half else f"{whole} года"
    return f"{whole},5 лет" if half else f"{whole} лет"


def eggs_to_set_for(pullets: int) -> int:
    return max(int(-(-pullets // (HATCH_SHARE * PULLET_SHARE))), 1)


def flock_age_lines(groups, *, today: date) -> list[str]:
    known, unknown = adult_ages(groups, today=today)
    lines: list[str] = []
    old_hens = 0
    for age in sorted(known, key=lambda a: -a.years):
        mark = ""
        if age.role == "hens" and age.years >= REPLACE_AFTER_YEARS:
            mark = " — несутся уже заметно меньше, пора планировать замену"
            old_hens += age.bird_count
        lines.append(f"- «{age.name}»: {age.bird_count} шт., возраст {years_text(age.years)}{mark}.")
    if old_hens:
        eggs = eggs_to_set_for(old_hens)
        lines.append(
            f"- На замену {old_hens} несушек заложите примерно {eggs} яиц: выводится около 70%, и половина — петушки. "
            "Весенний вывод (март–апрель) начнёт нестись к осени."
        )
    if unknown:
        lines.append(
            "- Без даты вывода: " + ", ".join(f"«{group.name}»" for group in unknown)
            + ". Укажите год в «Поголовье» → группа → «📅 Год вывода», чтобы бот следил за возрастом."
        )
    if not lines:
        lines.append("- Взрослых групп пока нет.")
    return lines


# --- incubation results ------------------------------------------------------------------


@dataclass(frozen=True)
class BatchResult:
    title: str
    species: str
    eggs: int
    hatched: int
    start: date

    @property
    def rate(self) -> float:
        return self.hatched / self.eggs * 100 if self.eggs else 0.0


def batch_results(batches) -> list[BatchResult]:
    return [
        BatchResult(batch.title, batch.species, batch.eggs_count, batch.hatched_count, batch.start_date)
        for batch in batches
        if not batch.is_active and batch.hatched_count is not None and batch.eggs_count > 0
    ]


# --- why eggs did not hatch ---------------------------------------------------------------


@dataclass(frozen=True)
class BatchLosses:
    infertile: int
    dead_embryo: int
    not_hatched: int

    @property
    def total(self) -> int:
        return self.infertile + self.dead_embryo + self.not_hatched


def parse_batch_losses(text: str) -> BatchLosses:
    numbers = [part for part in (text or "").replace(",", " ").replace(";", " ").split() if part]
    if len(numbers) != 3 or not all(part.isdigit() for part in numbers):
        raise ValueError("Нужно три числа через пробел: неоплод, замершие, не вылупились. Например: 3 2 1")
    return BatchLosses(*(int(part) for part in numbers))


def save_batch_losses(database, *, user_id: int, batch, losses: BatchLosses) -> None:
    if batch.is_active or batch.hatched_count is None:
        raise ValueError("Сначала завершите вывод и укажите, сколько вывелось.")
    left = batch.eggs_count - batch.hatched_count
    if losses.total > left:
        raise ValueError(f"Не вывелось {left} из {batch.eggs_count}: сумма не может быть больше.")
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO batch_losses (batch_id, user_id, infertile, dead_embryo, not_hatched, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(batch_id) DO UPDATE SET
                infertile = excluded.infertile,
                dead_embryo = excluded.dead_embryo,
                not_hatched = excluded.not_hatched,
                updated_at = CURRENT_TIMESTAMP
            """,
            (batch.id, user_id, losses.infertile, losses.dead_embryo, losses.not_hatched),
        )


def load_batch_losses(database, user_id: int) -> dict[int, BatchLosses]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT batch_id, infertile, dead_embryo, not_hatched FROM batch_losses WHERE user_id = ?", (user_id,)
        ).fetchall()
    return {int(r["batch_id"]): BatchLosses(int(r["infertile"]), int(r["dead_embryo"]), int(r["not_hatched"])) for r in rows}


LOSS_ADVICE = (
    ("infertile", "неоплод", "больше всего неоплода: проверьте петуха (возраст, активность, 1 петух на 8–12 кур) и свежесть яиц"),
    ("dead_embryo", "замершие", "больше всего замерших: проверьте точность термометра, перепады температуры, переворот и хранение яиц до закладки"),
    ("not_hatched", "не вылупились", "больше всего не вылупившихся: обычно мала влажность на выводе или не хватает вентиляции в последние 3 дня"),
)


def losses_lines(batches, losses: dict[int, BatchLosses]) -> list[str]:
    rows = [(b, losses[b.id]) for b in batches if b.id in losses]
    if not rows:
        return []
    eggs = sum(b.eggs_count for b, _ in rows)
    totals = {
        "infertile": sum(l.infertile for _, l in rows),
        "dead_embryo": sum(l.dead_embryo for _, l in rows),
        "not_hatched": sum(l.not_hatched for _, l in rows),
    }
    lines = [
        "",
        f"Почему не вывелись (по {len(rows)} парт., {eggs} яиц): "
        f"неоплод {totals['infertile']}, замершие {totals['dead_embryo']}, не вылупились {totals['not_hatched']}.",
    ]
    if sum(totals.values()):
        key = max(totals, key=totals.get)
        advice = next(text for code, _, text in LOSS_ADVICE if code == key)
        lines.append(f"Главная потеря — {advice}.")
    return lines


def incubation_results_lines(batches, species_titles: dict[str, str], losses: dict[int, BatchLosses] | None = None) -> list[str]:
    results = batch_results(batches)
    if not results:
        return ["Завершённых партий с числом выведенных пока нет: при завершении партии укажите, сколько вывелось."]
    lines = ["По видам:"]
    for species in sorted({r.species for r in results}):
        rows = [r for r in results if r.species == species]
        eggs = sum(r.eggs for r in rows)
        hatched = sum(r.hatched for r in rows)
        lines.append(
            f"- {species_titles.get(species, species)}: {len(rows)} парт., заложено {eggs}, вывелось {hatched} "
            f"({hatched / eggs * 100:.0f}%)."
        )
    lines.extend(["", "Партии:"])
    for r in sorted(results, key=lambda r: r.start, reverse=True)[:10]:
        lines.append(f"- {r.start.strftime('%d.%m.%Y')} {r.title}: {r.hatched} из {r.eggs} ({r.rate:.0f}%)")
    if len(results) >= 2:
        best = max(results, key=lambda r: r.rate)
        worst = min(results, key=lambda r: r.rate)
        if best.rate - worst.rate >= 15:
            lines.extend(
                [
                    "",
                    f"Лучшая партия — «{best.title}» ({best.rate:.0f}%), худшая — «{worst.title}» ({worst.rate:.0f}%). "
                    "Сравните их: свежесть яиц, температура и влажность, переворот, сезон.",
                ]
            )
    lines.extend(losses_lines(batches, losses or {}))
    if not losses:
        lines.extend(["", "Укажите у завершённых партий, почему не вывелись («📝 Почему не вывелись») — бот подскажет, что проверить."])
    lines.extend(
        [
            "",
            "Ориентир для домашнего инкубатора — около 70–80% от заложенных яиц. Сильно ниже — проверьте "
            "оплодотворённость на овоскопе, точность термометра, влажность на выводе и возраст яиц (не старше 7–10 дней).",
        ]
    )
    return lines
