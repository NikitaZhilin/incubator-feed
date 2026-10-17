"""Web parity: care calendar, moving grown chicks to adults, Excel export."""

from __future__ import annotations

from html import escape

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import Response

from app.services.care import CareService, when_text
from app.services.feeds import FeedService
from app.services.insights import GROWN_CHICK_DAYS, chick_age_text
from app.storage.database import Database
from app.storage.repositories.feeds import FeedRepository


def _today(timezone_name: str):
    from app.web.parity import _local_today

    return _local_today(timezone_name)


def _hidden_user(selected_user) -> str:
    return f'<input type="hidden" name="user_id" value="{escape(str(selected_user or ""))}">'


def register_farm_tool_routes(app: FastAPI, require_web_access) -> None:
    from app.web import main as web

    access = [Depends(require_web_access)]

    async def _context(request: Request, auth: str | None, what: str):
        form = web._parse_urlencoded_form((await request.body()).decode("utf-8", errors="replace"))
        base = web._link("/livestock", auth or "")
        current = app.state.web_config
        if not current.db_path.exists():
            return form, base, None, web._redirect_with_message(base, error=f"База данных не найдена. {what} не выполнено.")
        raw = form.get("user_id", "")
        user_id = web._selected_user_for_write(current, user_id=int(raw) if raw.strip().isdigit() else None)
        if user_id is None:
            return form, base, None, web._redirect_with_message(base, error=f"Пользователь не выбран. {what} не выполнено.")
        return form, base, user_id, None

    def _care() -> CareService:
        return CareService(Database(app.state.web_config.db_path))

    @app.post("/care/{task_id}/{action}", dependencies=access)
    async def care_action(task_id: int, action: str, request: Request, auth: str | None = Query(default=None)):
        form, base, user_id, failed = await _context(request, auth, "Действие")
        if failed:
            return failed
        service = _care()
        today = _today(app.state.web_config.timezone_name)
        try:
            if action == "done":
                task = service.mark_done(user_id, task_id, today=today)
                message = f"{task.title}: сделано, следующий раз {task.next_due.strftime('%d.%m')}." if task else ""
            elif action == "snooze":
                task = service.snooze(user_id, task_id, today=today)
                message = f"{task.title}: напомню {task.next_due.strftime('%d.%m')}." if task else ""
            elif action == "toggle":
                task = service.toggle(user_id, task_id, today=today)
                message = f"{task.title}: {'включено' if task.is_active else 'выключено'}." if task else ""
            elif action == "interval":
                raw = form.get("interval_days", "").strip()
                if not raw.isdigit():
                    raise ValueError("Нужно целое число дней.")
                task = service.set_interval(user_id, task_id, int(raw))
                message = f"{task.title}: каждые {task.interval_days} дн." if task else ""
            else:
                return web._redirect_with_message(base, error="Неизвестное действие.")
        except ValueError as exc:
            return web._redirect_with_message(base, error=str(exc))
        if task is None:
            return web._redirect_with_message(base, error="Задача не найдена.")
        return web._redirect_with_message(base, notice=message)

    @app.post("/bird-groups/{group_id}/grow", dependencies=access)
    async def grow_group(group_id: int, request: Request, auth: str | None = Query(default=None)):
        form, base, user_id, failed = await _context(request, auth, "Перевод во взрослых")
        if failed:
            return failed
        database = Database(app.state.web_config.db_path)
        feeds = FeedService(FeedRepository(database))
        from app.web.parity import feeding_service_for

        feeds.before_ration_change = feeding_service_for(database, app.state.web_config.timezone_name).stock.checkpoint_user
        try:
            if form.get("mode") == "mixed":
                hens = None
            else:
                raw = form.get("hens", "").strip()
                if not raw.isdigit():
                    raise ValueError("Укажите число курочек или выберите «пол пока не различить».")
                hens = int(raw)
            created = feeds.grow_chicks(user_id=user_id, group_id=group_id, hens=hens)
        except ValueError as exc:
            return web._redirect_with_message(base, error=str(exc))
        return web._redirect_with_message(
            base,
            notice="Цыплята переведены во взрослых: " + ", ".join(f"{g.name} — {g.bird_count}" for g in created) + ".",
        )

    @app.post("/incubation/losses", dependencies=access)
    async def save_losses(request: Request, auth: str | None = Query(default=None)):
        from app.services.farm_overview import BatchLosses, save_batch_losses
        from app.storage.repositories.batches import BatchRepository

        form, _, user_id, failed = await _context(request, auth, "Сохранение")
        base = web._link("/incubation", auth or "")
        if failed:
            return failed
        database = Database(app.state.web_config.db_path)
        try:
            values = []
            for field in ("batch_id", "infertile", "dead_embryo", "not_hatched"):
                raw = form.get(field, "0").strip() or "0"
                if not raw.isdigit():
                    raise ValueError("Нужны целые числа от нуля.")
                values.append(int(raw))
            batch = BatchRepository(database).get(values[0], user_id)
            if batch is None:
                raise ValueError("Партия не найдена.")
            save_batch_losses(database, user_id=user_id, batch=batch, losses=BatchLosses(*values[1:]))
        except ValueError as exc:
            return web._redirect_with_message(base, error=str(exc))
        return web._redirect_with_message(base, notice=f"Сохранено для «{batch.title}».")

    @app.get("/export.xlsx", dependencies=access)
    async def export_xlsx(auth: str | None = Query(default=None), user_id: int | None = Query(default=None)):
        from app.services.export import build_farm_workbook, export_filename

        current = app.state.web_config
        selected = web._selected_user_for_write(current, user_id=user_id) if current.db_path.exists() else None
        if selected is None:
            return Response("Пользователь не выбран или база данных недоступна.", status_code=404)
        payload = build_farm_workbook(Database(current.db_path), selected, timezone_name=current.timezone_name)
        name = export_filename(_today(current.timezone_name))
        return Response(
            payload,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )


