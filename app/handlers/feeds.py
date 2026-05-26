from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from math import isfinite

from app.domain import FeedEstimate
from app.domain import PROFILES
from app.keyboards.feeds import (
    bird_group_select_keyboard,
    bird_groups_keyboard,
    feed_actions_keyboard,
    feed_cancel_keyboard,
    feed_delete_confirm_keyboard,
    feed_edit_keyboard,
    feed_rate_keyboard,
    feeds_menu_keyboard,
    grain_base_keyboard,
    stock_assign_groups_keyboard,
    stock_confirm_mix_keyboard,
    stock_items_keyboard,
    stock_kind_keyboard,
    stock_menu_keyboard,
)
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.services.stock import STOCK_KIND_LABELS, StockService
from app.services.feed_recipes import (
    DEFAULT_GRAIN_BASE,
    calculate_chicken_mix,
    format_chicken_mix,
    get_grain_base_option,
    parse_feed_amount,
)
from app.utils.dates import DATE_FORMAT_HINT, parse_user_date


router = Router()


class NewFeed(StatesGroup):
    name = State()
    group = State()
    amount = State()
    birds = State()
    hens = State()
    roosters = State()
    rate = State()
    hen_rate = State()
    rooster_rate = State()
    threshold = State()


class FeedMix(StatesGroup):
    grain_base = State()
    amount = State()


class RestockFeed(StatesGroup):
    amount = State()


class ChangeFeed(StatesGroup):
    amount = State()


class EditFeed(StatesGroup):
    value = State()
    group = State()


class BirdGroupFlow(StatesGroup):
    name = State()
    kind = State()
    count = State()
    hatched_date = State()
    joined_date = State()
    species = State()


class StockPurchaseFlow(StatesGroup):
    name = State()
    kind = State()
    amount = State()


class StockMixFlow(StatesGroup):
    grain_base = State()
    count = State()


class StockAssignFlow(StatesGroup):
    group = State()
    item = State()
    rate = State()


class StockAdjustFlow(StatesGroup):
    item = State()
    amount = State()


FEED_FLOW_STATES = (
    NewFeed.name,
    NewFeed.group,
    NewFeed.amount,
    NewFeed.birds,
    NewFeed.hens,
    NewFeed.roosters,
    NewFeed.rate,
    NewFeed.hen_rate,
    NewFeed.rooster_rate,
    NewFeed.threshold,
    FeedMix.grain_base,
    FeedMix.amount,
    RestockFeed.amount,
    ChangeFeed.amount,
    EditFeed.value,
    EditFeed.group,
    BirdGroupFlow.name,
    BirdGroupFlow.kind,
    BirdGroupFlow.count,
    BirdGroupFlow.hatched_date,
    BirdGroupFlow.joined_date,
    BirdGroupFlow.species,
    StockPurchaseFlow.name,
    StockPurchaseFlow.kind,
    StockPurchaseFlow.amount,
    StockMixFlow.count,
    StockMixFlow.grain_base,
    StockAssignFlow.group,
    StockAssignFlow.item,
    StockAssignFlow.rate,
    StockAdjustFlow.item,
    StockAdjustFlow.amount,
)


@router.callback_query(StateFilter(*FEED_FLOW_STATES), F.data == "flow:cancel")
async def feed_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Действие с кормами отменено.", reply_markup=feeds_menu_keyboard())
    await callback.answer()


@router.message(StateFilter(*FEED_FLOW_STATES), Command("cancel"))
async def feed_cancel_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие с кормами отменено.", reply_markup=feeds_menu_keyboard())


@router.message(Command("feed"))
async def feed_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewFeed.name)
    await message.answer("Введите название корма, например Комбикорм ПК-1.", reply_markup=feed_cancel_keyboard())


@router.callback_query(F.data == "feeds:menu")
async def feeds_menu(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    await state.clear()
    estimates = feed_service.list_user_estimates(callback.from_user.id)
    if not estimates:
        await callback.message.answer(
            "🌾 Корма\n\nЗапасов пока нет. Добавьте корм и поголовье для расчета — я посчитаю остаток и напомню о покупке.",
            reply_markup=feeds_menu_keyboard(),
        )
    else:
        lines = ["🌾 Корма"]
        for estimate in estimates:
            lines.append("")
            lines.append(_format_estimate(estimate))
        await callback.message.answer(
            "\n".join(lines),
            reply_markup=feeds_menu_keyboard([(item.feed.id, item.feed.name) for item in estimates]),
        )
    await callback.answer()


@router.callback_query(F.data == "feeds:add")
async def feed_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewFeed.name)
    await callback.message.answer("Введите название корма, например Комбикорм ПК-1.", reply_markup=feed_cancel_keyboard())
    await callback.answer()


@router.callback_query(F.data == "feeds:groups")
async def bird_groups_menu(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    await state.clear()
    groups = feed_service.list_bird_groups(callback.from_user.id)
    if not groups:
        text = (
            "Поголовье пока не задано.\n\n"
            "Можно добавить основное стадо или цыплят. Потом корм привязывается к поголовью, "
            "и расход считается понятнее."
        )
    else:
        lines = ["Поголовье:"]
        for group in groups:
            species = f", {PROFILES[group.species].title}" if group.species in PROFILES else ""
            if group.group_kind == "chicks":
                hatched = group.hatched_at.isoformat() if group.hatched_at else "дата не указана"
                joined = (
                    f", подсадка {group.joined_at.isoformat()}"
                    if group.joined_at
                    else ", подсадка не задана"
                )
                lines.append(
                    f"- #{group.id} {group.name}: {group.bird_count} цыплят, вывод {hatched}{joined}, запас {group.reserve_percent:g}%"
                )
            else:
                lines.append(f"- #{group.id} {group.name}: {group.bird_count} птиц{species}")
        text = "\n".join(lines)
    await callback.message.answer(text, reply_markup=bird_groups_keyboard())
    await callback.answer()


@router.callback_query(F.data == "feeds:group_add")
async def bird_group_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BirdGroupFlow.name)
    await callback.message.answer(
        "Введите название поголовья, например Основное стадо или Цыплята май.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.message(BirdGroupFlow.name)
async def bird_group_name(
    message: Message,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="bird_group_name",
            message="short_name",
        )
        await message.answer("Введите название поголовья минимум из двух символов.")
        return
    await state.update_data(name=name)
    await state.set_state(BirdGroupFlow.kind)
    await message.answer(
        "Что это за поголовье?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Куры и петухи", callback_data="feeds:group_kind:adult")],
                [InlineKeyboardButton(text="Цыплята", callback_data="feeds:group_kind:chicks")],
                [InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")],
            ]
        ),
    )


