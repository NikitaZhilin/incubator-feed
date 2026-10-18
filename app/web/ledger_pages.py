"""Web parity for the farm ledger: losses, eggs out, purchase prices and the cost of an egg."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, Query, Request

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
from app.storage.database import Database
from app.storage.repositories.feeds import FeedRepository


def _today(timezone_name: str) -> date:
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("Europe/Moscow")
    return datetime.now(timezone.utc).astimezone(zone).date()


def ledger_service_for(database: Database, timezone_name: str) -> LedgerService:
    from app.web.parity import feeding_service_for

    feeding = feeding_service_for(database, timezone_name)
    feed_service = FeedService(FeedRepository(database))
    feed_service.before_ration_change = feeding.stock.checkpoint_user
    return LedgerService(database, feed_service, feeding_service=feeding, stock_service=feeding.stock)


def _date_or_today(value: str, timezone_name: str) -> date:
    cleaned = (value or "").strip()
    today = _today(timezone_name)
    if not cleaned:
        return today
    try:
        chosen = date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError("Неверная дата.") from exc
    if chosen > today or chosen < today - timedelta(days=366):
        raise ValueError("Дата должна быть не позже сегодняшней и не раньше года назад.")
    return chosen


def register_ledger_routes(app: FastAPI, require_web_access) -> None:
    from app.web import main as web

    access = [Depends(require_web_access)]

    async def _context(request: Request, back: str, auth: str | None, what: str):
        form = web._parse_urlencoded_form((await request.body()).decode("utf-8", errors="replace"))
        redirect_base = web._link(back, auth or "")
        current = app.state.web_config
        if not current.db_path.exists():
            return form, redirect_base, None, None, web._redirect_with_message(
                redirect_base, error=f"База данных не найдена. {what} не выполнено."
            )
        raw = form.get("user_id", "")
        user_id = web._selected_user_for_write(current, user_id=int(raw) if raw.strip().isdigit() else None)
        if user_id is None:
            return form, redirect_base, None, None, web._redirect_with_message(
                redirect_base, error=f"Пользователь не выбран. {what} не выполнено."
            )
        service = ledger_service_for(Database(current.db_path), current.timezone_name)
        return form, redirect_base, user_id, service, None

    @app.post("/ledger/losses", dependencies=access)
    async def add_loss(request: Request, auth: str | None = Query(default=None)):
        form, base, user_id, service, failed = await _context(request, "/livestock", auth, "Запись потери")
        if failed:
            return failed
        try:
            raw_group = form.get("bird_group_id", "")
            if not raw_group.isdigit():
                raise ValueError("Выберите группу поголовья.")
            loss = service.record_loss(
                user_id=user_id,
                bird_group_id=int(raw_group),
                count=parse_count(form.get("count", ""), limit=MAX_BIRDS, what="птиц"),
                reason=form.get("reason", ""),
                occurred_on=_date_or_today(form.get("occurred_on", ""), app.state.web_config.timezone_name),
                note=form.get("note", "").strip(),
            )
        except ValueError as exc:
            return web._redirect_with_message(base, error=str(exc))
        tail = " Группа стала пустой и ушла в архив." if loss.group_archived else ""
        return web._redirect_with_message(
            base, notice=f"Записано: «{loss.group_name}» −{loss.count} ({LOSS_REASONS[loss.reason].lower()}).{tail}"
        )

    @app.post("/ledger/losses/{loss_id}/undo", dependencies=access)
    async def undo_loss(loss_id: int, request: Request, auth: str | None = Query(default=None)):
        _, base, user_id, service, failed = await _context(request, "/livestock", auth, "Отмена потери")
        if failed:
            return failed
        loss = service.undo_loss(user_id, loss_id)
        if loss is None:
            return web._redirect_with_message(base, error="Эта запись уже отменена.")
        return web._redirect_with_message(base, notice=f"Запись отменена: «{loss.group_name}» снова +{loss.count}.")

    @app.post("/ledger/eggs-out", dependencies=access)
    async def add_eggs_out(request: Request, auth: str | None = Query(default=None)):
        form, base, user_id, service, failed = await _context(request, "/eggs", auth, "Запись расхода яиц")
        if failed:
            return failed
        try:
            raw_amount = form.get("amount_rub", "").strip()
            raw_place = form.get("place_id", "").strip()
            outflow = service.record_outflow(
                user_id=user_id,
                kind=form.get("kind", ""),
                eggs_count=parse_count(form.get("eggs_count", ""), limit=MAX_EGGS, what="яиц"),
                amount_rub=(parse_rub(raw_amount) or None) if raw_amount else None,
                occurred_on=_date_or_today(form.get("occurred_on", ""), app.state.web_config.timezone_name),
                note=form.get("note", "").strip(),
                place_id=int(raw_place) if raw_place.isdigit() else None,
            )
        except ValueError as exc:
            return web._redirect_with_message(base, error=str(exc))
        money = f" за {format_rub(outflow.amount_rub)}" if outflow.amount_rub else ""
        return web._redirect_with_message(
            base, notice=f"Записано: {OUTFLOW_KINDS[outflow.kind].lower()} {outflow.eggs_count} яиц{money}."
        )

    # --- egg storage -------------------------------------------------------------

    @app.post("/storage/setup", dependencies=access)
    async def storage_setup(request: Request, auth: str | None = Query(default=None)):
        _, base, user_id, service, failed = await _context(request, "/eggs", auth, "Настройка хранения")
        if failed:
            return failed
        service.storage.setup_default(user_id)
        return web._redirect_with_message(base, notice="Места хранения созданы. Внесите, сколько яиц лежит сейчас.")

    @app.post("/storage/recount", dependencies=access)
    async def storage_recount(request: Request, auth: str | None = Query(default=None)):
        form, base, user_id, service, failed = await _context(request, "/eggs", auth, "Пересчёт")
        if failed:
            return failed
        try:
            raw_place, raw_count = form.get("place_id", ""), form.get("count", "").strip()
            if not raw_place.isdigit() or not raw_count.isdigit():
                raise ValueError("Выберите место и укажите число яиц.")
            diff = service.storage.recount(
                user_id, int(raw_place), int(raw_count),
                today=_today(app.state.web_config.timezone_name), age=form.get("age", "fresh"),
            )
        except ValueError as exc:
            return web._redirect_with_message(base, error=str(exc))
        text = "Совпало с учётом." if diff == 0 else (f"Убрано {-diff} самых старых." if diff < 0 else f"Добавлено {diff}.")
        return web._redirect_with_message(base, notice=f"Пересчитано. {text}")

    @app.post("/storage/move", dependencies=access)
    async def storage_move(request: Request, auth: str | None = Query(default=None)):
        form, base, user_id, service, failed = await _context(request, "/eggs", auth, "Перенос")
        if failed:
            return failed
        try:
            values = [form.get(name, "").strip() for name in ("from_place", "to_place", "count")]
            if not all(value.isdigit() for value in values):
                raise ValueError("Выберите места и укажите число яиц.")
            moved = service.storage.move(user_id, int(values[0]), int(values[1]), int(values[2]))
        except ValueError as exc:
            return web._redirect_with_message(base, error=str(exc))
        return web._redirect_with_message(base, notice=f"Перенесено {moved} яиц.")

    @app.post("/storage/places", dependencies=access)
    async def storage_add_place(request: Request, auth: str | None = Query(default=None)):
        form, base, user_id, service, failed = await _context(request, "/eggs", auth, "Добавление места")
        if failed:
            return failed
        try:
            raw_capacity = form.get("capacity", "").strip()
            if raw_capacity and not raw_capacity.isdigit():
                raise ValueError("Вместимость — целое число или пусто.")
            place = service.storage.add_place(user_id, form.get("name", ""), int(raw_capacity) if raw_capacity and int(raw_capacity) else None)
        except ValueError as exc:
            return web._redirect_with_message(base, error=str(exc))
        return web._redirect_with_message(base, notice=f"Место «{place.name}» добавлено.")

    @app.post("/storage/places/{place_id}/remove", dependencies=access)
    async def storage_remove_place(place_id: int, request: Request, auth: str | None = Query(default=None)):
        _, base, user_id, service, failed = await _context(request, "/eggs", auth, "Удаление места")
        if failed:
            return failed
        try:
            removed = service.storage.remove_place(user_id, place_id)
        except ValueError as exc:
            return web._redirect_with_message(base, error=str(exc))
        return web._redirect_with_message(base, notice="Место удалено." if removed else "Место не найдено.")

    @app.post("/ledger/eggs-out/{outflow_id}/undo", dependencies=access)
    async def undo_eggs_out(outflow_id: int, request: Request, auth: str | None = Query(default=None)):
        _, base, user_id, service, failed = await _context(request, "/eggs", auth, "Отмена записи")
        if failed:
            return failed
        outflow = service.undo_outflow(user_id, outflow_id)
        if outflow is None:
            return web._redirect_with_message(base, error="Эта запись уже отменена.")
        return web._redirect_with_message(
            base, notice=f"Запись отменена: {OUTFLOW_KINDS[outflow.kind].lower()} {outflow.eggs_count} яиц."
        )

    @app.post("/ledger/purchases/{transaction_id}/price", dependencies=access)
    async def set_price(transaction_id: int, request: Request, auth: str | None = Query(default=None)):
        form, base, user_id, service, failed = await _context(request, "/feeds", auth, "Сохранение цены")
        if failed:
            return failed
        try:
            raw = form.get("price_rub", "").strip()
            price = parse_rub(raw) if raw else None
        except ValueError as exc:
            return web._redirect_with_message(base, error=str(exc))
        if not service.set_purchase_price(user_id, transaction_id, price):
            return web._redirect_with_message(base, error="Покупка не найдена.")
        return web._redirect_with_message(
            base, notice=f"Цена сохранена: {format_rub(price)}." if price is not None else "Цена убрана."
        )


# --- page fragments -------------------------------------------------------------


def _hidden_user(selected_user) -> str:
    return f'<input type="hidden" name="user_id" value="{escape(str(selected_user or ""))}">'


def losses_block(db_path, *, selected_user, auth_token: str, timezone_name: str) -> str:
    from app.web.main import _link

    if selected_user is None or not db_path.exists():
        return ""
    service = ledger_service_for(Database(db_path), timezone_name)
    user = int(selected_user)
    today = _today(timezone_name)
    groups = [group for group in service.feed_service.list_bird_groups(user) if group.is_active]
    summary = service.loss_summary(user, today=today)
    recent = service.recent_losses(user, limit=10)
    group_options = "".join(
        f'<option value="{group.id}">{escape(group.name)} ({group.bird_count})</option>' for group in groups
    )
    reason_options = "".join(
        f'<option value="{escape(code)}">{escape(label)}</option>' for code, label in LOSS_REASONS.items()
    )
    rows = "".join(
        "<tr>"
        f"<td>{escape(loss.occurred_on.strftime('%d.%m.%Y'))}</td>"
        f"<td>{escape(loss.group_name)}</td><td>−{loss.count}</td>"
        f"<td>{escape(LOSS_REASONS.get(loss.reason, loss.reason))}</td>"
        f"<td>{escape(loss.note)}</td>"
        f"<td><form class=\"quiet\" method=\"post\" action=\"{escape(_link(f'/ledger/losses/{loss.id}/undo', auth_token))}\">"
        f"{_hidden_user(selected_user)}<button type=\"submit\" class=\"secondary\">↩️ Отменить</button></form></td>"
        "</tr>"
        for loss in recent
    ) or '<tr><td colspan="6">Потерь не записано.</td></tr>'
    warning = (
        f'<p class="small">⚠️ За 30 дней выбыло {summary.total} — больше, чем за прошлые 30 дней '
        f"({summary.previous_total}). Проверьте птиц, корм, воду и курятник.</p>"
        if summary.rising
        else ""
    )
    form = (
        f"""
  <form class="note" method="post" action="{escape(_link('/ledger/losses', auth_token))}">
    {_hidden_user(selected_user)}
    <label><span class="label">Группа</span><select name="bird_group_id" required>{group_options}</select></label>
    <label><span class="label">Сколько выбыло</span><input name="count" type="number" min="1" step="1" value="1" required></label>
    <label><span class="label">Причина</span><select name="reason">{reason_options}</select></label>
    <label><span class="label">Дата</span><input name="occurred_on" type="date" value="{today.isoformat()}" max="{today.isoformat()}"></label>
    <label><span class="label">Комментарий</span><input name="note" type="text" maxlength="120" placeholder="необязательно"></label>
    <button type="submit">➖ Записать потерю</button>
  </form>"""
        if groups
        else "<p>Нет активных групп поголовья.</p>"
    )
    return f"""
  <h2>Падёж и выбраковка</h2>
  <p class="small">Поголовье уменьшится само, норма корма и прогноз яиц пересчитаются. За 30 дней: {summary.total} (за прошлые 30: {summary.previous_total}).</p>
  {warning}
  {form}
  <table>
    <thead><tr><th>Дата</th><th>Группа</th><th>Сколько</th><th>Причина</th><th>Комментарий</th><th></th></tr></thead>
    <tbody>{rows}</tbody>
  </table>"""


def eggs_out_block(db_path, *, selected_user, auth_token: str, timezone_name: str) -> str:
    from app.web.main import _link

    if selected_user is None or not db_path.exists():
        return ""
    service = ledger_service_for(Database(db_path), timezone_name)
    user = int(selected_user)
    today = _today(timezone_name)
    balance = service.egg_balance(user, today=today)
    month = service.outflow_summary(user, start_date=today - timedelta(days=29), end_date=today)
    kind_options = "".join(
        f'<option value="{escape(code)}">{escape(label)}</option>' for code, label in OUTFLOW_KINDS.items()
    )
    rows = "".join(
        "<tr>"
        f"<td>{escape(row.occurred_on.strftime('%d.%m.%Y'))}</td>"
        f"<td>{escape(OUTFLOW_KINDS[row.kind])}</td><td>{row.eggs_count}</td>"
        f"<td>{escape(format_rub(row.amount_rub)) if row.amount_rub else '—'}</td>"
        f"<td><form class=\"quiet\" method=\"post\" action=\"{escape(_link(f'/ledger/eggs-out/{row.id}/undo', auth_token))}\">"
        f"{_hidden_user(selected_user)}<button type=\"submit\" class=\"secondary\">↩️ Отменить</button></form></td>"
        "</tr>"
        for row in service.recent_outflows(user, today=today, days=30)[:10]
    ) or '<tr><td colspan="5">Записей за 30 дней нет.</td></tr>'
    if balance is None:
        stats = "Записей пока нет: отмечайте, когда яйца продаёте, отдаёте или кладёте в инкубатор."
    else:
        home = (
            f"В хранении {balance.at_home} яиц."
            if balance.from_storage
            else f"Дома примерно {balance.at_home} яиц (собрано {balance.collected}, ушло {balance.gone} "
            f"с {balance.since.strftime('%d.%m')})."
        )
        stats = (
            f"{home} За 30 дней продано {month.sold} на {format_rub(month.revenue_rub)}, "
            f"отдано {month.given}, съели {month.eaten}, в инкубатор {month.incubated}."
        )
    stocks = service.storage.contents(user)
    place_select = (
        '<label><span class="label">Откуда</span><select name="place_id"><option value="">самые старые, откуда угодно</option>'
        + "".join(f'<option value="{st.place.id}">{escape(st.place.name)} ({st.total})</option>' for st in stocks)
        + "</select></label>"
        if len(stocks) > 1
        else ""
    )
    return storage_block(service, user, selected_user=selected_user, auth_token=auth_token, today=today) + f"""
  <h2>Продажа и раздача яиц</h2>
  <p class="small">{escape(stats)}</p>
  <form class="note" method="post" action="{escape(_link('/ledger/eggs-out', auth_token))}">
    {_hidden_user(selected_user)}
    <label><span class="label">Куда ушли</span><select name="kind">{kind_options}</select></label>
    <label><span class="label">Яиц</span><input name="eggs_count" type="number" min="1" step="1" required></label>
    <label><span class="label">Сумма, ₽ (только для продажи)</span><input name="amount_rub" type="text" inputmode="decimal" maxlength="20" placeholder="необязательно"></label>
    <label><span class="label">Дата</span><input name="occurred_on" type="date" value="{today.isoformat()}" max="{today.isoformat()}"></label>
    {place_select}
    <button type="submit">📤 Записать</button>
  </form>
  <table>
    <thead><tr><th>Дата</th><th>Куда</th><th>Яиц</th><th>Сумма</th><th></th></tr></thead>
    <tbody>{rows}</tbody>
  </table>"""


def cost_block(db_path, *, selected_user, auth_token: str, timezone_name: str) -> str:
    from app.web.main import _link

    if selected_user is None or not db_path.exists():
        return ""
    service = ledger_service_for(Database(db_path), timezone_name)
    user = int(selected_user)
    today = _today(timezone_name)
    report = service.cost_report(user, today=today)
    outflow = service.outflow_summary(user, start_date=today - timedelta(days=report.days - 1), end_date=today)
    lines = "".join(f"<li>{escape(line.removeprefix('- '))}</li>" for line in format_cost_report(report, outflow))
    purchases = service.ledger.recent_purchases(user, limit=8)
    rows = "".join(
        "<tr>"
        f"<td>{escape(row['created_at'].strftime('%d.%m.%Y'))}</td>"
        f"<td>{escape(row['name'])}</td><td>{row['amount_kg']:g} кг</td>"
        f"<td><form class=\"inline\" method=\"post\" action=\"{escape(_link(f'/ledger/purchases/{row['id']}/price', auth_token))}\">"
        f"{_hidden_user(selected_user)}"
        f"<input name=\"price_rub\" type=\"text\" inputmode=\"decimal\" maxlength=\"20\" "
        f"value=\"{'' if row['price_rub'] is None else format(row['price_rub'], 'g')}\" placeholder=\"₽ за покупку\" aria-label=\"Цена покупки, ₽\">"
        f"<button type=\"submit\" class=\"secondary\">💰 Сохранить</button></form></td>"
        "</tr>"
        for row in purchases
    ) or '<tr><td colspan="4">Покупок пока нет.</td></tr>'
    return f"""
  <h2>Себестоимость</h2>
  <ul class="note">{lines}</ul>
  <details>
    <summary>Цены последних покупок</summary>
    <table>
      <thead><tr><th>Дата</th><th>Позиция</th><th>Количество</th><th>Цена за всю покупку</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </details>"""


def storage_block(service, user: int, *, selected_user, auth_token: str, today) -> str:
    """🧺 Хранение: places, counts and ages, recount, move, add place."""
    from app.services.egg_storage import AGE_CHOICES, DEFAULT_PLACES, USE_FIRST_DAYS, age_text
    from app.web.main import _link

    stocks = service.storage.contents(user)
    if not stocks:
        default = " + ".join(f"{name} ({cap})" if cap else name for name, cap in DEFAULT_PLACES)
        return f"""
  <h2>Хранение яиц</h2>
  <p class="small">Бот будет знать, сколько яиц в каждом месте и сколько им дней. Новый сбор раскладывается сам, продажа берёт самые старые.</p>
  <form class="quiet" method="post" action="{escape(_link('/storage/setup', auth_token))}">
    {_hidden_user(selected_user)}<button type="submit">🧺 Начать: {escape(default)}</button>
  </form>"""
    rows = []
    for stock in stocks:
        oldest = stock.oldest()
        old = sum(lot.count for lot in stock.lots if (today - lot.laid_on).days > USE_FIRST_DAYS)
        remove = (
            f'<form class="quiet" method="post" action="{escape(_link(f"/storage/places/{stock.place.id}/remove", auth_token))}">'
            f'{_hidden_user(selected_user)}<button type="submit" class="secondary">🗑</button></form>'
            if stock.total == 0
            else ""
        )
        rows.append(
            "<tr>"
            f"<td>{escape(stock.place.name)}</td>"
            f"<td>{stock.total}{f' из {stock.place.capacity}' if stock.place.capacity else ''}</td>"
            f"<td>{escape(age_text((today - oldest).days)) if oldest else '—'}</td>"
            f"<td>{old or '—'}</td><td>{remove}</td>"
            "</tr>"
        )
    options = "".join(f'<option value="{s.place.id}">{escape(s.place.name)} ({s.total})</option>' for s in stocks)
    age_options = "".join(f'<option value="{code}">{escape(label)}</option>' for code, (label, _) in AGE_CHOICES.items())
    move = ""
    if len(stocks) > 1:
        to_options = "".join(f'<option value="{s.place.id}">{escape(s.place.name)}</option>' for s in reversed(stocks))
        move = f"""
    <form class="note" method="post" action="{escape(_link('/storage/move', auth_token))}">
      {_hidden_user(selected_user)}
      <label><span class="label">Откуда</span><select name="from_place">{options}</select></label>
      <label><span class="label">Куда</span><select name="to_place">{to_options}</select></label>
      <label><span class="label">Сколько яиц</span><input name="count" type="number" min="1" step="1" value="30"></label>
      <button type="submit">↔️ Перенести</button>
    </form>"""
    return f"""
  <h2>Хранение яиц</h2>
  <p class="small">Всего {sum(s.total for s in stocks)} яиц. Новый сбор заполняет места сверху вниз до вместимости; продажа и «съели» берут самые старые.</p>
  <table>
    <thead><tr><th>Место</th><th>Яиц</th><th>Самые старые</th><th>Старше 3 недель</th><th></th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <details>
    <summary>Пересчитать, перенести, добавить место</summary>
    <form class="note" method="post" action="{escape(_link('/storage/recount', auth_token))}">
      {_hidden_user(selected_user)}
      <label><span class="label">Место</span><select name="place_id">{options}</select></label>
      <label><span class="label">Сколько лежит на самом деле</span><input name="count" type="number" min="0" step="1" required></label>
      <label><span class="label">Возраст, если яиц больше, чем в учёте</span><select name="age">{age_options}</select></label>
      <button type="submit">🔢 Пересчитать</button>
    </form>{move}
    <form class="note" method="post" action="{escape(_link('/storage/places', auth_token))}">
      {_hidden_user(selected_user)}
      <label><span class="label">Новое место</span><input name="name" type="text" maxlength="60" required placeholder="например, Полка в кладовке"></label>
      <label><span class="label">Вместимость (пусто — без ограничения)</span><input name="capacity" type="number" min="1" step="1"></label>
      <button type="submit">➕ Добавить место</button>
    </form>
  </details>"""
