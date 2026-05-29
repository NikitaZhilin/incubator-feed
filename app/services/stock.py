from dataclasses import dataclass
from datetime import datetime, timezone
from math import floor, isfinite
import re

from app.domain import (
    CONTENT,
    FeedingAssignment,
    FlockFeedAssignment,
    FlockFeedUsage,
    FlockIngredientForecast,
    FlockReport,
    StockEstimate,
    StockItem,
)
from app.services.feed_recipes import (
    DEFAULT_GRAIN_BASE,
    get_grain_base_option,
    list_grain_base_options,
    load_chicken_mix_recipe,
)
from app.services.feeds import FeedService
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.stock import StockRepository
from app.storage.repositories.analytics import AnalyticsRepository


STOCK_KIND_LABELS = {
    "ingredient": "ингредиент",
    "finished_mix": "готовая смесь",
    "commercial_feed": "готовый корм",
    "other": "другое",
}
DEFAULT_HEN_DAILY_G = 120
DEFAULT_ROOSTER_DAILY_G = 150
DEFAULT_ADULT_DAILY_G = 120


@dataclass(frozen=True)
class RequiredIngredient:
    name: str
    parts: float
    required_kg: float
    available_kg: float
    stock_item_id: int | None

    @property
    def missing_kg(self) -> float:
        return max(self.required_kg - self.available_kg, 0)


@dataclass(frozen=True)
class MixPlan:
    recipe_code: str
    recipe_version: str
    title: str
    mix_count: float
    grain_base_code: str
    grain_base_label: str
    output_name: str
    output_kg: float
    ingredients: tuple[RequiredIngredient, ...]

    @property
    def can_produce(self) -> bool:
        return all(item.missing_kg <= 0 for item in self.ingredients)

    @property
    def max_mix_count(self) -> float:
        limits = [
            item.available_kg / item.required_kg * self.mix_count
            for item in self.ingredients
            if item.required_kg > 0
        ]
        return max(min(limits), 0) if limits else 0


