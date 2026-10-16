"""Losses of birds, eggs that left the house (sold / given), purchase prices and the cost of an egg."""

from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.services.feeds import FeedService
from app.services.ledger import (
    LOSS_REASONS,
    MAX_BIRDS,
    MAX_EGGS,
    OUTFLOW_KINDS,
    LedgerService,
    format_cost_report,
    format_rub,
    parse_count,
    parse_rub,
)
from app.services.stock import StockService
from app.utils.dates import local_today


router = Router()


class LossFlow(StatesGroup):
    count = State()


class OutFlow(StatesGroup):
    count = State()
    amount = State()


class PriceFlow(StatesGroup):
    amount = State()


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows]
    )


CANCEL = ("Отмена", "ledger:cancel")
HOME = ("🏠 Главное меню", "menu:home")


def livestock_back_keyboard(undo: str | None = None) -> InlineKeyboardMarkup:
    rows = [[("↩️ Отменить запись", undo)]] if undo else []
    rows += [
        [("📉 Потери", "ledger:losses")],
        [("⬅️ Поголовье и стада", "feeds:livestock")],
        [HOME],
    ]
    return _kb(rows)


def eggs_out_back_keyboard(undo: str | None = None) -> InlineKeyboardMarkup:
    rows = [[("↩️ Отменить запись", undo)]] if undo else []
    rows += [
        [("📤 Ещё запись", "ledger:out"), ("💰 Продажи", "ledger:out_list")],
        [("⬅️ К яйцам", "eggs:menu")],
        [HOME],
    ]
    return _kb(rows)


def _today() -> object:
    return local_today()


@router.callback_query(F.data == "ledger:cancel")
async def ledger_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    await callback.message.answer("Запись отменена.", reply_markup=_kb([[HOME]]))


# --- losses -------------------------------------------------------------------