def care_block(db_path, *, selected_user, auth_token: str, timezone_name: str) -> str:
    from app.web.main import _link

    if selected_user is None or not db_path.exists():
        return ""
    today = _today(timezone_name)
    tasks = CareService(Database(db_path)).list(int(selected_user), today=today)
    rows = []
    for task in tasks:
        def button(action: str, label: str, css: str = "secondary") -> str:
            return (
                f'<form class="inline" method="post" action="{escape(_link(f"/care/{task.id}/{action}", auth_token))}">'
                f'{_hidden_user(selected_user)}<button type="submit" class="{css}">{label}</button></form>'
            )

        status = when_text(task, today) if task.is_active else "выключено"
        flag = "❗ " if task.is_active and task.days_until(today) <= 0 else ""
        rows.append(
            "<tr>"
            f"<td>{flag}{escape(task.title)}<div class=\"small\">{escape(task.hint)}</div></td>"
            f"<td>{escape(status)}</td>"
            f"<td>{escape(task.last_done.strftime('%d.%m.%Y')) if task.last_done else '—'}</td>"
            f"<td><form class=\"inline\" method=\"post\" action=\"{escape(_link(f'/care/{task.id}/interval', auth_token))}\">"
            f"{_hidden_user(selected_user)}<input name=\"interval_days\" type=\"number\" min=\"1\" max=\"365\" "
            f"value=\"{task.interval_days}\" aria-label=\"Каждые, дней\"><button type=\"submit\" class=\"secondary\">дн.</button></form></td>"
            f"<td><div class=\"care-actions\">{button('done', '✅ Сделал', '') if task.is_active else ''}"
            f"{button('snooze', '⏰ +3') if task.is_active else ''}"
            f"{button('toggle', '⏸' if task.is_active else '▶️ Вкл')}</div></td>"
            "</tr>"
        )
    return f"""
  <style>.care-actions {{ display: flex; gap: 6px; flex-wrap: nowrap; }} .care-actions button {{ padding-left: 10px; padding-right: 10px; }}</style>
  <h2>Календарь ухода</h2>
  <p class="small">Бот напоминает в день срока; «Сделал» переносит следующее напоминание на заданный срок. Если делали недавно — тоже нажмите «Сделал».</p>
  <table>
    <thead><tr><th>Что</th><th>Когда</th><th>Последний раз</th><th>Каждые</th><th></th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>"""


