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
)
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.services.feed_recipes import (
    calculate_chicken_mix,
    format_chicken_mix,
    parse_feed_amount,
)


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
    count = State()
    species = State()


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
    FeedMix.amount,
    RestockFeed.amount,
    ChangeFeed.amount,
    EditFeed.value,
    EditFeed.group,
    BirdGroupFlow.name,
    BirdGroupFlow.count,
    BirdGroupFlow.species,
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
            "🌾 Корма\n\nЗапасов пока нет. Добавьте корм, количество птиц и расход на голову — я посчитаю остаток и напомню о покупке.",
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
        text = "Групп птицы пока нет. Создайте группу, чтобы привязывать к ней корма."
    else:
        lines = ["Группы птицы:"]
        for group in groups:
            species = f", {PROFILES[group.species].title}" if group.species in PROFILES else ""
            lines.append(f"- #{group.id} {group.name}: {group.bird_count} птиц{species}")
        text = "\n".join(lines)
    await callback.message.answer(text, reply_markup=bird_groups_keyboard())
    await callback.answer()


@router.callback_query(F.data == "feeds:group_add")
async def bird_group_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BirdGroupFlow.name)
    await callback.message.answer("Введите название группы, например Несушки.", reply_markup=feed_cancel_keyboard())
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
        await message.answer("Введите название группы минимум из двух символов.")
        return
    await state.update_data(name=name)
    await state.set_state(BirdGroupFlow.count)
    await message.answer("Сколько птиц в группе? Введите число.", reply_markup=feed_cancel_keyboard())


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
    await state.set_state(BirdGroupFlow.species)
    rows = [
        [InlineKeyboardButton(text=profile.title, callback_data=f"feeds:group_species:{code}")]
        for code, profile in PROFILES.items()
    ]
    rows.append([InlineKeyboardButton(text="Без вида", callback_data="feeds:group_species:none")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")])
    await message.answer(
        "Выберите вид птицы для группы или оставьте без вида.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
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
    )
    await state.clear()
    await callback.message.answer(
        f"Группа создана: #{group.id} {group.name}, {group.bird_count} птиц.",
        reply_markup=bird_groups_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "feeds:mix")
async def feed_mix_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(FeedMix.amount)
    await callback.message.answer(
        "Сколько готовой смеси рассчитать?\n\n"
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

    await state.clear()
    calculation = calculate_chicken_mix(target_kg)
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
            "Выберите группу птицы для корма или оставьте без группы.",
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
            await callback.message.answer("Группа не найдена. Выберите другую или оставьте без группы.")
            await callback.answer()
            return
        await state.update_data(bird_group_id=group.id, bird_count=group.bird_count)
        group_note = f"Выбрана группа {group.name}: {group.bird_count} птиц.\n"
    else:
        await state.update_data(bird_group_id=None)
        group_note = "Корм будет без группы птицы.\n"
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
        "group": "Выберите новую группу птицы или оставьте корм без группы.",
    }
    if field == "group":
        groups = feed_service.list_bird_groups(callback.from_user.id)
        await state.set_state(EditFeed.group)
        await callback.message.answer(
            "Выберите новую группу птицы или оставьте корм без группы.",
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
            await callback.message.answer("Группа не найдена.")
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
            "Группа корма обновлена.\n\n" + _format_estimate(feed_service.estimate(feed)),
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
    return (
        f"#{feed.id} {feed.name}\n"
        f"Группа: {feed.bird_group_name or 'не указана'}\n"
        f"Остаток расчетный: {estimate.remaining_kg:.1f} кг из {feed.amount_kg:g} кг\n"
        f"Птиц: {feed.bird_count} (кур/несушек: {feed.hen_count}, петухов: {feed.rooster_count})\n"
        f"Расход кур: {hen_daily_g:g} г/гол./день\n"
        f"Расход петухов: {rooster_daily_g:g} г/гол./день\n"
        f"Общий расход: {estimate.daily_usage_kg:.2f} кг/день\n"
        f"Хватит примерно: {days_left}\n"
        f"Напомнить при остатке: {feed.low_threshold_kg:g} кг ({threshold})"
    )