class StockService:
    def __init__(
        self,
        stock: StockRepository,
        feeds: FeedRepository,
        analytics: AnalyticsRepository | None = None,
    ) -> None:
        self.stock = stock
        self.feeds = feeds
        self.analytics = analytics

    def list_estimates(
        self,
        user_id: int,
        *,
        now: datetime | None = None,
    ) -> list[StockEstimate]:
        current = now or datetime.now(timezone.utc)
        return [self.estimate_item(item, now=current) for item in self.stock.list_items(user_id)]

    def estimate_item(
        self,
        item: StockItem,
        *,
        now: datetime | None = None,
    ) -> StockEstimate:
        current = now or datetime.now(timezone.utc)
        last = self.stock.last_transaction(item.id, item.user_id)
        if last is None:
            return StockEstimate(item, 0, self._daily_usage_kg(item, current), None, None)

        consumed_kg = self._consumed_since(item, last.created_at, current)
        remaining_kg = max(last.balance_after_kg - consumed_kg, 0)
        daily_usage_kg = self._daily_usage_kg(item, current)
        days_left = floor(remaining_kg / daily_usage_kg) if daily_usage_kg > 0 else None
        return StockEstimate(
            item=item,
            remaining_kg=remaining_kg,
            daily_usage_kg=daily_usage_kg,
            days_left=days_left,
            last_transaction_at=last.created_at,
        )

    def add_purchase(
        self,
        *,
        user_id: int,
        name: str,
        kind: str,
        amount_kg: float,
        note: str = "",
    ) -> StockEstimate:
        self._validate_amount(amount_kg)
        item = self.stock.get_or_create_item(user_id=user_id, name=name, kind=kind)
        current = self.estimate_item(item)
        transaction = self.stock.add_transaction(
            user_id=user_id,
            stock_item_id=item.id,
            transaction_type="purchase",
            amount_kg=amount_kg,
            balance_after_kg=current.remaining_kg + amount_kg,
            note=note or "Покупка",
        )
        self._track("stock_purchase", user_id=user_id, entity_id=item.id)
        return self.estimate_item(item, now=transaction.created_at)

    def adjust_stock(
        self,
        *,
        user_id: int,
        stock_item_id: int,
        amount_kg: float,
        note: str = "",
    ) -> StockEstimate | None:
        self._validate_amount(amount_kg, allow_zero=True)
        item = self.stock.get_item(stock_item_id, user_id)
        if item is None:
            return None
        transaction = self.stock.add_transaction(
            user_id=user_id,
            stock_item_id=item.id,
            transaction_type="manual_adjustment",
            amount_kg=amount_kg,
            balance_after_kg=amount_kg,
            note=note or "Фактический остаток",
        )
        self._track("stock_adjusted", user_id=user_id, entity_id=item.id)
        return self.estimate_item(item, now=transaction.created_at)

    def plan_mix(
        self,
        *,
        user_id: int,
        mix_count: float,
        grain_base: str = DEFAULT_GRAIN_BASE,
        now: datetime | None = None,
    ) -> MixPlan:
        self._validate_amount(mix_count)
        grain_base_option = get_grain_base_option(grain_base)
        recipe = load_chicken_mix_recipe(grain_base=grain_base_option.code)
        recipe_payload = CONTENT["feed_recipes"]["chicken_mix"]
        one_cycle_kg = self.one_chicken_mix_cycle_kg(grain_base=grain_base_option.code)
        ingredients = []
        current = now or datetime.now(timezone.utc)
        for ingredient in recipe:
            required_kg = ingredient.parts * ingredient.density_kg_per_l * mix_count
            item = self._find_stock_item_by_names(
                user_id=user_id,
                names=(ingredient.name, *ingredient.aliases),
            )
            available_kg = self.estimate_item(item, now=current).remaining_kg if item else 0
            ingredients.append(
                RequiredIngredient(
                    name=ingredient.name,
                    parts=ingredient.parts,
                    required_kg=required_kg,
                    available_kg=available_kg,
                    stock_item_id=item.id if item else None,
                )
            )
        return MixPlan(
            recipe_code="chicken_mix",
            recipe_version=f"{recipe_payload['version']}; grain_base={grain_base_option.code}",
            title=str(recipe_payload["title"]),
            mix_count=mix_count,
            grain_base_code=grain_base_option.code,
            grain_base_label=grain_base_option.label,
            output_name=str(recipe_payload["title"]),
            output_kg=one_cycle_kg * mix_count,
            ingredients=tuple(ingredients),
        )

    def best_available_mix_plan(
        self,
        *,
        user_id: int,
        now: datetime | None = None,
    ) -> MixPlan:
        plans = tuple(
            self.plan_mix(
                user_id=user_id,
                mix_count=1,
                grain_base=option.code,
                now=now,
            )
            for option in list_grain_base_options()
        )
        return max(plans, key=_mix_plan_availability_key)

    def produce_mix(
        self,
        *,
        user_id: int,
        mix_count: float,
        grain_base: str = DEFAULT_GRAIN_BASE,
    ) -> MixPlan:
        plan = self.plan_mix(user_id=user_id, mix_count=mix_count, grain_base=grain_base)
        if not plan.can_produce:
            raise ValueError("Недостаточно ингредиентов для замеса.")
        output = self.stock.get_or_create_item(
            user_id=user_id,
            name=plan.output_name,
            kind="finished_mix",
        )
        mix = self.stock.create_mix_production(
            user_id=user_id,
            recipe_code=plan.recipe_code,
            recipe_version=plan.recipe_version,
            mix_count=plan.mix_count,
            output_stock_item_id=output.id,
            output_kg=plan.output_kg,
        )
        for required in plan.ingredients:
            if required.stock_item_id is None:
                ingredient_item = self.stock.get_or_create_item(
                    user_id=user_id,
                    name=required.name,
                    kind="ingredient",
                )
            else:
                ingredient_item = self.stock.get_item(required.stock_item_id, user_id)
                if ingredient_item is None:
                    raise ValueError("Позиция склада не найдена.")
            current = self.estimate_item(ingredient_item, now=mix.created_at)
            self.stock.add_mix_item(
                mix_production_id=mix.id,
                ingredient_stock_item_id=ingredient_item.id,
                ingredient_name=required.name,
                amount_kg=required.required_kg,
            )
            self.stock.add_transaction(
                user_id=user_id,
                stock_item_id=ingredient_item.id,
                transaction_type="mix_input",
                amount_kg=-required.required_kg,
                balance_after_kg=max(current.remaining_kg - required.required_kg, 0),
                note=f"Замес #{mix.id}",
                related_mix_id=mix.id,
                created_at=mix.created_at,
            )
        output_current = self.estimate_item(output, now=mix.created_at)
        self.stock.add_transaction(
            user_id=user_id,
            stock_item_id=output.id,
            transaction_type="mix_output",
            amount_kg=plan.output_kg,
            balance_after_kg=output_current.remaining_kg + plan.output_kg,
            note=f"Замес #{mix.id}",
            related_mix_id=mix.id,
            created_at=mix.created_at,
        )
        self._track("mix_produced", user_id=user_id, entity_id=mix.id)
        return plan

    def assign_feed(
        self,
        *,
        user_id: int,
        bird_group_id: int,
        stock_item_id: int,
        daily_per_bird_g: float = 120,
        reserve_percent: float = 0,
    ) -> FeedingAssignment:
        if self.feeds.get_bird_group(bird_group_id, user_id) is None:
            raise ValueError("Поголовье не найдено.")
        stock_item = self.stock.get_item(stock_item_id, user_id)
        if stock_item is None:
            raise ValueError("Позиция склада не найдена.")
        self._validate_amount(daily_per_bird_g)
        self._validate_amount(reserve_percent, allow_zero=True)
        assignment = self.stock.create_assignment(
            user_id=user_id,
            bird_group_id=bird_group_id,
            stock_item_id=stock_item_id,
            daily_per_bird_g=daily_per_bird_g,
            reserve_percent=reserve_percent,
        )
        self._track("feeding_assigned", user_id=user_id, entity_id=assignment.id)
        return assignment

    def list_assignments(self, user_id: int) -> list[FeedingAssignment]:
        return self.stock.list_assignments(user_id)

    def assign_flock_feed(
        self,
        *,
        user_id: int,
        flock_id: int,
        stock_item_id: int,
        share_percent: float = 100,
        daily_per_hen_g: float = DEFAULT_HEN_DAILY_G,
        daily_per_rooster_g: float = DEFAULT_ROOSTER_DAILY_G,
        daily_per_adult_g: float = DEFAULT_ADULT_DAILY_G,
        reserve_percent: float = 0,
    ) -> FlockFeedAssignment:
        flock = self.feeds.get_flock(flock_id, user_id)
        if flock is None or not flock.is_active:
            raise ValueError("Стадо не найдено.")
        stock_item = self.stock.get_item(stock_item_id, user_id)
        if stock_item is None:
            raise ValueError("Позиция склада не найдена.")
        if stock_item.kind != "finished_mix":
            raise ValueError("Стаду можно назначить только готовую смесь.")
        self._validate_amount(share_percent)
        self._validate_amount(daily_per_hen_g)
        self._validate_amount(daily_per_rooster_g)
        self._validate_amount(daily_per_adult_g)
        self._validate_amount(reserve_percent, allow_zero=True)
        active_share = sum(
            assignment.share_percent
            for assignment in self.stock.list_flock_assignments(user_id, flock_id)
            if assignment.stock_item_id != stock_item_id
        )
        if active_share + share_percent > 100:
            raise ValueError("Сумма долей рациона стада не может быть больше 100%.")
        members = self.feeds.list_flock_members(flock_id, user_id)
        self.stock.deactivate_assignments_for_groups(
            user_id=user_id,
            bird_group_ids=[member.bird_group_id for member in members],
        )
        assignment = self.stock.create_flock_assignment(
            user_id=user_id,
            flock_id=flock_id,
            stock_item_id=stock_item_id,
            share_percent=share_percent,
            daily_per_hen_g=daily_per_hen_g,
            daily_per_rooster_g=daily_per_rooster_g,
            daily_per_adult_g=daily_per_adult_g,
            reserve_percent=reserve_percent,
        )
        self._track("flock_feed_assigned", user_id=user_id, entity_id=assignment.id)
        return assignment

    def list_flock_reports(
        self,
        user_id: int,
        *,
        now: datetime | None = None,
    ) -> list[FlockReport]:
        current = now or datetime.now(timezone.utc)
        reports: list[FlockReport] = []
        for flock in self.feeds.list_flocks(user_id):
            members = tuple(self.feeds.list_flock_members(flock.id, user_id))
            usages = []
            for assignment in self.stock.list_flock_assignments(user_id, flock.id):
                item = self.stock.get_item(assignment.stock_item_id, user_id)
                remaining_kg = self.estimate_item(item, now=current).remaining_kg if item else 0
                daily_usage_kg = self._flock_assignment_daily_usage_kg(assignment, current)
                days_left = floor(remaining_kg / daily_usage_kg) if daily_usage_kg > 0 else None
                mix_plan = self.best_available_mix_plan(user_id=user_id, now=current)
                producible_mix_count = int(mix_plan.max_mix_count)
                producible_mix_kg = mix_plan.output_kg * producible_mix_count
                total_days_left = (
                    floor((remaining_kg + producible_mix_kg) / daily_usage_kg)
                    if daily_usage_kg > 0
                    else None
                )
                limiting_ingredient = self._mix_limit_ingredient(mix_plan)
                ingredient_forecasts = self._ingredient_forecasts_for_mix_plan(
                    mix_plan,
                    daily_mix_usage_kg=daily_usage_kg,
                    ready_mix_days_left=days_left,
                )
                usages.append(
                    FlockFeedUsage(
                        assignment=assignment,
                        daily_usage_kg=daily_usage_kg,
                        remaining_kg=remaining_kg,
                        days_left=days_left,
                        producible_mix_count=producible_mix_count,
                        producible_mix_kg=producible_mix_kg,
                        total_days_left=total_days_left,
                        grain_base_label=mix_plan.grain_base_label,
                        limiting_ingredient_name=(
                            limiting_ingredient.name if limiting_ingredient else None
                        ),
                        missing_ingredient_names=tuple(
                            ingredient.name
                            for ingredient in mix_plan.ingredients
                            if ingredient.missing_kg > 0
                        ),
                        ingredient_forecasts=tuple(ingredient_forecasts),
                    )
                )
            reports.append(
                FlockReport(
                    flock=flock,
                    members=members,
                    assignments=tuple(usages),
                    daily_usage_kg=sum(item.daily_usage_kg for item in usages),
                )
            )
        return reports

    def list_history(self, user_id: int, limit: int = 20):
        return self.stock.list_transactions(user_id, limit=limit)

    @staticmethod
    def one_chicken_mix_cycle_kg(grain_base: str = DEFAULT_GRAIN_BASE) -> float:
        return sum(
            item.parts * item.density_kg_per_l
            for item in load_chicken_mix_recipe(grain_base=grain_base)
        )

    @staticmethod
    def _mix_limit_ingredient(plan: MixPlan) -> RequiredIngredient | None:
        candidates = [item for item in plan.ingredients if item.required_kg > 0]
        if not candidates:
            return None
        return min(candidates, key=lambda item: item.available_kg / item.required_kg)

    @staticmethod
    def _ingredient_forecasts_for_mix_plan(
        plan: MixPlan,
        *,
        daily_mix_usage_kg: float,
        ready_mix_days_left: int | None,
    ) -> list[FlockIngredientForecast]:
        if plan.output_kg <= 0 or daily_mix_usage_kg <= 0:
            return []
        ready_mix_delay_days = max(ready_mix_days_left or 0, 0)
        forecasts: list[FlockIngredientForecast] = []
        for ingredient in plan.ingredients:
            daily_usage_kg = daily_mix_usage_kg * ingredient.required_kg / plan.output_kg
            ingredient_days_left = (
                floor(ingredient.available_kg / daily_usage_kg)
                if daily_usage_kg > 0
                else None
            )
            days_left = (
                ready_mix_delay_days + ingredient_days_left
                if ingredient_days_left is not None
                else None
            )
            forecasts.append(
                FlockIngredientForecast(
                    name=ingredient.name,
                    available_kg=ingredient.available_kg,
                    daily_usage_kg=daily_usage_kg,
                    days_left=days_left,
                )
            )
        return sorted(
            forecasts,
            key=lambda item: item.days_left if item.days_left is not None else 10**9,
        )

    def _find_stock_item_by_names(self, *, user_id: int, names: tuple[str, ...]) -> StockItem | None:
        items = self.stock.list_items(user_id)
        normalized_names = set()
        for name in names:
            cleaned = name.strip()
            normalized = _normalize_stock_name(cleaned)
            if not cleaned or normalized in normalized_names:
                continue
            normalized_names.add(normalized)
            item = self.stock.find_item_by_name(user_id=user_id, name=cleaned)
            if item is not None:
                return item
        for item in items:
            stock_name = _normalize_stock_name(item.name)
            if stock_name in normalized_names:
                return item
        for item in items:
            stock_name = _normalize_stock_name(item.name)
            if any(_stock_names_match(alias, stock_name) for alias in normalized_names):
                return item
        return None

    def _consumed_since(self, item: StockItem, since: datetime, until: datetime) -> float:
        consumed = 0.0
        for assignment in self.stock.list_assignments_for_item(item.user_id, item.id):
            start = max(since, assignment.started_at)
            if until <= start:
                continue
            consumed += self._assignment_daily_usage_kg(assignment, until) * (
                (until - start).total_seconds() / 86400
            )
        for assignment in self.stock.list_flock_assignments_for_item(item.user_id, item.id):
            start = max(since, assignment.started_at)
            if until <= start:
                continue
            consumed += self._flock_assignment_daily_usage_kg(assignment, until) * (
                (until - start).total_seconds() / 86400
            )
        return consumed

    def _daily_usage_kg(self, item: StockItem, current: datetime) -> float:
        return sum(
            self._assignment_daily_usage_kg(assignment, current)
            for assignment in self.stock.list_assignments_for_item(item.user_id, item.id)
        ) + sum(
            self._flock_assignment_daily_usage_kg(assignment, current)
            for assignment in self.stock.list_flock_assignments_for_item(item.user_id, item.id)
        )

    def _assignment_daily_usage_kg(
        self,
        assignment: FeedingAssignment,
        current: datetime,
    ) -> float:
        group = self.feeds.get_bird_group(assignment.bird_group_id, assignment.user_id)
        if group is None:
            return 0
        if group.group_kind == "chicks" and group.hatched_at is not None:
            if group.joined_at is not None and current.date() >= group.joined_at:
                return 0
            age_days = max((current.date() - group.hatched_at).days, 0)
            reserve = 1 + max(group.reserve_percent, 0) / 100
            return group.bird_count * FeedService.chick_daily_g(age_days) * reserve / 1000
        reserve = 1 + max(assignment.reserve_percent, 0) / 100
        return group.bird_count * assignment.daily_per_bird_g * reserve / 1000

    def _flock_assignment_daily_usage_kg(
        self,
        assignment: FlockFeedAssignment,
        current: datetime,
    ) -> float:
        members = self.feeds.list_flock_members(assignment.flock_id, assignment.user_id)
        total_g = 0.0
        for member in members:
            if member.group_kind == "chicks":
                if member.group_joined_at is not None and current.date() < member.group_joined_at:
                    continue
                if member.hatched_at is not None:
                    age_days = max((current.date() - member.hatched_at).days, 0)
                    total_g += member.bird_count * FeedService.chick_daily_g(age_days)
                else:
                    total_g += member.bird_count * assignment.daily_per_adult_g
            elif member.role == "hens":
                total_g += member.bird_count * assignment.daily_per_hen_g
            elif member.role == "roosters":
                total_g += member.bird_count * assignment.daily_per_rooster_g
            else:
                total_g += member.bird_count * assignment.daily_per_adult_g
        share = assignment.share_percent / 100
        reserve = 1 + max(assignment.reserve_percent, 0) / 100
        return total_g * share * reserve / 1000

    @staticmethod
    def _validate_amount(value: float, *, allow_zero: bool = False) -> None:
        if not isfinite(value) or value < 0 or (value == 0 and not allow_zero):
            raise ValueError("Количество должно быть больше нуля.")

    def _track(self, event_name: str, *, user_id: int, entity_id: int) -> None:
        if self.analytics is not None:
            self.analytics.track(
                event_name,
                user_id=user_id,
                entity_type="stock",
                entity_id=entity_id,
            )


def _normalize_stock_name(value: str) -> str:
    normalized = value.strip().lower().replace("ё", "е")
    normalized = re.sub(r"[^0-9a-zа-я]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _stock_names_match(recipe_name: str, stock_name: str) -> bool:
    return (
        recipe_name == stock_name
        or recipe_name in stock_name
        or stock_name in recipe_name
    )


def _mix_plan_availability_key(plan: MixPlan) -> tuple[int, float, int, float]:
    missing = [item for item in plan.ingredients if item.missing_kg > 0]
    return (
        int(plan.max_mix_count),
        plan.max_mix_count,
        -len(missing),
        -sum(item.missing_kg for item in missing),
    )
