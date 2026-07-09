from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from math import floor
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain import StockEstimate
from app.services.eggs import EggService, EXCLUSION_REASON_LABELS
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.services.stock import StockService


DEFAULT_CONTENT = {
    "version": "fallback",
    "disclaimer": "Советы справочные и не заменяют ветеринарный осмотр.",
    "daily_care": {
        "base": [
            "Проверить чистую воду утром и вечером.",
            "Проверить кормушки и доступ птицы к корму.",
            "Осмотреть птицу.",
        ],
        "eggs": ["Записать сбор яиц за день."],
    },
    "feeding": {
        "low_mix_days_threshold": 2,
        "warning_mix_days_threshold": 7,
        "no_flocks": "Сначала создайте стадо и назначьте ему готовую смесь.",
        "no_finished_mix": "Готовой смеси на складе нет.",
    },
    "eggs": {
        "drop_percent_threshold": 20,
        "minimum_recorded_days": 3,
        "checks": [
            "проверьте свет",
            "проверьте воду",
            "проверьте корм и минералы",
        ],
    },
    "incubation": {
        "max_batches_in_today_plan": 3,
        "max_recommendations_per_batch": 2,
    },
    "red_flags": [],
    "health_observation_checklist": [
        "проверить воду, корм, сухость и поведение птицы",
    ],
}


@dataclass(frozen=True)
class FinishedMixStatus:
    remaining_kg: float
    daily_usage_kg: float
    days_left: int | None
    estimates: tuple[StockEstimate, ...]


