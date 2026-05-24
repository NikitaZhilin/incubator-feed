from dataclasses import dataclass
import re

from app.domain import CONTENT


DEFAULT_BAG_KG = 25.0


@dataclass(frozen=True)
class MixIngredient:
    name: str
    parts: float
    density_kg_per_l: float
    group: str


@dataclass(frozen=True)
class MixIngredientAmount:
    ingredient: MixIngredient
    liters: float
    kg: float


@dataclass(frozen=True)
class MixCalculation:
    target_kg: float
    one_cycle_liters: float
    one_cycle_kg: float
    scale: float
    ingredients: tuple[MixIngredientAmount, ...]


def _load_recipe(code: str) -> tuple[MixIngredient, ...]:
    return tuple(
        MixIngredient(
            name=str(item["name"]),
            parts=float(item["parts"]),
            density_kg_per_l=float(item["density_kg_per_l"]),
            group=str(item["group"]),
        )
        for item in CONTENT["feed_recipes"][code]["ingredients"]
    )


CHICKEN_MIX_RECIPE: tuple[MixIngredient, ...] = _load_recipe("chicken_mix")


def parse_feed_amount(value: str, *, default_bag_kg: float = DEFAULT_BAG_KG) -> float:
    """Parse kilograms or bags: '25', '25 кг', '1 мешок', '2 мешка по 25'."""
    raw = value.strip().lower().replace(",", ".")
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", raw)]
    if not numbers:
        raise ValueError("Не понял количество.")

    if "меш" in raw:
        bags = numbers[0]
        bag_kg = numbers[1] if len(numbers) > 1 else default_bag_kg
        kg = bags * bag_kg
    else:
        kg = numbers[0]

    if kg <= 0:
        raise ValueError("Количество должно быть больше нуля.")
    return kg


def calculate_chicken_mix(target_kg: float) -> MixCalculation:
    if target_kg <= 0:
        raise ValueError("Вес смеси должен быть больше нуля.")

    one_cycle_liters = sum(item.parts for item in CHICKEN_MIX_RECIPE)
    one_cycle_kg = sum(item.parts * item.density_kg_per_l for item in CHICKEN_MIX_RECIPE)
    scale = target_kg / one_cycle_kg
    ingredients = tuple(
        MixIngredientAmount(
            ingredient=item,
            liters=item.parts * scale,
            kg=item.parts * item.density_kg_per_l * scale,
        )
        for item in CHICKEN_MIX_RECIPE
    )
    return MixCalculation(
        target_kg=target_kg,
        one_cycle_liters=one_cycle_liters,
        one_cycle_kg=one_cycle_kg,
        scale=scale,
        ingredients=ingredients,
    )


def format_chicken_mix(calculation: MixCalculation) -> str:
    lines = [
        f"🧮 {CONTENT['feed_recipes']['chicken_mix']['title']}",
        "",
        f"Готовая смесь: {calculation.target_kg:.1f} кг",
        str(CONTENT["feed_recipes"]["chicken_mix"]["description"]),
        (
            f"Базовый замес: {calculation.one_cycle_liters:g} кружек "
            f"≈ {calculation.one_cycle_kg:.2f} кг."
        ),
        "",
    ]

    current_group = None
    for amount in calculation.ingredients:
        ingredient = amount.ingredient
        if ingredient.group != current_group:
            current_group = ingredient.group
            lines.append(f"{current_group}:")
        lines.append(
            f"- {ingredient.name}: {ingredient.parts:g} части -> "
            f"{amount.liters:.2f} л/кружек, ≈ {amount.kg:.2f} кг"
        )

    lines.extend(
        [
            "",
            "Расчет по кг примерный: части заданы объемом, а вес зависит от фракции и влажности сырья.",
        ]
    )
    return "\n".join(lines)