def chick_grow_forms(db_path, *, selected_user, auth_token: str, timezone_name: str) -> str:
    from app.web.main import _link

    if selected_user is None or not db_path.exists():
        return ""
    today = _today(timezone_name)
    groups = [
        group
        for group in FeedService(FeedRepository(Database(db_path))).list_bird_groups(int(selected_user))
        if group.is_active
        and group.group_kind == "chicks"
        and (group.hatched_at is None or (today - group.hatched_at).days >= GROWN_CHICK_DAYS - 28)
    ]
    if not groups:
        return ""
    forms = []
    for group in groups:
        age = chick_age_text(group, today) if group.hatched_at else "возраст не указан"
        grown = group.hatched_at is not None and (today - group.hatched_at).days >= GROWN_CHICK_DAYS
        note = " — пора переводить" if grown else ""
        forms.append(
            f"""
    <form class="note" method="post" action="{escape(_link(f'/bird-groups/{group.id}/grow', auth_token))}">
      {_hidden_user(selected_user)}
      <div><strong>{escape(group.name)}</strong>: {group.bird_count} птиц, {escape(age)}{note}</div>
      <label><span class="label">Курочек (остальные — петухи)</span>
        <input name="hens" type="number" min="0" max="{group.bird_count}" step="1" placeholder="0–{group.bird_count}"></label>
      <label><span class="label">Или</span>
        <select name="mode"><option value="split">разделить по числу курочек</option><option value="mixed">пол пока не различить — одна смешанная группа</option></select></label>
      <button type="submit">🐓 Перевести во взрослых</button>
    </form>"""
        )
    return "\n  <h2>Цыплята → взрослые</h2>\n  <p class=\"small\">С 16 недель молодняк ест и живёт как взрослые: переведите группу, и учёт яиц с нормой корма станут точными.</p>" + "".join(forms)


def incubation_results_block(db_path, *, selected_user, auth_token: str = "") -> str:
    """Hatch rate by species and the batch-to-batch comparison, like «Статистика» in the bot."""
    from app.domain import PROFILES
    from app.services.farm_overview import incubation_results_lines, load_batch_losses
    from app.storage.repositories.batches import BatchRepository
    from app.web.main import _link

    if selected_user is None or not db_path.exists():
        return ""
    database = Database(db_path)
    batches = BatchRepository(database).list_all_for_user(int(selected_user))
    losses = load_batch_losses(database, int(selected_user))
    lines = incubation_results_lines(batches, {code: profile.title for code, profile in PROFILES.items()}, losses)
    items = "".join(
        f"<li>{escape(line.removeprefix('- '))}</li>" if line.startswith("- ") else
        (f"<p class=\"small\">{escape(line)}</p>" if line else "")
        for line in lines
    )
    finished = [b for b in batches if not b.is_active and b.hatched_count is not None]
    form = ""
    if finished:
        options = "".join(
            f'<option value="{b.id}">{escape(b.title)} — не вывелось {b.eggs_count - b.hatched_count}'
            f'{" (заполнено)" if b.id in losses else ""}</option>'
            for b in sorted(finished, key=lambda b: b.start_date, reverse=True)
        )
        form = f"""
  <details>
    <summary>Почему не вывелись</summary>
    <form class="note" method="post" action="{escape(_link('/incubation/losses', auth_token))}">
      {_hidden_user(selected_user)}
      <label><span class="label">Партия</span><select name="batch_id">{options}</select></label>
      <label><span class="label">Неоплод</span><input name="infertile" type="number" min="0" step="1" value="0"></label>
      <label><span class="label">Замершие</span><input name="dead_embryo" type="number" min="0" step="1" value="0"></label>
      <label><span class="label">Не вылупились</span><input name="not_hatched" type="number" min="0" step="1" value="0"></label>
      <button type="submit">Сохранить</button>
    </form>
  </details>"""
    return f"""
  <h2>Итоги инкубации</h2>
  <div class="note"><ul class="note">{items}</ul></div>{form}"""