@router.callback_query(F.data == "ledger:loss")
async def loss_start(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    await state.clear()
    groups = [group for group in feed_service.list_bird_groups(callback.from_user.id) if group.is_active]
    await callback.answer()
    if not groups:
        await callback.message.answer(
            "Нет активных групп поголовья.", reply_markup=livestock_back_keyboard()
        )
        return
    rows = [[(f"{group.name[:28]} ({group.bird_count})", f"ledger:loss_group:{group.id}")] for group in groups]
    rows.append([CANCEL])
    await callback.message.answer("Из какой группы выбыли птицы?", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("ledger:loss_group:"))
async def loss_group(callback: CallbackQuery, state: FSMContext, feed_service: FeedService) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    group = feed_service.get_bird_group(int(raw), callback.from_user.id) if raw.isdigit() else None
    if group is None or not group.is_active:
        await callback.answer("Группа не найдена.", show_alert=True)
        return
    await state.set_state(LossFlow.count)
    await state.update_data(loss_group_id=group.id)
    await callback.answer()
    quick = [(str(n), f"ledger:loss_n:{n}") for n in (1, 2, 3) if n <= group.bird_count]
    await callback.message.answer(
        f"«{group.name}»: сейчас {group.bird_count} птиц. Сколько выбыло? Нажмите или напишите число.\n\nОтмена: /cancel",
        reply_markup=_kb([quick, [CANCEL]]),
    )


async def _ask_reason(target: Message, state: FSMContext, count: int) -> None:
    await state.update_data(loss_count=count)
    rows = [[(label, f"ledger:loss_reason:{code}")] for code, label in LOSS_REASONS.items()]
    rows.append([CANCEL])
    await target.answer(f"Выбыло: {count}. Причина?", reply_markup=_kb(rows))


@router.callback_query(LossFlow.count, F.data.startswith("ledger:loss_n:"))
async def loss_count_button(callback: CallbackQuery, state: FSMContext) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    await callback.answer()
    await _ask_reason(callback.message, state, int(raw) if raw.isdigit() else 1)


@router.message(LossFlow.count)
async def loss_count_text(message: Message, state: FSMContext) -> None:
    try:
        count = parse_count(message.text or "", limit=MAX_BIRDS, what="птиц")
    except ValueError as exc:
        await message.answer(f"{exc}\n\nОтмена: /cancel")
        return
    await _ask_reason(message, state, count)


@router.callback_query(F.data.startswith("ledger:loss_reason:"))
async def loss_reason(callback: CallbackQuery, state: FSMContext, ledger_service: LedgerService) -> None:
    data = await state.get_data()
    reason = str(callback.data).rsplit(":", 1)[1]
    if "loss_group_id" not in data or "loss_count" not in data:
        await callback.answer("Начните запись заново.", show_alert=True)
        return
    try:
        loss = ledger_service.record_loss(
            user_id=callback.from_user.id,
            bird_group_id=int(data["loss_group_id"]),
            count=int(data["loss_count"]),
            reason=reason,
            occurred_on=_today(),
        )
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await state.clear()
    await callback.answer("Записано")
    tail = (
        " Группа стала пустой и ушла в архив."
        if loss.group_archived
        else " Поголовье уменьшено, норма корма и прогноз яиц пересчитаны."
    )
    summary = ledger_service.loss_summary(callback.from_user.id, today=_today())
    lines = [f"Записано: «{loss.group_name}» −{loss.count} ({LOSS_REASONS[loss.reason].lower()}).{tail}"]
    lines.append(f"За 30 дней выбыло: {summary.total}.")
    if summary.rising:
        lines.append(
            f"⚠️ Это больше, чем за прошлые 30 дней ({summary.previous_total}). "
            "Проверьте птиц, корм, воду и курятник — см. «Птицевод → Проблема с птицей»."
        )
    await callback.message.answer(
        "\n".join(lines), reply_markup=livestock_back_keyboard(f"ledger:loss_undo:{loss.id}")
    )


@router.callback_query(F.data.startswith("ledger:loss_undo:"))
async def loss_undo(callback: CallbackQuery, ledger_service: LedgerService) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    loss = ledger_service.undo_loss(callback.from_user.id, int(raw)) if raw.isdigit() else None
    if loss is None:
        await callback.answer("Эта запись уже отменена.", show_alert=True)
        return
    await callback.answer("Отменено")
    tail = " Группа возвращена из архива; если она была в стаде, добавьте её обратно." if loss.group_archived else ""
    await callback.message.answer(
        f"Запись отменена: «{loss.group_name}» снова +{loss.count}.{tail}", reply_markup=livestock_back_keyboard()
    )


@router.callback_query(F.data == "ledger:losses")
async def losses_list(callback: CallbackQuery, state: FSMContext, ledger_service: LedgerService) -> None:
    await state.clear()
    await callback.answer()
    user_id = callback.from_user.id
    summary = ledger_service.loss_summary(user_id, today=_today())
    recent = ledger_service.recent_losses(user_id, limit=10)
    lines = ["📉 Потери поголовья", ""]
    if not recent:
        lines.append("Записей нет. Если птица пала или ушла на мясо, нажмите «➖ Падёж / выбыло».")
    else:
        lines.append(f"За 30 дней: {summary.total} (за прошлые 30 дней: {summary.previous_total}).")
        if summary.by_reason:
            lines.append(
                "По причинам: "
                + ", ".join(f"{LOSS_REASONS[code].lower()} {count}" for code, count in summary.by_reason.items())
                + "."
            )
        lines.extend(["", "Последние записи:"])
        lines.extend(
            f"- {loss.occurred_on.strftime('%d.%m')}: «{loss.group_name}» −{loss.count}, {LOSS_REASONS.get(loss.reason, loss.reason).lower()}"
            for loss in recent
        )
    rows = [[("➖ Падёж / выбыло", "ledger:loss")]]
    rows += [[(f"↩️ Отменить {loss.occurred_on.strftime('%d.%m')} −{loss.count}", f"ledger:loss_undo:{loss.id}")] for loss in recent[:3]]
    rows += [[("⬅️ Поголовье и стада", "feeds:livestock")], [HOME]]
    await callback.message.answer("\n".join(lines), reply_markup=_kb(rows))


# --- eggs out -----------------------------------------------------------------


@router.callback_query(F.data == "ledger:out")
async def out_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    rows = [[(label, f"ledger:out_kind:{code}")] for code, label in OUTFLOW_KINDS.items()]
    rows.append([CANCEL])
    await callback.message.answer("Куда ушли яйца?", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("ledger:out_kind:"))
async def out_kind(callback: CallbackQuery, state: FSMContext) -> None:
    kind = str(callback.data).rsplit(":", 1)[1]
    if kind not in OUTFLOW_KINDS:
        await callback.answer("Выберите вариант из списка.", show_alert=True)
        return
    await state.set_state(OutFlow.count)
    await state.update_data(out_kind=kind)
    await callback.answer()
    quick = [(str(n), f"ledger:out_n:{n}") for n in (10, 20, 30)]
    await callback.message.answer(
        f"{OUTFLOW_KINDS[kind]}: сколько яиц? Нажмите или напишите число.\n\nОтмена: /cancel",
        reply_markup=_kb([quick, [CANCEL]]),
    )


async def _after_count(target: Message, state: FSMContext, ledger_service: LedgerService, user_id: int, count: int) -> None:
    data = await state.get_data()
    kind = str(data.get("out_kind") or "")
    await state.update_data(out_count=count)
    if kind == "sold":
        await state.set_state(OutFlow.amount)
        await target.answer(
            f"Продали {count} яиц. За сколько всего, в рублях? Например 300.\n\nОтмена: /cancel",
            reply_markup=_kb([[("Без суммы", "ledger:out_noamount")], [CANCEL]]),
        )
        return
    await _record_outflow(target, state, ledger_service, user_id, amount=None)


async def _record_outflow(
    target: Message, state: FSMContext, ledger_service: LedgerService, user_id: int, *, amount: float | None
) -> None:
    data = await state.get_data()
    try:
        outflow = ledger_service.record_outflow(
            user_id=user_id,
            kind=str(data.get("out_kind") or ""),
            eggs_count=int(data.get("out_count") or 0),
            amount_rub=amount,
            occurred_on=_today(),
        )
    except ValueError as exc:
        await state.clear()
        await target.answer(str(exc), reply_markup=eggs_out_back_keyboard())
        return
    await state.clear()
    line = f"Записано: {OUTFLOW_KINDS[outflow.kind].lower()} {outflow.eggs_count} яиц"
    if outflow.amount_rub:
        line += f" за {format_rub(outflow.amount_rub)} ({format_rub(outflow.amount_rub / outflow.eggs_count * 10)} за десяток)"
    lines = [line + "."]
    balance = ledger_service.egg_balance(user_id, today=_today())
    if balance is not None:
        lines.append(f"Дома примерно {balance.at_home} яиц (считаю с {balance.since.strftime('%d.%m')}).")
    await target.answer("\n".join(lines), reply_markup=eggs_out_back_keyboard(f"ledger:out_undo:{outflow.id}"))


@router.callback_query(OutFlow.count, F.data.startswith("ledger:out_n:"))
async def out_count_button(callback: CallbackQuery, state: FSMContext, ledger_service: LedgerService) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    await callback.answer()
    await _after_count(callback.message, state, ledger_service, callback.from_user.id, int(raw) if raw.isdigit() else 10)


@router.message(OutFlow.count)
async def out_count_text(message: Message, state: FSMContext, ledger_service: LedgerService) -> None:
    try:
        count = parse_count(message.text or "", limit=MAX_EGGS, what="яиц")
    except ValueError as exc:
        await message.answer(f"{exc}\n\nОтмена: /cancel")
        return
    await _after_count(message, state, ledger_service, message.from_user.id, count)


@router.callback_query(OutFlow.amount, F.data == "ledger:out_noamount")
async def out_no_amount(callback: CallbackQuery, state: FSMContext, ledger_service: LedgerService) -> None:
    await callback.answer()
    await _record_outflow(callback.message, state, ledger_service, callback.from_user.id, amount=None)


@router.message(OutFlow.amount)
async def out_amount_text(message: Message, state: FSMContext, ledger_service: LedgerService) -> None:
    try:
        amount = parse_rub(message.text or "")
    except ValueError as exc:
        await message.answer(f"{exc}\n\nОтмена: /cancel")
        return
    await _record_outflow(message, state, ledger_service, message.from_user.id, amount=amount or None)


@router.callback_query(F.data.startswith("ledger:out_undo:"))
async def out_undo(callback: CallbackQuery, ledger_service: LedgerService) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    outflow = ledger_service.undo_outflow(callback.from_user.id, int(raw)) if raw.isdigit() else None
    if outflow is None:
        await callback.answer("Эта запись уже отменена.", show_alert=True)
        return
    await callback.answer("Отменено")
    await callback.message.answer(
        f"Запись отменена: {OUTFLOW_KINDS[outflow.kind].lower()} {outflow.eggs_count} яиц.",
        reply_markup=eggs_out_back_keyboard(),
    )


def format_outflow_overview(ledger_service: LedgerService, user_id: int) -> str:
    today = _today()
    month = ledger_service.outflow_summary(user_id, start_date=today - timedelta(days=29), end_date=today)
    week = ledger_service.outflow_summary(user_id, start_date=today - timedelta(days=6), end_date=today)
    lines = ["💰 Продажи и расход яиц", ""]
    balance = ledger_service.egg_balance(user_id, today=today)
    if balance is None:
        lines.append("Записей пока нет. Нажмите «📤 Продал / отдал», когда яйца уходят из дома.")
        return "\n".join(lines)
    lines.append(
        f"Дома примерно {balance.at_home} яиц: собрано {balance.collected}, ушло {balance.gone} "
        f"(с {balance.since.strftime('%d.%m')})."
    )
    for title, summary in (("За 7 дней", week), ("За 30 дней", month)):
        parts = []
        if summary.sold:
            parts.append(f"продано {summary.sold} на {format_rub(summary.revenue_rub)}")
        if summary.given:
            parts.append(f"отдано {summary.given}")
        if summary.eaten:
            parts.append(f"съели {summary.eaten}")
        if summary.incubated:
            parts.append(f"в инкубатор {summary.incubated}")
        lines.append(f"{title}: " + (", ".join(parts) if parts else "записей нет") + ".")
    recent = ledger_service.recent_outflows(user_id, today=today, days=30)[:8]
    if recent:
        lines.extend(["", "Последние записи:"])
        for row in recent:
            money = f" — {format_rub(row.amount_rub)}" if row.amount_rub else ""
            lines.append(f"- {row.occurred_on.strftime('%d.%m')}: {OUTFLOW_KINDS[row.kind].lower()} {row.eggs_count}{money}")
    return "\n".join(lines)


@router.callback_query(F.data == "ledger:out_list")
async def out_list(callback: CallbackQuery, state: FSMContext, ledger_service: LedgerService) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        format_outflow_overview(ledger_service, callback.from_user.id), reply_markup=eggs_out_back_keyboard()
    )


