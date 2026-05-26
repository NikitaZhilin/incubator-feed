from dataclasses import dataclass
import re

from app.domain import CONTENT


DEFAULT_BAG_KG = 25.0
DEFAULT_PACK_KG = 0.5


@dataclass(frozen=True)
class MixIngredient:
    name: str
    parts: float
    density_kg_per_l: float
    group: str
    aliases: tuple[str, ...] = ()


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
    grain_base_code: str
    grain_base_label: str
    grain_base_note: str
    ingredients: tuple[MixIngredientAmount, ...]


@dataclass(frozen=True)
class GrainBaseOption:
    code: str
    label: str
    name: str
    parts: float
    density_kg_per_l: float
    group: str
    aliases: tuple[str, ...]
    note: str


DEFAULT_GRAIN_BASE = "wheat"


def _grain_base_payload(code: str) -> dict:
    variants = CONTENT["feed_recipes"]["chicken_mix"]["ingredient_variants"]["grain_base"]
    for option in variants["options"]:
        if str(option["code"]) == code:
            return option
    raise ValueError("Неизвестный вариант зерновой основы.")


def get_grain_base_option(code: str = DEFAULT_GRAIN_BASE) -> GrainBaseOption:
    payload = _grain_base_payload(code)
    return GrainBaseOption(
        code=str(payload["code"]),
        label=str(payload["label"]),
        name=str(payload["name"]),
        parts=float(payload["parts"]),
        density_kg_per_l=float(payload["density_kg_per_l"]),
        group=str(payload["group"]),
        aliases=tuple(str(item) for item in payload.get("aliases", [])),
        note=str(payload.get("note", "")),
    )


def list_grain_base_options() -> tuple[GrainBaseOption, ...]:
    variants = CONTENT["feed_recipes"]["chicken_mix"]["ingredient_variants"]["grain_base"]
    return tuple(get_grain_base_option(str(option["code"])) for option in variants["options"])


def _ingredient_from_payload(item: dict) -> MixIngredient:
    return MixIngredient(
        name=str(item["name"]),
        parts=float(item["parts"]),
        density_kg_per_l=float(item["density_kg_per_l"]),
        group=str(item["group"]),
        aliases=tuple(str(alias) for alias in item.get("aliases", [])),
    )


def _load_recipe(code: str, *, grain_base: str = DEFAULT_GRAIN_BASE) -> tuple[MixIngredient, ...]:
    selected_grain_base = get_grain_base_option(grain_base)
    ingredients = []
    for item in CONTENT["feed_recipes"][code]["ingredients"]:
        if item.get("variant_group") == "grain_base":
            ingredients.append(
                MixIngredient(
                    name=selected_grain_base.name,
                    parts=selected_grain_base.parts,
                    density_kg_per_l=selected_grain_base.density_kg_per_l,
                    group=selected_grain_base.group,
                    aliases=selected_grain_base.aliases,
                )
            )
        else:
            ingredients.append(_ingredient_from_payload(item))
    return tuple(ingredients)


def load_chicken_mix_recipe(
    *,
    grain_base: str = DEFAULT_GRAIN_BASE,
) -> tuple[MixIngredient, ...]:
    return _load_recipe("chicken_mix", grain_base=grain_base)


CHICKEN_MIX_RECIPE: tuple[MixIngredient, ...] = _load_recipe("chicken_mix")


def parse_feed_amount(
    value: str,
    *,
    default_bag_kg: float = DEFAULT_BAG_KG,
    default_pack_kg: float = DEFAULT_PACK_KG,
) -> float:
    """Parse kilograms, grams, bags or small packs."""
    raw = value.strip().lower().replace(",", ".")
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", raw)]
    if not numbers:
        raise ValueError("Не понял количество.")

    has_grams = bool(re.search(r"(?<!к)(?:гр\.?|грамм\w*|г\b)", raw))
    if "меш" in raw:
        bags = numbers[0]
        bag_kg = numbers[1] if len(numbers) > 1 else default_bag_kg
        kg = bags * bag_kg
    elif "пач" in raw or "упак" in raw:
        packs = numbers[0]
        pack_kg = numbers[1] if len(numbers) > 1 else default_pack_kg
        if len(numbers) > 1 and has_grams:
            pack_kg = pack_kg / 1000
        kg = packs * pack_kg
    elif has_grams:
        kg = numbers[0] / 1000
    else:
        kg = numbers[0]

    if kg <= 0:
        raise ValueError("Количество должно быть больше нуля.")
    return kg


def calculate_chicken_mix(
    target_kg: float,
    *,
    grain_base: str = DEFAULT_GRAIN_BASE,
) -> MixCalculation:
    if target_kg <= 0:
        raise ValueError("Вес смеси должен быть больше нуля.")

    grain_base_option = get_grain_base_option(grain_base)
    recipe = load_chicken_mix_recipe(grain_base=grain_base_option.code)
    one_cycle_liters = sum(item.parts for item in recipe)
    one_cycle_kg = sum(item.parts * item.density_kg_per_l for item in recipe)
    scale = target_kg / one_cycle_kg
    ingredients = tuple(
        MixIngredientAmount(
            ingredient=item,
            liters=item.parts * scale,
            kg=item.parts * item.density_kg_per_l * scale,
        )
        for item in recipe
    )
    return MixCalculation(
        target_kg=target_kg,
        one_cycle_liters=one_cycle_liters,
        one_cycle_kg=one_cycle_kg,
        scale=scale,
        grain_base_code=grain_base_option.code,
        grain_base_label=grain_base_option.label,
        grain_base_note=grain_base_option.note,
        ingredients=ingredients,
    )


def format_chicken_mix(calculation: MixCalculation) -> str:
    lines = [
        f"🧮 {CONTENT['feed_recipes']['chicken_mix']['title']}",
        "",
        f"Готовая смесь: {calculation.target_kg:.1f} кг",
        str(CONTENT["feed_recipes"]["chicken_mix"]["description"]),
        f"Зерновая основа вместо пшеницы: {calculation.grain_base_label}.",
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
            calculation.grain_base_note,
            "Расчет по кг примерный: части заданы объемом, а вес зависит от фракции и влажности сырья.",
        ]
    )
    return "\n".join(lines)