@router.callback_query(BirdGroupFlow.kind, F.data.startswith("feeds:group_kind:"))
async def bird_group_kind(callback: CallbackQuery, state: FSMContext) -> None:
    group_kind = str(callback.data).split(":", 2)[2]
    await state.update_data(group_kind=group_kind)
    await state.set_state(BirdGroupFlow.count)
    if group_kind == "chicks":
        await callback.message.answer("Сколько цыплят? Введите число.", reply_markup=feed_cancel_keyboard())
    else:
        await callback.message.answer(
            "Сколько всего птиц в основном стаде? Куры и петухи считаются вместе.",
            reply_markup=feed_cancel_keyboard(),
        )
    await callback.answer()


@router.message(BirdGroupFlow.count)
async def bird_group_count(
    message: Message,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    if not message.text or not message.text.strip().isdigit() or int(message.text.strip()) <= 0:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="bird_group_count",
            message="invalid_count",
        )
        await message.answer("Введите количество птиц числом, например 25.")
        return
    await state.update_data(bird_count=int(message.text.strip()))
    data = await state.get_data()
    if data.get("group_kind") == "chicks":
        await state.set_state(BirdGroupFlow.hatched_date)
        await message.answer(
            f"Введите дату вывода цыплят: {DATE_FORMAT_HINT}.",
            reply_markup=feed_cancel_keyboard(),
        )
        return
    await state.set_state(BirdGroupFlow.species)
    rows = [
        [InlineKeyboardButton(text=profile.title, callback_data=f"feeds:group_species:{code}")]
        for code, profile in PROFILES.items()
    ]
    rows.append([InlineKeyboardButton(text="Без вида", callback_data="feeds:group_species:none")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")])
    await message.answer(
        "Выберите вид птицы для поголовья или оставьте без вида.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.message(BirdGroupFlow.hatched_date)
async def bird_group_hatched_date(
    message: Message,
    state: FSMContext,
    incubation_service: IncubationService,
) -> None:
    try:
        hatched_at = parse_user_date(message.text or "")
    except ValueError as exc:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="bird_group_hatched_date",
            message="invalid_date",
        )
        await message.answer(str(exc))
        return
    await state.update_data(hatched_at=hatched_at)
    await state.set_state(BirdGroupFlow.joined_date)
    await message.answer(
        "Введите примерную дату подсадки в основной курятник.\n"
        "Если пока неизвестно, отправьте 0.",
        reply_markup=feed_cancel_keyboard(),
    )


@router.message(BirdGroupFlow.joined_date)
async def bird_group_joined_date(
    message: Message,
    state: FSMContext,
    feed_service: FeedService,
    incubation_service: IncubationService,
) -> None:
    text = (message.text or "").strip().lower()
    joined_at = None
    if text not in {"0", "-", "нет", "не знаю"}:
        try:
            joined_at = parse_user_date(text)
        except ValueError as exc:
            incubation_service.track_scenario_error(
                user_id=message.from_user.id,
                scenario="bird_group_joined_date",
                message="invalid_date",
            )
            await message.answer(str(exc))
            return
    data = await state.get_data()
    try:
        group = feed_service.create_bird_group(
            user_id=message.from_user.id,
            name=str(data["name"]),
            bird_count=int(data["bird_count"]),
            species="chicken",
            group_kind="chicks",
            hatched_at=data["hatched_at"],
            joined_at=joined_at,
            reserve_percent=10,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    joined_text = joined_at.isoformat() if joined_at else "не задана"
    await message.answer(
        f"Поголовье создано: #{group.id} {group.name}, {group.bird_count} цыплят.\n"
        f"Вывод: {group.hatched_at.isoformat() if group.hatched_at else '-'}, подсадка: {joined_text}.\n"
        "Расход корма будет считаться по возрасту цыплят с запасом 10%.",
        reply_markup=bird_groups_keyboard(),
    )


@router.callback_query(BirdGroupFlow.species, F.data.startswith("feeds:group_species:"))
async def bird_group_species(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    species = str(callback.data).split(":", 2)[2]
    data = await state.get_data()
    group = feed_service.create_bird_group(
        user_id=callback.from_user.id,
        name=str(data["name"]),
        bird_count=int(data["bird_count"]),
        species=None if species == "none" else species,
        group_kind="adult",
    )
    await state.clear()
    await callback.message.answer(
        f"Поголовье создано: #{group.id} {group.name}, {group.bird_count} птиц.",
        reply_markup=bird_groups_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "stock:menu")
async def stock_menu(callback: CallbackQuery, state: FSMContext, stock_service: StockService) -> None:
    await state.clear()
    estimates = stock_service.list_estimates(callback.from_user.id)
    await callback.message.answer(
        _format_stock_menu(estimates),
        reply_markup=stock_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "stock:purchase")
async def stock_purchase_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(StockPurchaseFlow.name)
    await callback.message.answer(
        "Введите название позиции склада, например Кукуруза, Пшеница или Комбикорм ПК-1.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.message(StockPurchaseFlow.name)
async def stock_purchase_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Введите название минимум из двух символов.")
        return
    await state.update_data(name=name)
    await state.set_state(StockPurchaseFlow.kind)
    await message.answer("Что это за позиция?", reply_markup=stock_kind_keyboard())


@router.callback_query(StockPurchaseFlow.kind, F.data.startswith("stock:kind:"))
async def stock_purchase_kind(callback: CallbackQuery, state: FSMContext) -> None:
    kind = str(callback.data).split(":", 2)[2]
    await state.update_data(kind=kind)
    await state.set_state(StockPurchaseFlow.amount)
    await callback.message.answer(
        "Сколько куплено или добавлено на склад? Например 25 кг, 1 мешок, 2 мешка по 25.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.message(StockPurchaseFlow.amount)
async def stock_purchase_amount(
    message: Message,
    state: FSMContext,
    stock_service: StockService,
    incubation_service: IncubationService,
) -> None:
    try:
        amount_kg = parse_feed_amount(message.text or "")
    except ValueError as exc:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="stock_purchase_amount",
            message=str(exc),
        )
        await message.answer(str(exc))
        return
    data = await state.get_data()
    estimate = stock_service.add_purchase(
        user_id=message.from_user.id,
        name=str(data["name"]),
        kind=str(data["kind"]),
        amount_kg=amount_kg,
    )
    await state.clear()
    await message.answer(
        "Покупка добавлена.\n\n" + _format_stock_estimate(estimate),
        reply_markup=stock_menu_keyboard(),
    )


@router.callback_query(F.data == "stock:mix")
async def stock_mix_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(StockMixFlow.grain_base)
    await callback.message.answer(
        "Что использовать в рецепте на месте пшеницы?",
        reply_markup=grain_base_keyboard("stock:mix_grain"),
    )
    await callback.answer()


@router.callback_query(StockMixFlow.grain_base, F.data.startswith("stock:mix_grain:"))
async def stock_mix_grain_base(
    callback: CallbackQuery,
    state: FSMContext,
    stock_service: StockService,
) -> None:
    grain_base = str(callback.data).rsplit(":", 1)[1]
    try:
        option = get_grain_base_option(grain_base)
    except ValueError as exc:
        await callback.message.answer(str(exc), reply_markup=stock_menu_keyboard())
        await callback.answer()
        return
    await state.update_data(grain_base=option.code)
    await state.set_state(StockMixFlow.count)
    one_cycle = stock_service.one_chicken_mix_cycle_kg(grain_base=option.code)
    await callback.message.answer(
        f"Сколько замесов смеси сделать?\n\n"
        f"Зерновая основа: {option.label}.\n"
        f"Один замес по рецепту ≈ {one_cycle:.1f} кг готовой смеси.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.message(StockMixFlow.count)
async def stock_mix_count(
    message: Message,
    state: FSMContext,
    stock_service: StockService,
    incubation_service: IncubationService,
) -> None:
    try:
        mix_count = _parse_float(message.text)
    except ValueError:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="stock_mix_count",
            message="invalid_count",
        )
        await message.answer("Введите количество замесов числом, например 3.")
        return
    data = await state.get_data()
    grain_base = str(data.get("grain_base") or DEFAULT_GRAIN_BASE)
    plan = stock_service.plan_mix(
        user_id=message.from_user.id,
        mix_count=mix_count,
        grain_base=grain_base,
    )
    await state.clear()
    await message.answer(
        _format_mix_plan(plan),
        reply_markup=(
            stock_confirm_mix_keyboard(mix_count, grain_base)
            if plan.can_produce
            else stock_menu_keyboard()
        ),
    )


@router.callback_query(F.data.startswith("stock:mix_confirm:"))
async def stock_mix_confirm(callback: CallbackQuery, stock_service: StockService) -> None:
    parts = str(callback.data).split(":")
    if len(parts) == 4:
        grain_base = parts[2]
        mix_count = float(parts[3])
    else:
        grain_base = DEFAULT_GRAIN_BASE
        mix_count = float(parts[-1])
    try:
        plan = stock_service.produce_mix(
            user_id=callback.from_user.id,
            mix_count=mix_count,
            grain_base=grain_base,
        )
    except ValueError as exc:
        await callback.message.answer(str(exc), reply_markup=stock_menu_keyboard())
        await callback.answer()
        return
    await callback.message.answer(
        "Замес создан.\n\n" + _format_mix_plan(plan),
        reply_markup=stock_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "stock:history")
async def stock_history(callback: CallbackQuery, stock_service: StockService) -> None:
    transactions = stock_service.list_history(callback.from_user.id)
    items = {item.id: item for item in stock_service.stock.list_items(callback.from_user.id)}
    if not transactions:
        await callback.message.answer("История склада пока пустая.", reply_markup=stock_menu_keyboard())
        await callback.answer()
        return
    lines = ["📋 История склада:"]
    labels = {
        "purchase": "покупка",
        "mix_input": "списано на замес",
        "mix_output": "получена смесь",
        "manual_adjustment": "задан остаток",
        "write_off": "списание",
    }
    for transaction in transactions[:12]:
        item = items.get(transaction.stock_item_id)
        sign = "+" if transaction.amount_kg > 0 else ""
        lines.append(
            f"- {transaction.created_at.date().isoformat()} "
            f"{item.name if item else '#'+str(transaction.stock_item_id)}: "
            f"{labels.get(transaction.type, transaction.type)} {sign}{transaction.amount_kg:g} кг, "
            f"остаток {transaction.balance_after_kg:g} кг"
        )
    await callback.message.answer("\n".join(lines), reply_markup=stock_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "stock:assignments")
async def stock_assignments(callback: CallbackQuery, state: FSMContext, stock_service: StockService, feed_service: FeedService) -> None:
    await state.clear()
    assignments = stock_service.list_assignments(callback.from_user.id)
    lines = ["⚙️ Рационы склада:"]
    if assignments:
        for assignment in assignments:
            lines.append(
                f"- {assignment.bird_group_name}: {assignment.stock_item_name}, "
                f"{assignment.daily_per_bird_g:g} г/гол./день"
            )
    else:
        lines.append("Рационы пока не заданы.")
    groups = feed_service.list_bird_groups(callback.from_user.id)
    if not groups:
        lines.append("\nСначала создайте поголовье в разделе Корма -> Поголовье.")
        await callback.message.answer("\n".join(lines), reply_markup=stock_menu_keyboard())
    else:
        await callback.message.answer(
            "\n".join(lines) + "\n\nВыберите поголовье, которому нужно назначить складской корм.",
            reply_markup=stock_assign_groups_keyboard(groups),
        )
        await state.set_state(StockAssignFlow.group)
    await callback.answer()


@router.callback_query(StockAssignFlow.group, F.data.startswith("stock:assign_group:"))
async def stock_assign_group(callback: CallbackQuery, state: FSMContext, stock_service: StockService) -> None:
    group_id = int(str(callback.data).rsplit(":", 1)[1])
    items = stock_service.stock.list_items(callback.from_user.id)
    if not items:
        await callback.message.answer("На складе пока нет позиций. Сначала добавьте покупку.", reply_markup=stock_menu_keyboard())
        await callback.answer()
        return
    await state.update_data(bird_group_id=group_id)
    await state.set_state(StockAssignFlow.item)
    await callback.message.answer(
        "Выберите, какой складской корм ест это поголовье.",
        reply_markup=stock_items_keyboard(items, prefix="stock:assign_item"),
    )
    await callback.answer()


@router.callback_query(StockAssignFlow.item, F.data.startswith("stock:assign_item:"))
async def stock_assign_item(callback: CallbackQuery, state: FSMContext, feed_service: FeedService, stock_service: StockService) -> None:
    item_id = int(str(callback.data).rsplit(":", 1)[1])
    data = await state.get_data()
    group = feed_service.get_bird_group(int(data["bird_group_id"]), callback.from_user.id)
    if group is None:
        await callback.message.answer("Поголовье не найдено.", reply_markup=stock_menu_keyboard())
        await callback.answer()
        return
    await state.update_data(stock_item_id=item_id)
    if group.group_kind == "chicks":
        assignment = stock_service.assign_feed(
            user_id=callback.from_user.id,
            bird_group_id=group.id,
            stock_item_id=item_id,
        )
        await state.clear()
        await callback.message.answer(
            f"Рацион задан: {assignment.bird_group_name} -> {assignment.stock_item_name}.\n"
            "Для цыплят расход считается автоматически по возрасту.",
            reply_markup=stock_menu_keyboard(),
        )
    else:
        await state.set_state(StockAssignFlow.rate)
        await callback.message.answer(
            "Введите средний расход на одну птицу в день в граммах, например 120.",
            reply_markup=feed_cancel_keyboard(),
        )
    await callback.answer()


@router.message(StockAssignFlow.rate)
async def stock_assign_rate(message: Message, state: FSMContext, stock_service: StockService) -> None:
    try:
        daily_g = _parse_float(message.text)
    except ValueError:
        await message.answer("Введите расход в граммах числом, например 120.")
        return
    data = await state.get_data()
    assignment = stock_service.assign_feed(
        user_id=message.from_user.id,
        bird_group_id=int(data["bird_group_id"]),
        stock_item_id=int(data["stock_item_id"]),
        daily_per_bird_g=daily_g,
    )
    await state.clear()
    await message.answer(
        f"Рацион задан: {assignment.bird_group_name} -> {assignment.stock_item_name}, {daily_g:g} г/гол./день.",
        reply_markup=stock_menu_keyboard(),
    )


@router.callback_query(F.data == "stock:adjust")
async def stock_adjust_start(callback: CallbackQuery, state: FSMContext, stock_service: StockService) -> None:
    await state.clear()
    items = stock_service.stock.list_items(callback.from_user.id)
    if not items:
        await callback.message.answer("На складе пока нет позиций.", reply_markup=stock_menu_keyboard())
        await callback.answer()
        return
    await state.set_state(StockAdjustFlow.item)
    await callback.message.answer(
        "Выберите позицию, для которой нужно задать фактический остаток.",
        reply_markup=stock_items_keyboard(items, prefix="stock:adjust_item"),
    )
    await callback.answer()


@router.callback_query(StockAdjustFlow.item, F.data.startswith("stock:adjust_item:"))
async def stock_adjust_item(callback: CallbackQuery, state: FSMContext) -> None:
    item_id = int(str(callback.data).rsplit(":", 1)[1])
    await state.update_data(stock_item_id=item_id)
    await state.set_state(StockAdjustFlow.amount)
    await callback.message.answer(
        "Введите фактический остаток в кг, например 10 или 1 мешок.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.message(StockAdjustFlow.amount)
async def stock_adjust_amount(message: Message, state: FSMContext, stock_service: StockService) -> None:
    try:
        amount_kg = parse_feed_amount(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    data = await state.get_data()
    estimate = stock_service.adjust_stock(
        user_id=message.from_user.id,
        stock_item_id=int(data["stock_item_id"]),
        amount_kg=amount_kg,
    )
    await state.clear()
    if estimate is None:
        await message.answer("Позиция склада не найдена.", reply_markup=stock_menu_keyboard())
        return
    await message.answer(
        "Фактический остаток обновлен.\n\n" + _format_stock_estimate(estimate),
        reply_markup=stock_menu_keyboard(),
    )


@router.callback_query(F.data == "feeds:mix")
async def feed_mix_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(FeedMix.grain_base)
    await callback.message.answer(
        "Что использовать в рецепте на месте пшеницы?",
        reply_markup=grain_base_keyboard("feeds:mix_grain"),
    )
    await callback.answer()


@router.callback_query(FeedMix.grain_base, F.data.startswith("feeds:mix_grain:"))
async def feed_mix_grain_base(callback: CallbackQuery, state: FSMContext) -> None:
    grain_base = str(callback.data).rsplit(":", 1)[1]
    try:
        option = get_grain_base_option(grain_base)
    except ValueError as exc:
        await callback.message.answer(str(exc), reply_markup=feeds_menu_keyboard())
        await callback.answer()
        return
    await state.update_data(grain_base=option.code)
    await state.set_state(FeedMix.amount)
    await callback.message.answer(
        "Сколько готовой смеси рассчитать?\n\n"
        f"Зерновая основа: {option.label}.\n"
        "Можно написать: 25, 25 кг, 1 мешок, 2 мешка по 25.\n"
        "По умолчанию 1 мешок = 25 кг.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.message(FeedMix.amount)
async def feed_mix_amount(message: Message, state: FSMContext) -> None:
    try:
        target_kg = parse_feed_amount(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    data = await state.get_data()
    grain_base = str(data.get("grain_base") or DEFAULT_GRAIN_BASE)
    await state.clear()
    calculation = calculate_chicken_mix(target_kg, grain_base=grain_base)
    await message.answer(
        format_chicken_mix(calculation),
        reply_markup=feeds_menu_keyboard(),
    )


@router.message(NewFeed.name)
async def feed_name_with_service(
    message: Message,
    state: FSMContext,
    feed_service: FeedService,
    incubation_service: IncubationService,
) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_name",
            message="short_name",
        )
        await message.answer("Введите название корма.")
        return
    await state.update_data(name=name)
    await state.set_state(NewFeed.amount)
    groups = feed_service.list_bird_groups(message.from_user.id)
    if groups:
        await state.set_state(NewFeed.group)
        await message.answer(
            "Выберите поголовье для расчета корма или оставьте без привязки.",
            reply_markup=bird_group_select_keyboard(groups, allow_skip=True),
        )
        return
    await message.answer(
        "Укажите начальный остаток корма в кг: например 40, 12.5 кг или 1 мешок.",
        reply_markup=feed_cancel_keyboard(),
    )


@router.callback_query(NewFeed.group, F.data.startswith("feeds:select_group:"))
async def feed_select_group(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    value = str(callback.data).split(":", 2)[2]
    if value != "none":
        group = feed_service.get_bird_group(int(value), callback.from_user.id)
        if group is None:
            await callback.message.answer("Поголовье не найдено. Выберите другое или оставьте корм без привязки.")
            await callback.answer()
            return
        await state.update_data(
            bird_group_id=group.id,
            bird_count=group.bird_count,
            group_kind=group.group_kind,
        )
        group_note = f"Выбрано поголовье {group.name}: {group.bird_count} птиц.\n"
    else:
        await state.update_data(bird_group_id=None)
        group_note = "Корм будет без привязки к поголовью.\n"
    await state.set_state(NewFeed.amount)
    await callback.message.answer(
        group_note + "Укажите начальный остаток корма в кг: например 40, 12.5 кг или 1 мешок.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.message(NewFeed.amount)
async def feed_amount(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    try:
        amount = parse_feed_amount(message.text or "")
    except ValueError:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_amount",
            message="invalid_amount",
        )
        await message.answer("Не понял начальный остаток. Напишите: 40, 12.5 кг, 1 мешок или 2 мешка по 25.")
        return
    await state.update_data(amount_kg=amount)
    data = await state.get_data()
    if data.get("group_kind") == "chicks":
        await state.update_data(
            hen_count=int(data["bird_count"]),
            rooster_count=0,
            daily_per_bird_g=15,
            hen_daily_g=15,
            rooster_daily_g=15,
        )
        await state.set_state(NewFeed.threshold)
        await message.answer(
            "Это корм для цыплят. Расход буду считать автоматически по возрасту с запасом.\n"
            "При каком остатке напомнить о покупке? Введите кг, например 5.",
            reply_markup=feed_cancel_keyboard(),
        )
        return
    if data.get("bird_group_id") is not None:
        await state.set_state(NewFeed.hens)
        await message.answer(
            f"В выбранной группе {data['bird_count']} птиц.\n"
            "Для расчета расхода укажите, сколько из них кур/несушек. "
            "Остальные будут считаться петухами.",
            reply_markup=feed_cancel_keyboard(),
        )
        return
    await state.set_state(NewFeed.hens)
    await message.answer(
        "Для расчета расхода укажите поголовье.\n"
        "Сколько кур/несушек учитывать для этого корма? Если корм общий для всех кур, укажите общее число кур.",
        reply_markup=feed_cancel_keyboard(),
    )


@router.message(NewFeed.hens)
async def feed_hens(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    if not message.text or not message.text.strip().isdigit():
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_hens",
            message="invalid_count",
        )
        await message.answer("Введите количество кур числом, например 25. Если кур нет, введите 0.")
        return
    hen_count = int(message.text.strip())
    data = await state.get_data()
    group_total = data.get("bird_count") if data.get("bird_group_id") is not None else None
    if group_total is not None:
        group_total = int(group_total)
        if hen_count > group_total:
            incubation_service.track_scenario_error(
                user_id=message.from_user.id,
                scenario="feed_hens",
                message="group_hens_too_large",
            )
            await message.answer(
                f"В выбранной группе всего {group_total} птиц. "
                "Введите количество кур/несушек еще раз."
            )
            return
        rooster_count = group_total - hen_count
        await state.update_data(
            hen_count=hen_count,
            rooster_count=rooster_count,
            bird_count=group_total,
        )
        if hen_count == 0:
            await state.set_state(NewFeed.rooster_rate)
            await message.answer(
                f"Учту всю группу как петухов: {rooster_count}.\n"
                "Укажите расход на одного петуха в день.",
                reply_markup=feed_rate_keyboard(),
            )
        elif rooster_count:
            await state.set_state(NewFeed.hen_rate)
            await message.answer(
                f"Учту: кур/несушек {hen_count}, петухов {rooster_count}.\n"
                "Укажите расход на одну курицу/несушку в день.",
                reply_markup=feed_rate_keyboard(),
            )
        else:
            await state.set_state(NewFeed.hen_rate)
            await message.answer(
                "Учту всю группу как кур/несушек.\n"
                "Укажите расход на одну курицу/несушку в день.",
                reply_markup=feed_rate_keyboard(),
            )
        return
    await state.update_data(hen_count=hen_count)
    await state.set_state(NewFeed.roosters)
    await message.answer(
        "Сколько петухов учитывать для этого корма? Если петухов нет или их не нужно учитывать, введите 0.",
        reply_markup=feed_cancel_keyboard(),
    )


@router.message(NewFeed.roosters)
async def feed_roosters(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    if not message.text or not message.text.strip().isdigit():
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_roosters",
            message="invalid_count",
        )
        await message.answer("Введите количество петухов числом, например 2. Если петухов нет, введите 0.")
        return
    rooster_count = int(message.text.strip())
    data = await state.get_data()
    hen_count = int(data.get("hen_count", 0))
    total = hen_count + rooster_count
    if total <= 0:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_roosters",
            message="empty_flock",
        )
        await message.answer("Нужно указать хотя бы одну курицу или одного петуха.")
        return
    group_total = data.get("bird_count") if data.get("bird_group_id") is not None else None
    if group_total is not None and total != int(group_total):
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_roosters",
            message="group_total_mismatch",
        )
        await message.answer(
            f"В выбранной группе {group_total} птиц, а вы указали {total}. "
            "Введите количество петухов еще раз так, чтобы куры + петухи совпали с группой."
        )
        return
    await state.update_data(rooster_count=rooster_count, bird_count=total)
    if hen_count == 0:
        await state.set_state(NewFeed.rooster_rate)
        await message.answer(
            "Кур/несушек нет. Укажите расход на одного петуха в день.",
            reply_markup=feed_rate_keyboard(),
        )
        return
    await state.set_state(NewFeed.hen_rate)
    await message.answer("Укажите расход на одну курицу/несушку в день.", reply_markup=feed_rate_keyboard())


@router.message(NewFeed.birds)
async def feed_birds(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    if not message.text or not message.text.strip().isdigit() or int(message.text.strip()) <= 0:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_birds",
            message="invalid_count",
        )
        await message.answer("Введите количество птиц числом, например 25.")
        return
    await state.update_data(bird_count=int(message.text.strip()))
    await state.set_state(NewFeed.rate)
    await message.answer("Укажите расход на одну птицу в день.", reply_markup=feed_rate_keyboard())


@router.callback_query(NewFeed.rate, F.data.startswith("feed_rate:"))
async def feed_rate_callback(callback: CallbackQuery, state: FSMContext) -> None:
    value = str(callback.data).split(":", 1)[1]
    if value == "manual":
        await callback.message.answer("Введите расход в граммах на птицу в день, например 120.")
        await callback.answer()
        return
    await state.update_data(daily_per_bird_g=float(value))
    await state.set_state(NewFeed.threshold)
    await callback.message.answer(
        "При каком остатке напомнить о покупке? Введите кг, например 5.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(NewFeed.hen_rate, F.data.startswith("feed_rate:"))
async def feed_hen_rate_callback(callback: CallbackQuery, state: FSMContext) -> None:
    value = str(callback.data).split(":", 1)[1]
    if value == "manual":
        await callback.message.answer("Введите расход в граммах на одну курицу/несушку в день, например 120.")
        await callback.answer()
        return
    await state.update_data(hen_daily_g=float(value))
    await state.set_state(NewFeed.rooster_rate)
    data = await state.get_data()
    if int(data.get("rooster_count", 0)) == 0:
        await state.update_data(rooster_daily_g=float(value))
        await state.set_state(NewFeed.threshold)
        await callback.message.answer(
            "Петухов нет, расход для них не нужен.\n"
            "При каком остатке напомнить о покупке? Введите кг, например 5.",
            reply_markup=feed_cancel_keyboard(),
        )
    else:
        await callback.message.answer("Укажите расход на одного петуха в день.", reply_markup=feed_rate_keyboard())
    await callback.answer()


@router.message(NewFeed.hen_rate)
async def feed_hen_rate_message(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    try:
        rate = _parse_float(message.text)
    except ValueError:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_hen_rate",
            message="invalid_rate",
        )
        await message.answer("Введите расход на курицу в граммах, например 120.")
        return
    await state.update_data(hen_daily_g=rate)
    data = await state.get_data()
    if int(data.get("rooster_count", 0)) == 0:
        await state.update_data(rooster_daily_g=rate)
        await state.set_state(NewFeed.threshold)
        await message.answer(
            "Петухов нет, расход для них не нужен.\n"
            "При каком остатке напомнить о покупке? Введите кг, например 5.",
            reply_markup=feed_cancel_keyboard(),
        )
        return
    await state.set_state(NewFeed.rooster_rate)
    await message.answer("Укажите расход на одного петуха в день.", reply_markup=feed_rate_keyboard())


@router.callback_query(NewFeed.rooster_rate, F.data.startswith("feed_rate:"))
async def feed_rooster_rate_callback(callback: CallbackQuery, state: FSMContext) -> None:
    value = str(callback.data).split(":", 1)[1]
    if value == "manual":
        await callback.message.answer("Введите расход в граммах на одного петуха в день, например 150.")
        await callback.answer()
        return
    await state.update_data(rooster_daily_g=float(value))
    await state.set_state(NewFeed.threshold)
    await callback.message.answer(
        "При каком остатке напомнить о покупке? Введите кг, например 5.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.message(NewFeed.rooster_rate)
async def feed_rooster_rate_message(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    try:
        rate = _parse_float(message.text)
    except ValueError:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_rooster_rate",
            message="invalid_rate",
        )
        await message.answer("Введите расход на петуха в граммах, например 150.")
        return
    await state.update_data(rooster_daily_g=rate)
    await state.set_state(NewFeed.threshold)
    await message.answer(
        "При каком остатке напомнить о покупке? Введите кг, например 5.",
        reply_markup=feed_cancel_keyboard(),
    )


@router.message(NewFeed.rate)
async def feed_rate_message(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    try:
        rate = _parse_float(message.text)
    except ValueError:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_rate",
            message="invalid_rate",
        )
        await message.answer("Введите расход в граммах, например 120.")
        return
    await state.update_data(daily_per_bird_g=rate)
    await state.set_state(NewFeed.threshold)
    await message.answer(
        "При каком остатке напомнить о покупке? Введите кг, например 5.",
        reply_markup=feed_cancel_keyboard(),
    )


@router.message(NewFeed.threshold)
async def feed_threshold(
    message: Message,
    state: FSMContext,
    feed_service: FeedService,
    incubation_service: IncubationService,
) -> None:
    try:
        threshold = _parse_float(message.text, allow_zero=True)
    except ValueError:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_threshold",
            message="invalid_threshold",
        )
        await message.answer("Введите порог в кг, например 5.")
        return
    data = await state.get_data()
    feed = feed_service.create_feed(
        user_id=message.from_user.id,
        name=str(data["name"]),
        amount_kg=float(data["amount_kg"]),
        bird_count=int(data["bird_count"]),
        daily_per_bird_g=float(data.get("hen_daily_g", data.get("daily_per_bird_g", 120))),
        low_threshold_kg=threshold,
        bird_group_id=(
            int(data["bird_group_id"])
            if data.get("bird_group_id") is not None
            else None
        ),
        hen_count=int(data.get("hen_count", data["bird_count"])),
        rooster_count=int(data.get("rooster_count", 0)),
        hen_daily_g=float(data.get("hen_daily_g", data.get("daily_per_bird_g", 120))),
        rooster_daily_g=float(data.get("rooster_daily_g", data.get("hen_daily_g", data.get("daily_per_bird_g", 120)))),
    )
    await state.clear()
    estimate = feed_service.estimate(feed)
    await message.answer(
        "Корм добавлен.\n\n" + _format_estimate(estimate),
        reply_markup=feed_actions_keyboard(feed.id),
    )


@router.callback_query(F.data.startswith("feeds:view:"))
async def feed_view(callback: CallbackQuery, feed_service: FeedService) -> None:
    feed_id = int(str(callback.data).split(":", 2)[2])
    estimate = feed_service.get_estimate(feed_id, callback.from_user.id)
    if estimate is None:
        await callback.message.answer("Корм не найден.", reply_markup=feeds_menu_keyboard())
    else:
        await callback.message.answer(
            _format_estimate(estimate),
            reply_markup=feed_actions_keyboard(feed_id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("feeds:delete:"))
async def feed_delete(callback: CallbackQuery) -> None:
    feed_id = int(str(callback.data).split(":", 2)[2])
    await callback.message.answer("Архивировать этот корм? История операций сохранится.", reply_markup=feed_delete_confirm_keyboard(feed_id))
    await callback.answer()


@router.callback_query(F.data.startswith("feeds:restock:"))
async def feed_restock_start(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    feed_id = int(str(callback.data).split(":", 2)[2])
    estimate = feed_service.get_estimate(feed_id, callback.from_user.id)
    if estimate is None:
        await callback.message.answer("Корм не найден.", reply_markup=feeds_menu_keyboard())
        await callback.answer()
        return

    await state.clear()
    await state.update_data(feed_id=feed_id)
    await state.set_state(RestockFeed.amount)
    await callback.message.answer(
        f"Текущий расчетный остаток: {estimate.remaining_kg:.1f} кг.\n"
        "Задайте фактический остаток на складе. Можно написать: 25 кг, 1 мешок, 2 мешка по 25.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("feeds:add_amount:"))
async def feed_add_amount_start(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    feed_id = int(str(callback.data).split(":", 2)[2])
    estimate = feed_service.get_estimate(feed_id, callback.from_user.id)
    if estimate is None:
        await callback.message.answer("Корм не найден.", reply_markup=feeds_menu_keyboard())
        await callback.answer()
        return
    await state.clear()
    await state.update_data(feed_id=feed_id, action="add")
    await state.set_state(ChangeFeed.amount)
    await callback.message.answer(
        f"Текущий расчетный остаток: {estimate.remaining_kg:.1f} кг.\n"
        "Сколько добавить к остатку? Например 10 кг или 1 мешок.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("feeds:write_off:"))
async def feed_write_off_start(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    feed_id = int(str(callback.data).split(":", 2)[2])
    estimate = feed_service.get_estimate(feed_id, callback.from_user.id)
    if estimate is None:
        await callback.message.answer("Корм не найден.", reply_markup=feeds_menu_keyboard())
        await callback.answer()
        return
    await state.clear()
    await state.update_data(feed_id=feed_id, action="write_off")
    await state.set_state(ChangeFeed.amount)
    await callback.message.answer(
        f"Текущий расчетный остаток: {estimate.remaining_kg:.1f} кг.\n"
        "Сколько списать? Например 3 кг или 0.5.",
        reply_markup=feed_cancel_keyboard(),
    )
    await callback.answer()


@router.message(ChangeFeed.amount)
async def feed_change_amount(message: Message, state: FSMContext, feed_service: FeedService) -> None:
    try:
        amount_kg = parse_feed_amount(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    data = await state.get_data()
    feed_id = int(data["feed_id"])
    action = str(data["action"])
    try:
        if action == "add":
            feed = feed_service.add_feed_amount(
                feed_id=feed_id,
                user_id=message.from_user.id,
                amount_kg=amount_kg,
            )
            prefix = "Пополнение сохранено."
        else:
            feed = feed_service.write_off_feed(
                feed_id=feed_id,
                user_id=message.from_user.id,
                amount_kg=amount_kg,
            )
            prefix = "Списание сохранено."
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await state.clear()
    if feed is None:
        await message.answer("Корм не найден.", reply_markup=feeds_menu_keyboard())
        return
    await message.answer(
        prefix + "\n\n" + _format_estimate(feed_service.estimate(feed)),
        reply_markup=feed_actions_keyboard(feed.id),
    )


@router.callback_query(F.data.startswith("feeds:history:"))
async def feed_history(callback: CallbackQuery, feed_service: FeedService) -> None:
    feed_id = int(str(callback.data).split(":", 2)[2])
    transactions = feed_service.list_transactions(feed_id, callback.from_user.id)
    if not transactions:
        await callback.message.answer("История операций пока пустая.", reply_markup=feed_actions_keyboard(feed_id))
        await callback.answer()
        return
    lines = ["История корма:"]
    labels = {
        "initial": "начальный остаток",
        "restock": "пополнение",
        "write_off": "списание",
        "adjustment": "задан остаток",
    }
    for item in transactions[:10]:
        sign = "+" if item.amount_kg > 0 else ""
        lines.append(
            f"- {item.created_at.date().isoformat()} {labels.get(item.type, item.type)}: "
            f"{sign}{item.amount_kg:g} кг, остаток {item.balance_after_kg:g} кг"
        )
    await callback.message.answer("\n".join(lines), reply_markup=feed_actions_keyboard(feed_id))
    await callback.answer()


@router.callback_query(F.data.startswith("feeds:edit:"))
async def feed_edit_menu(callback: CallbackQuery) -> None:
    feed_id = int(str(callback.data).split(":", 2)[2])
    await callback.message.answer("Что изменить?", reply_markup=feed_edit_keyboard(feed_id))
    await callback.answer()


@router.callback_query(F.data.startswith("feeds:edit_field:"))
async def feed_edit_field(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    _, _, feed_id_text, field = str(callback.data).split(":", 3)
    await state.clear()
    await state.update_data(feed_id=int(feed_id_text), field=field)
    await state.set_state(EditFeed.value)
    prompts = {
        "name": "Введите новое название корма.",
        "birds": "Введите новое общее поголовье для расчета расхода.",
        "hens": "Введите новое количество кур/несушек для расчета расхода.",
        "roosters": "Введите новое количество петухов для расчета расхода.",
        "rate": "Введите новый расход в граммах на птицу в день.",
        "hen_rate": "Введите новый расход в граммах на курицу/несушку в день.",
        "rooster_rate": "Введите новый расход в граммах на петуха в день.",
        "threshold": "Введите новый порог предупреждения в кг.",
        "group": "Выберите новое поголовье или оставьте корм без привязки.",
    }
    if field == "group":
        groups = feed_service.list_bird_groups(callback.from_user.id)
        await state.set_state(EditFeed.group)
        await callback.message.answer(
            "Выберите новое поголовье или оставьте корм без привязки.",
            reply_markup=bird_group_select_keyboard(groups, allow_skip=True, prefix="feeds:edit_group"),
        )
        await callback.answer()
        return
    await callback.message.answer(prompts.get(field, "Введите новое значение."), reply_markup=feed_cancel_keyboard())
    await callback.answer()


@router.callback_query(EditFeed.group, F.data.startswith("feeds:edit_group:"))
async def feed_edit_group(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    data = await state.get_data()
    feed_id = int(data["feed_id"])
    value = str(callback.data).split(":", 2)[2]
    if value == "none":
        feed = feed_service.update_feed(
            feed_id=feed_id,
            user_id=callback.from_user.id,
            clear_bird_group=True,
        )
    else:
        group = feed_service.get_bird_group(int(value), callback.from_user.id)
        if group is None:
            await callback.message.answer("Поголовье не найдено.")
            await callback.answer()
            return
        feed = feed_service.update_feed(
            feed_id=feed_id,
            user_id=callback.from_user.id,
            bird_group_id=group.id,
            bird_count=group.bird_count,
        )
    await state.clear()
    if feed is None:
        await callback.message.answer("Корм не найден.", reply_markup=feeds_menu_keyboard())
    else:
        await callback.message.answer(
            "Поголовье корма обновлено.\n\n" + _format_estimate(feed_service.estimate(feed)),
            reply_markup=feed_actions_keyboard(feed.id),
        )
    await callback.answer()


@router.message(EditFeed.value)
async def feed_edit_value(
    message: Message,
    state: FSMContext,
    feed_service: FeedService,
    incubation_service: IncubationService,
) -> None:
    data = await state.get_data()
    feed_id = int(data["feed_id"])
    field = str(data["field"])
    value = (message.text or "").strip()
    try:
        kwargs = {}
        if field == "name":
            kwargs["name"] = value
        elif field == "birds":
            if not value.isdigit():
                incubation_service.track_scenario_error(
                    user_id=message.from_user.id,
                    scenario="feed_edit_birds",
                    message="invalid_count",
                )
                raise ValueError("Количество птиц должно быть числом.")
            kwargs["bird_count"] = int(value)
            kwargs["hen_count"] = int(value)
            kwargs["rooster_count"] = 0
        elif field == "hens":
            if not value.isdigit():
                incubation_service.track_scenario_error(
                    user_id=message.from_user.id,
                    scenario="feed_edit_hens",
                    message="invalid_count",
                )
                raise ValueError("Количество кур должно быть числом.")
            kwargs["hen_count"] = int(value)
        elif field == "roosters":
            if not value.isdigit():
                incubation_service.track_scenario_error(
                    user_id=message.from_user.id,
                    scenario="feed_edit_roosters",
                    message="invalid_count",
                )
                raise ValueError("Количество петухов должно быть числом.")
            kwargs["rooster_count"] = int(value)
        elif field == "rate":
            kwargs["daily_per_bird_g"] = _parse_float(value)
        elif field == "hen_rate":
            kwargs["hen_daily_g"] = _parse_float(value)
        elif field == "rooster_rate":
            kwargs["rooster_daily_g"] = _parse_float(value)
        elif field == "threshold":
            kwargs["low_threshold_kg"] = _parse_float(value, allow_zero=True)
        else:
            raise ValueError("Неизвестное поле.")
        feed = feed_service.update_feed(
            feed_id=feed_id,
            user_id=message.from_user.id,
            **kwargs,
        )
    except ValueError as exc:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario=f"feed_edit_{field}",
            message=str(exc),
        )
        await message.answer(str(exc))
        return

    await state.clear()
    if feed is None:
        await message.answer("Корм не найден.", reply_markup=feeds_menu_keyboard())
        return
    await message.answer(
        "Корм обновлен.\n\n" + _format_estimate(feed_service.estimate(feed)),
        reply_markup=feed_actions_keyboard(feed.id),
    )


@router.message(RestockFeed.amount)
async def feed_restock_amount(
    message: Message,
    state: FSMContext,
    feed_service: FeedService,
    incubation_service: IncubationService,
) -> None:
    try:
        amount_kg = parse_feed_amount(message.text or "")
    except ValueError as exc:
        incubation_service.track_scenario_error(
            user_id=message.from_user.id,
            scenario="feed_restock",
            message=str(exc),
        )
        await message.answer(str(exc))
        return

    data = await state.get_data()
    feed_id = int(data["feed_id"])
    try:
        feed = feed_service.restock_feed(
            feed_id=feed_id,
            user_id=message.from_user.id,
            amount_kg=amount_kg,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await state.clear()
    if feed is None:
        await message.answer("Корм не найден.", reply_markup=feeds_menu_keyboard())
        return

    estimate = feed_service.estimate(feed)
    await message.answer(
        "Запас обновлен. Напоминание о покупке снова активно.\n\n" + _format_estimate(estimate),
        reply_markup=feed_actions_keyboard(feed.id),
    )


@router.callback_query(F.data.startswith("feeds:delete_confirm:"))
async def feed_delete_confirm(callback: CallbackQuery, feed_service: FeedService) -> None:
    feed_id = int(str(callback.data).split(":", 2)[2])
    deleted = feed_service.delete_feed(feed_id, callback.from_user.id)
    await callback.message.answer(
        "Корм архивирован." if deleted else "Корм не найден.",
        reply_markup=feeds_menu_keyboard(),
    )
    await callback.answer()


def _format_stock_menu(estimates) -> str:
    if not estimates:
        return (
            "📦 Склад\n\n"
            "Склад пока пустой. Добавьте покупку ингредиента, готового корма или смеси."
        )
    groups = {
        "finished_mix": ["Готовая смесь:"],
        "ingredient": ["Ингредиенты:"],
        "commercial_feed": ["Готовые корма:"],
        "other": ["Другое:"],
    }
    for estimate in estimates:
        groups.setdefault(estimate.item.kind, [STOCK_KIND_LABELS.get(estimate.item.kind, estimate.item.kind) + ":"])
        days = "не расходуется" if estimate.days_left is None else f"хватит примерно на {estimate.days_left} дн."
        usage = (
            ""
            if estimate.daily_usage_kg <= 0
            else f", расход {estimate.daily_usage_kg:.2f} кг/день"
        )
        groups[estimate.item.kind].append(
            f"- {estimate.item.name}: {estimate.remaining_kg:.1f} кг ({days}{usage})"
        )
    lines = ["📦 Склад"]
    for key in ("finished_mix", "ingredient", "commercial_feed", "other"):
        if len(groups[key]) > 1:
            lines.append("")
            lines.extend(groups[key])
    return "\n".join(lines)


def _format_stock_estimate(estimate) -> str:
    days = "не расходуется" if estimate.days_left is None else f"{estimate.days_left} дн."
    return (
        f"{estimate.item.name}\n"
        f"Тип: {STOCK_KIND_LABELS.get(estimate.item.kind, estimate.item.kind)}\n"
        f"Остаток расчетный: {estimate.remaining_kg:.1f} кг\n"
        f"Расход: {estimate.daily_usage_kg:.2f} кг/день\n"
        f"Хватит примерно: {days}"
    )


def _format_mix_plan(plan) -> str:
    lines = [
        f"🧮 {plan.title}",
        "",
        f"Зерновая основа: {plan.grain_base_label}",
        f"Замесов: {plan.mix_count:g}",
        f"Будет получено примерно: {plan.output_kg:.1f} кг.",
        "",
        "Будет списано:",
    ]
    for ingredient in plan.ingredients:
        if ingredient.missing_kg > 0:
            lines.append(
                f"- {ingredient.name}: нужно {ingredient.required_kg:.2f} кг, "
                f"есть {ingredient.available_kg:.2f} кг, не хватает {ingredient.missing_kg:.2f} кг"
            )
        else:
            lines.append(f"- {ingredient.name}: {ingredient.required_kg:.2f} кг")
    lines.append("")
    if plan.can_produce:
        lines.append("Создать замес?")
    else:
        lines.append(f"Ингредиентов не хватает. Максимум сейчас: {plan.max_mix_count:.1f} замеса.")
    lines.append("Расчет примерный: вес зависит от влажности и фракции ингредиентов.")
    return "\n".join(lines)


def _parse_float(value: str | None, *, allow_zero: bool = False) -> float:
    if value is None:
        raise ValueError("empty")
    parsed = float(value.strip().replace(",", "."))
    if not isfinite(parsed) or parsed < 0 or (parsed == 0 and not allow_zero):
        raise ValueError("not positive")
    return parsed


def _format_estimate(estimate: FeedEstimate) -> str:
    feed = estimate.feed
    days_left = "неизвестно" if estimate.days_left is None else f"{estimate.days_left} дн."
    threshold = (
        "неизвестно"
        if estimate.threshold_days_left is None
        else f"через {estimate.threshold_days_left} дн."
    )
    hen_daily_g = feed.hen_daily_g if feed.hen_daily_g is not None else feed.daily_per_bird_g
    rooster_daily_g = (
        feed.rooster_daily_g if feed.rooster_daily_g is not None else feed.daily_per_bird_g
    )
    if feed.bird_group_kind == "chicks":
        hatch_text = feed.bird_group_hatched_at.isoformat() if feed.bird_group_hatched_at else "не указана"
        joined_text = feed.bird_group_joined_at.isoformat() if feed.bird_group_joined_at else "не задана"
        status = (
            "Цыплята уже подсажены, отдельный расход этого корма остановлен."
            if estimate.daily_usage_kg == 0
            else f"Расход цыплят с запасом {feed.bird_group_reserve_percent:g}%: {estimate.daily_usage_kg:.2f} кг/день"
        )
        return (
            f"#{feed.id} {feed.name}\n"
            f"Поголовье: {feed.bird_group_name or 'цыплята'}\n"
            f"Цыплят: {feed.bird_count}\n"
            f"Дата вывода: {hatch_text}\n"
            f"Дата подсадки: {joined_text}\n"
            f"Остаток расчетный: {estimate.remaining_kg:.1f} кг из {feed.amount_kg:g} кг\n"
            f"{status}\n"
            f"Хватит примерно: {days_left}\n"
            f"Напомнить при остатке: {feed.low_threshold_kg:g} кг ({threshold})"
        )
    return (
        f"#{feed.id} {feed.name}\n"
        f"Поголовье: {feed.bird_group_name or 'не указано'}\n"
        f"Остаток расчетный: {estimate.remaining_kg:.1f} кг из {feed.amount_kg:g} кг\n"
        f"Птиц: {feed.bird_count} (кур/несушек: {feed.hen_count}, петухов: {feed.rooster_count})\n"
        f"Расход кур: {hen_daily_g:g} г/гол./день\n"
        f"Расход петухов: {rooster_daily_g:g} г/гол./день\n"
        f"Общий расход: {estimate.daily_usage_kg:.2f} кг/день\n"
        f"Хватит примерно: {days_left}\n"
        f"Напомнить при остатке: {feed.low_threshold_kg:g} кг ({threshold})"
    )