# --- weekly report -------------------------------------------------------------


@router.callback_query(F.data == "report:week")
async def weekly_report(
    callback: CallbackQuery,
    state: FSMContext,
    ledger_service: LedgerService,
    feeding_service,
    egg_service,
) -> None:
    from app.services.weekly_report import build_weekly_report

    await state.clear()
    await callback.answer()
    text = build_weekly_report(
        user_id=callback.from_user.id,
        today=_today(),
        eggs=egg_service.eggs,
        feeding_service=feeding_service,
        ledger_service=ledger_service,
    )
    await callback.message.answer(
        text + "\n\nТакой отчёт приходит сам по воскресеньям в 20:00.",
        reply_markup=_kb([[("🥚 Яйца", "eggs:menu"), ("🌾 Корма", "feeds:menu")], [HOME]]),
    )


# --- prices and cost ----------------------------------------------------------


@router.callback_query(F.data.startswith("ledger:price:"))
async def price_start(callback: CallbackQuery, state: FSMContext) -> None:
    raw = str(callback.data).rsplit(":", 1)[1]
    if not raw.isdigit():
        await callback.answer("Покупка не найдена.", show_alert=True)
        return
    await state.set_state(PriceFlow.amount)
    await state.update_data(price_tx=int(raw))
    await callback.answer()
    await callback.message.answer(
        "Сколько заплатили за всю покупку, в рублях? Например 1250.\n\nОтмена: /cancel",
        reply_markup=_kb([[CANCEL]]),
    )