class PoultryAdvisorService:
    def __init__(
        self,
        *,
        incubation_service: IncubationService,
        feed_service: FeedService,
        egg_service: EggService,
        stock_service: StockService,
        content: dict | None = None,
        timezone_name: str = "Europe/Moscow",
    ) -> None:
        self.incubation_service = incubation_service
        self.feed_service = feed_service
        self.egg_service = egg_service
        self.stock_service = stock_service
        self.content = content or load_poultry_advisor_content()
        self.timezone_name = timezone_name

    def build_today_plan(
        self,
        user_id: int,
        *,
        local_now: datetime | None = None,
        now_utc: datetime | None = None,
    ) -> str:
        now = now_utc or datetime.now(timezone.utc)
        local = local_now or now.astimezone(self._timezone())
        today = local.date()
        lines = [f"План птицевода на {today.isoformat()}:", ""]

        for task in self.content.get("daily_care", {}).get("base", []):
            lines.append(f"- {task}")

        lines.extend(["", "Яйца:"])
        try:
            stats = self.egg_service.stats(user_id, today=today)
            if stats.today_eggs > 0:
                lines.append(f"- Сбор за сегодня уже записан: {stats.today_eggs} шт.")
            else:
                lines.append("- Записать сбор яиц за день.")
            if stats.total_hens_count <= 0:
                lines.append("- В поголовье нет несушек: прогноз яйценоскости будет неточным.")
        except Exception:
            lines.append("- Раздел яиц сейчас не дал расчет. Проверьте запись сбора вручную.")

        lines.extend(["", "Корма и смесь:"])
        try:
            mix_status = self._finished_mix_status(user_id=user_id, now=now)
            lines.extend(self._finished_mix_lines(mix_status))
            lines.extend(self._mix_plan_lines(user_id=user_id, now=now, compact=True))
            lines.extend(self._flock_setup_warnings(user_id=user_id, now=now))
        except Exception:
            lines.append("- Расчет кормов сейчас недоступен.")

        incubation_lines = self._incubation_plan_lines(user_id=user_id)
        if incubation_lines:
            lines.extend(["", "Инкубация:"])
            lines.extend(incubation_lines)

        return "\n".join(_dedupe_blank_lines(lines))

    def build_feed_advice(
        self,
        user_id: int,
        *,
        now_utc: datetime | None = None,
    ) -> str:
        now = now_utc or datetime.now(timezone.utc)
        lines = ["Корма и замес:", ""]
        reports = self.stock_service.list_flock_reports(user_id, now=now)
        if not reports:
            lines.append(f"- {self.content.get('feeding', {}).get('no_flocks', DEFAULT_CONTENT['feeding']['no_flocks'])}")
            lines.append("- Добавьте поголовье, создайте стадо и назначьте ему готовую смесь.")
            return "\n".join(lines)

        has_assignment = False
        for report in reports:
            lines.append(f"{report.flock.name}:")
            if not report.assignments:
                lines.append("- Смесь не назначена, расход не считается.")
                continue
            for usage in report.assignments:
                has_assignment = True
                stock_name = usage.assignment.stock_item_name or "готовая смесь"
                lines.append(
                    f"- {stock_name}: расход {_format_kg(usage.daily_usage_kg)}/день, "
                    f"остаток {_format_kg(usage.remaining_kg)}, хватит {_format_days(usage.days_left)}."
                )
                if usage.total_days_left is not None:
                    lines.append(
                        f"- С учетом возможного замеса запас примерно на {_format_days(usage.total_days_left)}."
                    )
                if usage.missing_ingredient_names:
                    lines.append("- Для следующего замеса не хватает: " + ", ".join(usage.missing_ingredient_names[:5]) + ".")
                elif usage.producible_mix_count > 0:
                    lines.append(
                        f"- По складу можно сделать {usage.producible_mix_count} замес(ов), "
                        f"это примерно {_format_kg(usage.producible_mix_kg)}."
                    )
            lines.append("")

        if not has_assignment:
            lines.append("- Ни одному стаду не назначена готовая смесь. Сначала назначьте смесь стаду.")

        if has_assignment:
            lines.extend(self._mix_plan_lines(user_id=user_id, now=now, compact=False))
        return "\n".join(_dedupe_blank_lines(lines))

    def build_mix_timing_advice(
        self,
        user_id: int,
        *,
        now_utc: datetime | None = None,
        local_now: datetime | None = None,
    ) -> str:
        now = now_utc or datetime.now(timezone.utc)
        local = local_now or now.astimezone(self._timezone())
        status = self._finished_mix_status(user_id=user_id, now=now)
        lines = ["Когда делать замес:", ""]
        lines.extend(self._finished_mix_lines(status))

        if status.daily_usage_kg <= 0:
            lines.append("- Срок замеса не посчитать: стадам не назначена смесь или расход равен нулю.")
        elif status.remaining_kg <= 0:
            lines.append("- Замес нужен сейчас: готовой смеси на складе нет.")
        elif status.days_left is not None and status.days_left <= self._low_mix_days_threshold():
            lines.append(f"- Замес нужен сегодня или завтра: смеси осталось примерно на {status.days_left} дн.")
        elif status.days_left is not None:
            exhausted_on = (local + timedelta(days=status.days_left)).date()
            lines.append(f"- При текущем расходе смесь закончится примерно {exhausted_on.isoformat()}.")

        lines.extend(self._mix_plan_lines(user_id=user_id, now=now, compact=False))
        return "\n".join(_dedupe_blank_lines(lines))

    def build_egg_drop_advice(
        self,
        user_id: int,
        *,
        today: date | None = None,
    ) -> str:
        current_date = today or self.egg_service.current_date()
        stats = self.egg_service.stats(user_id, today=current_date)
        entries = self.egg_service.list_entries(user_id, limit=40)
        recent_entries = [entry for entry in entries if entry.entry_date >= current_date - timedelta(days=29)]
        recorded_days = len({entry.entry_date for entry in recent_entries})
        lines = ["Мало яиц: что проверить", ""]

        if stats.total_hens_count <= 0:
            lines.append("- В поголовье нет групп с ролью `несушки`.")
            lines.append("- Добавьте несушек или поменяйте роль взрослой группы, иначе расчет яйценоскости будет нулевым.")
            return "\n".join(lines)

        minimum_days = int(self.content.get("eggs", {}).get("minimum_recorded_days", 3))
        if recorded_days < minimum_days:
            lines.append(f"- Данных пока мало: записей есть за {recorded_days} дн., нужно хотя бы {minimum_days}.")
            lines.append("- Записывайте сбор яиц каждый день, потом сравнение станет полезным.")
        else:
            lines.append(
                f"- Сейчас в расчете {stats.active_hens_count} активных несушек из {stats.total_hens_count}."
            )
            lines.append(
                f"- Среднее за 7 дней: {stats.week_average:.1f} шт./день; "
                f"за 30 дней: {stats.month_average:.1f} шт./день."
            )
            if stats.month_average > 0:
                drop_percent = max((stats.month_average - stats.week_average) / stats.month_average * 100, 0)
                threshold = float(self.content.get("eggs", {}).get("drop_percent_threshold", 20))
                if drop_percent >= threshold:
                    lines.append(f"- Есть просадка: неделя ниже месячного среднего примерно на {drop_percent:.0f}%.")
                else:
                    lines.append("- Сильной просадки по 7/30 дням не видно, но условия все равно стоит проверить.")

        if stats.active_exclusions:
            lines.append("- Временно не несутся:")
            for exclusion in stats.active_exclusions[:5]:
                reason = EXCLUSION_REASON_LABELS.get(exclusion.reason, exclusion.reason)
                until = f" до {exclusion.expected_until.isoformat()}" if exclusion.expected_until else ""
                lines.append(f"  - {exclusion.hens_count} шт.: {reason}{until}.")

        if stats.weather_note:
            lines.append(f"- Погода: {stats.weather_note}")

        lines.append("")
        lines.append("Проверки на сегодня:")
        for check in self.content.get("eggs", {}).get("checks", [])[:7]:
            lines.append(f"- {check}.")
        lines.append("- Если есть вялость, кровь, тяжелое дыхание или массовая проблема, используйте сценарий `Проблема с птицей`.")
        return "\n".join(_dedupe_blank_lines(lines))

    def build_incubation_today_advice(
        self,
        user_id: int,
        *,
        today: date | None = None,
    ) -> str:
        current_date = today or date.today()
        lines = ["Инкубация сегодня:", ""]
        statuses = self.incubation_service.get_user_statuses(user_id)
        if not statuses:
            lines.append("- Активных партий нет. Если есть новая закладка, добавьте партию в разделе `Инкубация`.")
            return "\n".join(lines)

        for status in statuses:
            lines.append(
                f"{status.batch.title}: день {status.day}, {status.stage}, "
                f"до вывода {_format_days(status.days_left)}."
            )
            recommendations = status.recommendations[:3]
            if status.day >= status.profile.lockdown_from_day:
                lines.append("- Важный этап: не переворачивайте яйца и следите за влажностью.")
            for recommendation in recommendations:
                lines.append(f"- {recommendation}")
            lines.append("")
        return "\n".join(_dedupe_blank_lines(lines))

    def build_health_red_flags_advice(self) -> str:
        lines = [
            "Проблема с птицей: красные флаги",
            "",
            "Это ситуация риска.",
            "",
            "Что сделать сейчас:",
            "1. Изолировать больную птицу от стада.",
            "2. Дать доступ к чистой воде.",
            "3. Проверить тепло, сухость и вентиляцию.",
            "4. Убрать подозрительный корм.",
            "5. Связаться с ветеринаром.",
            "",
            "Я не ставлю диагнозы и не назначаю лекарства по переписке.",
            "",
            "К красным флагам относятся:",
        ]
        for item in self.content.get("red_flags", []):
            title = str(item.get("title", "")).strip()
            if title:
                lines.append(f"- {title}.")
        return "\n".join(lines)

    def build_health_observation_advice(self) -> str:
        lines = [
            "Проблема с птицей: наблюдение",
            "",
            "Если красных флагов нет, начните с простых проверок:",
        ]
        for item in self.content.get("health_observation_checklist", []):
            lines.append(f"- {item}.")
        lines.extend(
            [
                "",
                "Если состояние ухудшается, симптомов становится больше или болеют несколько птиц, обратитесь к ветеринару.",
            ]
        )
        return "\n".join(lines)

    def build_daily_summary_advice_lines(
        self,
        user_id: int,
        *,
        local_now: datetime,
        now_utc: datetime | None = None,
        settings: dict | None = None,
        limit: int = 3,
    ) -> list[str]:
        if settings is not None and not bool(settings.get("notify_poultry_advisor", True)):
            return []
        now = now_utc or datetime.now(timezone.utc)
        lines: list[str] = []

        try:
            status = self._finished_mix_status(user_id=user_id, now=now)
            if status.daily_usage_kg <= 0:
                lines.append("назначьте готовую смесь стаду, чтобы считать расход.")
            elif status.remaining_kg <= 0:
                lines.append("готовой смеси нет, нужен замес или пополнение склада.")
            elif status.days_left is not None and status.days_left <= self._low_mix_days_threshold():
                lines.append(f"смеси осталось примерно на {status.days_left} дн., пора готовить замес.")
        except Exception:
            pass

        try:
            stats = self.egg_service.stats(user_id, today=local_now.date())
            if stats.total_hens_count > 0 and stats.today_eggs == 0:
                lines.append("запишите сбор яиц за сегодня.")
            elif stats.total_hens_count <= 0:
                groups = self.feed_service.list_bird_groups(user_id)
                if any(group.is_active and group.group_kind == "adult" for group in groups):
                    lines.append("взрослые группы есть, но несушки не выделены для расчета яиц.")
        except Exception:
            pass

        try:
            statuses = self.incubation_service.get_user_statuses(user_id)
            if statuses:
                first = statuses[0]
                if first.recommendations:
                    lines.append(f"{first.batch.title}: день {first.day}, {first.recommendations[0]}")
        except Exception:
            pass

        return lines[:limit]

    def _finished_mix_status(self, *, user_id: int, now: datetime) -> FinishedMixStatus:
        estimates = tuple(
            estimate
            for estimate in self.stock_service.list_estimates(user_id, now=now)
            if estimate.item.kind == "finished_mix"
        )
        remaining_kg = sum(max(estimate.remaining_kg, 0) for estimate in estimates)
        daily_usage_kg = sum(max(estimate.daily_usage_kg, 0) for estimate in estimates)
        days_left = floor(remaining_kg / daily_usage_kg) if daily_usage_kg > 0 else None
        return FinishedMixStatus(
            remaining_kg=remaining_kg,
            daily_usage_kg=daily_usage_kg,
            days_left=days_left,
            estimates=estimates,
        )

    def _finished_mix_lines(self, status: FinishedMixStatus) -> list[str]:
        lines = [
            f"- Остаток готовой смеси: {_format_kg(status.remaining_kg)}.",
            f"- Расход: {_format_kg(status.daily_usage_kg)}/день.",
            f"- Хватит: {_format_days(status.days_left)}.",
        ]
        if not status.estimates:
            lines.append(f"- {self.content.get('feeding', {}).get('no_finished_mix', DEFAULT_CONTENT['feeding']['no_finished_mix'])}")
        elif status.daily_usage_kg <= 0:
            lines.append("- Расход по стадам не назначен, поэтому срок запаса не рассчитан.")
        elif status.remaining_kg <= 0:
            lines.append("- Готовой смеси нет: сделайте замес или добавьте готовую смесь на склад.")
        elif status.days_left is not None and status.days_left <= self._low_mix_days_threshold():
            lines.append(f"- Срочно: смеси осталось примерно на {status.days_left} дн.")
        elif status.days_left is not None and status.days_left <= self._warning_mix_days_threshold():
            lines.append(f"- Предупреждение: смеси осталось меньше недели ({status.days_left} дн.).")
        return lines

    def _mix_plan_lines(self, *, user_id: int, now: datetime, compact: bool) -> list[str]:
        try:
            plan = self.stock_service.best_available_mix_plan(user_id=user_id, now=now)
        except Exception:
            return ["- План замеса сейчас не рассчитался."]
        possible_count = floor(plan.max_mix_count)
        if possible_count > 0:
            return [
                f"- По складу можно сделать {possible_count} замес(ов), "
                f"получится примерно {_format_kg(plan.output_kg * possible_count)}."
            ]
        missing = [item for item in plan.ingredients if item.missing_kg > 0]
        if missing:
            if compact:
                return ["- Для нового замеса не хватает: " + ", ".join(item.name for item in missing[:5]) + "."]
            return ["- Нужно докупить для замеса:"] + [
                f"  - {item.name}: не хватает {_format_kg(item.missing_kg)}."
                for item in missing[:8]
            ]
        return ["- По рецепту замеса ограничений не найдено."]

    def _flock_setup_warnings(self, *, user_id: int, now: datetime) -> list[str]:
        warnings: list[str] = []
        flocks = self.feed_service.list_flocks(user_id)
        if not flocks:
            warnings.append("- Стада не созданы: расчет расхода смеси будет неполным.")
            return warnings
        reports = self.stock_service.list_flock_reports(user_id, now=now)
        if any(not report.assignments for report in reports):
            warnings.append("- Есть стада без назначенной смеси.")
        groups = self.feed_service.list_bird_groups(user_id)
        has_hens = any(group.is_active and group.group_kind == "adult" and group.role == "hens" for group in groups)
        has_mixed_adults = any(group.is_active and group.group_kind == "adult" and group.role == "mixed" for group in groups)
        if not has_hens and has_mixed_adults:
            warnings.append("- Взрослые куры заведены как смешанная группа: яйца не увидят их как несушек.")
        return warnings

    def _incubation_plan_lines(self, *, user_id: int) -> list[str]:
        statuses = self.incubation_service.get_user_statuses(user_id)
        if not statuses:
            return []
        max_batches = int(self.content.get("incubation", {}).get("max_batches_in_today_plan", 3))
        max_recommendations = int(self.content.get("incubation", {}).get("max_recommendations_per_batch", 2))
        lines: list[str] = []
        for status in statuses[:max_batches]:
            lines.append(f"- {status.batch.title}: день {status.day}, {status.stage}, до вывода {_format_days(status.days_left)}.")
            for recommendation in status.recommendations[:max_recommendations]:
                lines.append(f"  - {recommendation}")
        if len(statuses) > max_batches:
            lines.append(f"- Еще активных партий: {len(statuses) - max_batches}.")
        return lines

    def _low_mix_days_threshold(self) -> int:
        return int(self.content.get("feeding", {}).get("low_mix_days_threshold", 2))

    def _warning_mix_days_threshold(self) -> int:
        return int(self.content.get("feeding", {}).get("warning_mix_days_threshold", 7))

    def _timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")


def load_poultry_advisor_content(path: Path | None = None) -> dict:
    content_path = path or Path(__file__).resolve().parent.parent / "content" / "poultry_advisor.json"
    try:
        with content_path.open("r", encoding="utf-8") as file:
            content = json.load(file)
    except OSError:
        return DEFAULT_CONTENT
    if not isinstance(content, dict):
        return DEFAULT_CONTENT
    return content


def _format_kg(value: float) -> str:
    if abs(value) < 0.005:
        value = 0
    return f"{value:.1f} кг"


def _format_days(value: int | None) -> str:
    if value is None:
        return "не рассчитано"
    if value < 0:
        return "0 дн."
    return f"{value} дн."


def _dedupe_blank_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        result.append(line)
        previous_blank = blank
    while result and not result[-1].strip():
        result.pop()
    return result