@router.message(PriceFlow.amount)
async def price_text(
    message: Message, state: FSMContext, ledger_service: LedgerService, stock_service: StockService
) -> None:
    try:
        price = parse_rub(message.text or "")
    except ValueError as exc:
        await message.answer(f"{exc}\n\nОтмена: /cancel")
        return
    data = await state.get_data()
    await state.clear()
    if not ledger_service.set_purchase_price(message.from_user.id, int(data.get("price_tx") or 0), price):
        await message.answer("Покупка не найдена.", reply_markup=_kb([[("📦 Склад", "stock:menu")], [HOME]]))
        return
    report = ledger_service.cost_report(message.from_user.id, today=_today())
    lines = [f"Цена сохранена: {format_rub(price)}.", ""]
    lines.extend(format_cost_report(report))
    await message.answer(
        "\n".join(lines), reply_markup=_kb([[("💰 Себестоимость", "ledger:cost")], [("📦 Склад", "stock:menu")], [HOME]])
    )


@router.callback_query(F.data == "ledger:cost")
async def cost_view(callback: CallbackQuery, state: FSMContext, ledger_service: LedgerService) -> None:
    await state.clear()
    await callback.answer()
    today = _today()
    report = ledger_service.cost_report(callback.from_user.id, today=today)
    outflow = ledger_service.outflow_summary(
        callback.from_user.id, start_date=today - timedelta(days=report.days - 1), end_date=today
    )
    lines = ["💰 Себестоимость (по «Покормил» и ценам покупок)", ""]
    lines.extend(format_cost_report(report, outflow))
    lines.extend(["", "Цену можно указать сразу после внесения покупки — кнопка «💰 Указать цену»."])
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=_kb([[("➕ Добавить покупку", "stock:purchase")], [("⬅️ К кормам", "feeds:menu")], [HOME]]),
    )
