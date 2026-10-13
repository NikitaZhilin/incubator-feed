"""Web pages and forms that mirror bot features missing from the original web version.

Every action calls the same services as the Telegram bot, so the bot and the
site stay equivalent: egg exclusions and multi-day collection, weather refresh,
"already fed" mixes, archiving bird groups and flocks, editing incubation
batches, farm settings, the poultry advisor and the FAQ.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, time, timezone
from html import escape
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.domain import PROFILES
from app.services.eggs import EXCLUSION_REASON_LABELS, EggService
from app.services.feeds import FeedService
from app.services.help_content import HELP_TOPICS, format_help_topic
from app.services.incubation import IncubationService
from app.services.poultry_advisor import PoultryAdvisorService
from app.services.stock import StockService
from app.services.weather import OpenMeteoWeatherClient
from app.storage.database import Database
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.stock import StockRepository
from app.storage.repositories.users import UserRepository
from app.utils.dates import validate_incubation_start_date


HELP_ORDER = (
    "main",
    "incubation",
    "eggs",
    "egg_history",
    "egg_exclusions",
    "egg_weather",
    "feeds",
    "stock",
    "stock_history",
    "mix",
    "livestock",
    "bird_groups",
    "flocks",
    "flock_card",
    "feed_stats",
    "poultry_advisor",
    "settings",
    "settings_sections",
)

# Recently used "already fed" mix confirmations, like the regular mix form.
_PROCESSED_REQUESTS_KEY = "processed_mix_requests"


def register_parity_routes(app: FastAPI, require_web_access) -> None:
    """Attach the extra routes to the app created in app.web.main.create_app."""
    from app.web import main as web

    access = [Depends(require_web_access)]

    async def _form(request: Request) -> dict[str, str]:
        return web._parse_urlencoded_form((await request.body()).decode("utf-8", errors="replace"))

    def _user_for_write(form: dict[str, str]) -> int | None:
        raw = form.get("user_id", "")
        user_id = int(raw) if raw.strip().isdigit() else None
        return web._selected_user_for_write(app.state.web_config, user_id=user_id)

    def _egg_service(database: Database, *, with_weather: bool = False) -> EggService:
        return EggService(
            EggRepository(database),
            FeedRepository(database),
            OpenMeteoWeatherClient() if with_weather else None,
            timezone_name=app.state.web_config.timezone_name,
        )

    def _guard(form: dict[str, str], redirect_base: str, what: str):
        current = app.state.web_config
        if not current.db_path.exists():
            return None, web._redirect_with_message(
                redirect_base, error=f"База данных не найдена. {what} не выполнено."
            )
        user_id = _user_for_write(form)
        if user_id is None:
            return None, web._redirect_with_message(
                redirect_base, error=f"Пользователь не выбран. {what} не выполнено."
            )
        return user_id, None

    # ----- Eggs: exclusions -------------------------------------------------

    @app.post("/eggs/exclusions", dependencies=access)
    async def create_exclusion(request: Request, auth: str | None = Query(default=None)):
        form = await _form(request)
        redirect_base = web._link("/eggs", auth or "")
        user_id, failed = _guard(form, redirect_base, "Исключение")
        if failed:
            return failed
        try:
            hens_count = _parse_int(form.get("hens_count", ""), "Количество кур")
            started_at = _optional_date(form.get("started_at", ""), "Дата начала")
            expected_until = _optional_date(form.get("expected_until", ""), "Ожидаемая дата окончания")
            service = _egg_service(Database(app.state.web_config.db_path))
            service.create_exclusion(
                user_id=user_id,
                hens_count=hens_count,
                reason=form.get("reason", "other"),
                started_at=started_at,
                expected_until=expected_until,
            )
        except ValueError as exc:
            return web._redirect_with_message(redirect_base, error=str(exc))
        return web._redirect_with_message(
            redirect_base,
            notice=f"Отмечено: {hens_count} кур временно не несутся.",
        )

    @app.post("/eggs/exclusions/{exclusion_id}/finish", dependencies=access)
    async def finish_exclusion(
        exclusion_id: int,
        request: Request,
        auth: str | None = Query(default=None),
    ):
        form = await _form(request)
        redirect_base = web._link("/eggs", auth or "")
        user_id, failed = _guard(form, redirect_base, "Возврат несушек")
        if failed:
            return failed
        service = _egg_service(Database(app.state.web_config.db_path))
        if not service.finish_exclusion(user_id=user_id, exclusion_id=exclusion_id):
            return web._redirect_with_message(redirect_base, error="Исключение не найдено.")
        return web._redirect_with_message(redirect_base, notice="Куры снова учитываются в яйценоскости.")

    # ----- Eggs: multi-day collection --------------------------------------

    def _multi_day_distribution(service: EggService, user_id: int, form) -> tuple[int, list, bool]:
        total = _parse_int(form.get("total_eggs", ""), "Количество яиц")
        collection_date = _optional_date(form.get("collection_date", ""), "Дата сбора") or service.current_date()
        if collection_date > service.current_date():
            raise ValueError("Нельзя записать сбор на будущую дату.")
        auto = form.get("mode", "manual") == "auto"
        days = None if auto else _parse_int(form.get("days", ""), "Количество дней")
        distribution = service.preview_multi_day_distribution(
            user_id,
            total,
            days=days,
            today=collection_date,
            use_empty_days=auto,
        )
        return total, distribution, auto

    @app.get("/eggs/multi-day", response_class=HTMLResponse, dependencies=access)
    def multi_day_preview(request: Request, auth: str | None = Query(default=None)):
        form = {key: value for key, value in request.query_params.items()}
        redirect_base = web._link("/eggs", auth or "")
        user_id, failed = _guard(form, redirect_base, "Распределение сбора")
        if failed:
            return failed
        service = _egg_service(Database(app.state.web_config.db_path))
        try:
            total, distribution, auto = _multi_day_distribution(service, user_id, form)
        except ValueError as exc:
            return web._redirect_with_message(redirect_base, error=str(exc))
        rows = "".join(
            f"<tr><td>{escape(day.isoformat())}</td><td>{count}</td></tr>" for day, count in distribution
        )
        hidden = "".join(
            f'<input type="hidden" name="{escape(key)}" value="{escape(value)}">'
            for key, value in form.items()
            if key in {"user_id", "total_eggs", "collection_date", "days", "mode"}
        )
        period = "рассчитан автоматически по пустым дням" if auto else f"{len(distribution)} дн."
        body = f"""
  <p>Сбор {total} шт. будет разложен по дням ({escape(period)}):</p>
  <table>
    <thead><tr><th>Дата</th><th>Яиц</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <form class="note" method="post" action="{escape(web._link('/eggs/multi-day', auth or ''))}">
    {hidden}
    <button type="submit">Записать</button>
  </form>
  <p><a href="{escape(redirect_base)}">Отмена</a></p>"""
        return _page("Сбор за несколько дней", "Проверьте раскладку перед записью.", auth or "", "/eggs", body)

    @app.post("/eggs/multi-day", dependencies=access)
    async def multi_day_record(request: Request, auth: str | None = Query(default=None)):
        form = await _form(request)
        redirect_base = web._link("/eggs", auth or "")
        user_id, failed = _guard(form, redirect_base, "Запись сбора")
        if failed:
            return failed
        service = _egg_service(Database(app.state.web_config.db_path))
        try:
            total, distribution, auto = _multi_day_distribution(service, user_id, form)
            entries = service.record_multi_day_collection(
                user_id, total, distribution, auto_period=auto
            )
        except ValueError as exc:
            return web._redirect_with_message(redirect_base, error=str(exc))
        return web._redirect_with_message(
            redirect_base,
            notice=f"Записано {total} шт. за {len(entries)} дн.",
        )

    @app.post("/eggs/weather/refresh", dependencies=access)
    async def refresh_weather(request: Request, auth: str | None = Query(default=None)):
        form = await _form(request)
        redirect_base = web._link("/eggs", auth or "")
        user_id, failed = _guard(form, redirect_base, "Обновление погоды")
        if failed:
            return failed
        service = _egg_service(Database(app.state.web_config.db_path), with_weather=True)
        try:
            weather = await asyncio.to_thread(service.refresh_weather, user_id, force=True)
        except Exception as exc:  # network errors from weather providers
            return web._redirect_with_message(redirect_base, error=f"Погода не обновлена: {exc}")
        if weather is None:
            return web._redirect_with_message(redirect_base, error="Погода не обновлена.")
        return web._redirect_with_message(redirect_base, notice=f"Погода обновлена: {weather.city}.")

    # ----- Mix: already fed ---------------------------------------------------

    @app.post("/feeds/mixes/already-fed", dependencies=access)
    async def record_already_fed_mix(request: Request, auth: str | None = Query(default=None)):
        form = await _form(request)
        redirect_base = web._link("/mix", auth or "")
        user_id, failed = _guard(form, redirect_base, "Запись замеса")
        if failed:
            return failed
        processed = getattr(app.state, _PROCESSED_REQUESTS_KEY)
        request_id = form.get("request_id", "").strip()[:64]
        if request_id and request_id in processed:
            return web._redirect_with_message(redirect_base, notice="Этот замес уже записан.")
        current = app.state.web_config
        try:
            mix_count = web._parse_positive_float(form.get("mix_count", "1"))
            fed_date = _optional_date(form.get("fed_date", ""), "Дата замеса")
            occurred_at = None
            if fed_date is not None:
                if fed_date > _local_today(current.timezone_name):
                    raise ValueError("Дата замеса не может быть в будущем.")
                occurred_at = datetime.combine(fed_date, time(12, 0), tzinfo=_zone(current.timezone_name))
            database = Database(current.db_path)
            plan = StockService(StockRepository(database), FeedRepository(database)).produce_mix(
                user_id=user_id,
                mix_count=mix_count,
                grain_base=(form.get("grain_base") or "wheat").strip(),
                already_fed=True,
                occurred_at=occurred_at,
            )
        except ValueError as exc:
            return web._redirect_with_message(redirect_base, error=str(exc))
        if request_id:
            processed.append(request_id)
        return web._redirect_with_message(
            redirect_base,
            notice=f"Записан уже скормленный замес: {plan.mix_count:g} повт., {plan.output_kg:.1f} кг.",
        )

    # ----- Livestock: archive -------------------------------------------------

    @app.post("/bird-groups/{group_id}/archive", dependencies=access)
    async def archive_bird_group(group_id: int, request: Request, auth: str | None = Query(default=None)):
        form = await _form(request)
        redirect_base = web._link("/livestock", auth or "")
        user_id, failed = _guard(form, redirect_base, "Архивирование")
        if failed:
            return failed
        if form.get("confirm_archive") != "yes":
            return web._redirect_with_message(redirect_base, error="Подтвердите перенос в архив.")
        service = web._feed_service_for_writes(Database(app.state.web_config.db_path))
        if not service.archive_bird_group(group_id, user_id):
            return web._redirect_with_message(redirect_base, error="Поголовье не найдено.")
        return web._redirect_with_message(redirect_base, notice="Поголовье перенесено в архив.")

    @app.post("/flocks/{flock_id}/archive", dependencies=access)
    async def archive_flock(flock_id: int, request: Request, auth: str | None = Query(default=None)):
        form = await _form(request)
        redirect_base = web._link("/livestock", auth or "")
        user_id, failed = _guard(form, redirect_base, "Архивирование")
        if failed:
            return failed
        if form.get("confirm_archive") != "yes":
            return web._redirect_with_message(redirect_base, error="Подтвердите перенос в архив.")
        service = web._feed_service_for_writes(Database(app.state.web_config.db_path))
        if not service.archive_flock(flock_id, user_id):
            return web._redirect_with_message(redirect_base, error="Стадо не найдено.")
        return web._redirect_with_message(redirect_base, notice="Стадо перенесено в архив.")

    # ----- Incubation: edit batch ----------------------------------------------

    @app.post("/incubation/batches/{batch_id}/edit", dependencies=access)
    async def edit_batch(batch_id: int, request: Request, auth: str | None = Query(default=None)):
        form = await _form(request)
        redirect_base = web._link("/incubation", auth or "")
        user_id, failed = _guard(form, redirect_base, "Изменение партии")
        if failed:
            return failed
        current = app.state.web_config
        try:
            start_date = web._parse_required_date(form.get("start_date", ""), "Дата закладки")
            validate_incubation_start_date(start_date, today=_local_today(current.timezone_name))
            species = form.get("species", "").strip()
            if species not in PROFILES:
                raise ValueError("Выберите птицу из списка.")
            batch = IncubationService(BatchRepository(Database(current.db_path))).update_batch(
                batch_id=batch_id,
                user_id=user_id,
                species=species,
                eggs_count=_parse_int(form.get("eggs_count", ""), "Количество яиц"),
                start_date=start_date,
                title=form.get("title", "").strip() or None,
                note=form.get("note", ""),
            )
        except ValueError as exc:
            return web._redirect_with_message(redirect_base, error=str(exc))
        if batch is None:
            return web._redirect_with_message(redirect_base, error="Партия не найдена.")
        return web._redirect_with_message(redirect_base, notice=f"Партия обновлена: {batch.title}.")

    # ----- Settings: farm profile --------------------------------------------

    @app.post("/settings/profile", dependencies=access)
    async def update_profile(request: Request, auth: str | None = Query(default=None)):
        form = await _form(request)
        redirect_base = web._link("/about", auth or "")
        user_id, failed = _guard(form, redirect_base, "Сохранение настроек")
        if failed:
            return failed
        try:
            timezone_name = form.get("timezone", "").strip() or "Europe/Moscow"
            try:
                ZoneInfo(timezone_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("Не знаю такой часовой пояс. Пример: Europe/Moscow") from exc
            notification_time = _parse_time(form.get("notification_time", ""))
            UserRepository(Database(app.state.web_config.db_path)).update_settings(
                user_id,
                farm_name=form.get("farm_name", "").strip()[:120],
                notification_time=notification_time,
                timezone=timezone_name,
            )
        except ValueError as exc:
            return web._redirect_with_message(redirect_base, error=str(exc))
        return web._redirect_with_message(redirect_base, notice="Настройки хозяйства сохранены.")

    # ----- Poultry advisor ----------------------------------------------------

    @app.get("/advisor", response_class=HTMLResponse, dependencies=access)
    def advisor_page(
        user_id: int | None = Query(default=None),
        auth: str | None = Query(default=None),
    ):
        current = app.state.web_config
        selected = (
            web._selected_user_for_write(current, user_id=user_id) if current.db_path.exists() else None
        )
        if selected is None:
            body = "<p>Пользователь не выбран или база данных недоступна.</p>"
            return _page("Птицевод", "Советы на сегодня.", auth or "", "/advisor", body)
        database = Database(current.db_path)
        feeds = FeedRepository(database)
        incubation = IncubationService(BatchRepository(database), users=UserRepository(database))
        advisor = PoultryAdvisorService(
            incubation_service=incubation,
            feed_service=FeedService(feeds),
            egg_service=_egg_service(database),
            stock_service=StockService(StockRepository(database), feeds),
            timezone_name=current.timezone_name,
        )
        blocks = []
        for title, builder in (
            ("План на сегодня", lambda: advisor.build_today_plan(selected)),
            ("Корма и замес", lambda: advisor.build_feed_advice(selected)),
            ("Когда делать замес", lambda: advisor.build_mix_timing_advice(selected)),
            ("Мало яиц", lambda: advisor.build_egg_drop_advice(selected)),
            ("Инкубация сегодня", lambda: advisor.build_incubation_today_advice(selected)),
            ("Проблема с птицей: опасные признаки", advisor.build_health_red_flags_advice),
            ("Проблема с птицей: наблюдение", advisor.build_health_observation_advice),
        ):
            try:
                text = builder()
            except Exception as exc:  # keep the page usable if one block fails
                text = f"Не удалось построить совет: {exc}"
            blocks.append(
                f'<section class="note"><h2>{escape(title)}</h2>'
                f'<div class="pre">{escape(_plain(text))}</div></section>'
            )
        return _page(
            "Птицевод",
            "Те же советы, что в разделе «Птицевод» бота.",
            auth or "",
            "/advisor",
            "\n".join(blocks),
        )

    # ----- FAQ ----------------------------------------------------------------

    @app.get("/help", response_class=HTMLResponse, dependencies=access)
    def help_page(
        topic: str = Query(default="main"),
        auth: str | None = Query(default=None),
    ):
        key = topic if topic in HELP_TOPICS else "main"
        links = " · ".join(
            (
                f"<strong>{escape(HELP_TOPICS[item].title.removeprefix('FAQ: '))}</strong>"
                if item == key
                else f'<a href="{escape(_with_query(web._link("/help", auth or ""), topic=item))}">'
                f"{escape(HELP_TOPICS[item].title.removeprefix('FAQ: '))}</a>"
            )
            for item in HELP_ORDER
            if item in HELP_TOPICS
        )
        body = (
            f'<p class="small">{links}</p>'
            f'<section class="note"><div class="pre">{escape(_plain(format_help_topic(key)))}</div></section>'
        )
        return _page("FAQ", "Подсказки по разделам, как в боте.", auth or "", "/help", body)


# ----- Fragments used by the existing pages -----------------------------------


def eggs_extra_forms(*, selected_user, auth_token: str, today_value: str) -> str:
    from app.web.main import _link

    user = escape(str(selected_user or ""))
    reason_options = "".join(
        f'<option value="{escape(code)}">{escape(label)}</option>'
        for code, label in EXCLUSION_REASON_LABELS.items()
    )
    return f"""
  <details>
    <summary>Сбор за несколько дней</summary>
    <form class="note" method="get" action="{escape(_link('/eggs/multi-day', auth_token))}">
      <input type="hidden" name="user_id" value="{user}">
      <label><span class="label">Когда собрали</span>
        <input name="collection_date" type="date" required value="{escape(today_value)}"></label>
      <label><span class="label">Всего яиц</span>
        <input name="total_eggs" type="number" min="1" step="1" required></label>
      <label><span class="label">Период</span>
        <select name="mode">
          <option value="manual">Указать число дней</option>
          <option value="auto">Не помню: по среднему сбору и пустым дням</option>
        </select></label>
      <label><span class="label">Дней (2–30)</span>
        <input name="days" type="number" min="2" max="30" step="1" value="2"></label>
      <button type="submit">Показать раскладку</button>
    </form>
  </details>

  <form class="note" method="post" action="{escape(_link('/eggs/weather/refresh', auth_token))}">
    <input type="hidden" name="user_id" value="{user}">
    <button type="submit">Обновить погоду сейчас</button>
  </form>

  <details>
    <summary>Отметить, что куры временно не несутся</summary>
    <form class="note" method="post" action="{escape(_link('/eggs/exclusions', auth_token))}">
      <input type="hidden" name="user_id" value="{user}">
      <label><span class="label">Сколько кур</span>
        <input name="hens_count" type="number" min="1" step="1" required></label>
      <label><span class="label">Причина</span><select name="reason">{reason_options}</select></label>
      <label><span class="label">С какого дня</span>
        <input name="started_at" type="date" value="{escape(today_value)}"></label>
      <label><span class="label">Ожидаемо до</span>
        <input name="expected_until" type="date"></label>
      <button type="submit">Отметить</button>
    </form>
  </details>"""


def exclusion_finish_form(item: dict, *, selected_user, auth_token: str) -> str:
    from app.web.main import _link

    action = _link(f"/eggs/exclusions/{item.get('id')}/finish", auth_token)
    return (
        f'<form class="inline-form" method="post" action="{escape(action)}">'
        f'<input type="hidden" name="user_id" value="{escape(str(selected_user or ""))}">'
        '<button type="submit">Снова несутся</button></form>'
    )


def already_fed_mix_form(*, selected_user, auth_token: str, base_options: str, today_value: str) -> str:
    import secrets

    from app.web.main import _link

    return f"""
  <details>
    <summary>Записать прошлый замес как уже скормленный</summary>
    <p class="small">Для замеса, который уже съели: ингредиенты спишутся, а запас готовой смеси не увеличится.</p>
    <form class="note" method="post" action="{escape(_link('/feeds/mixes/already-fed', auth_token))}">
      <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
      <input type="hidden" name="request_id" value="{escape(secrets.token_urlsafe(16))}">
      <label><span class="label">Повторов замеса</span>
        <input name="mix_count" type="number" min="1" step="1" value="1" required></label>
      <label><span class="label">Основа</span><select name="grain_base">{base_options}</select></label>
      <label><span class="label">Дата замеса (пусто — не помню)</span>
        <input name="fed_date" type="date" max="{escape(today_value)}"></label>
      <button type="submit">Записать как скормленный</button>
    </form>
  </details>"""


def archive_form(path: str, *, selected_user, auth_token: str, label: str) -> str:
    from app.web.main import _link

    return f"""
      <form class="inline-form danger-zone" method="post" action="{escape(_link(path, auth_token))}">
        <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
        <label><input type="checkbox" name="confirm_archive" value="yes" required>
          <span>Подтвердить</span></label>
        <button type="submit">{escape(label)}</button>
      </form>"""


def batch_edit_form(item: dict, *, selected_user, auth_token: str) -> str:
    from app.web.main import _link

    species = str(item.get("species") or "")
    species_options = "".join(
        f'<option value="{escape(code)}"{" selected" if code == species else ""}>{escape(profile.title)}</option>'
        for code, profile in PROFILES.items()
    )
    action = _link(f"/incubation/batches/{item.get('id')}/edit", auth_token)
    return f"""
      <details>
        <summary>Изменить</summary>
        <form class="inline-form" method="post" action="{escape(action)}">
          <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
          <label><span class="label">Птица</span><select name="species">{species_options}</select></label>
          <label><span class="label">Яиц</span>
            <input name="eggs_count" type="number" min="1" step="1" required value="{escape(str(item.get('eggs_count', 1)))}"></label>
          <label><span class="label">Дата закладки</span>
            <input name="start_date" type="date" required value="{escape(str(item.get('start_date') or ''))}"></label>
          <label><span class="label">Название</span>
            <input name="title" type="text" maxlength="120" value="{escape(str(item.get('title') or ''))}"></label>
          <label><span class="label">Заметка</span>
            <input name="note" type="text" maxlength="255" value="{escape(str(item.get('note') or ''))}"></label>
          <button type="submit">Сохранить партию</button>
        </form>
      </details>"""


def profile_form(settings: dict, *, selected_user, auth_token: str) -> str:
    from app.web.main import _link

    return f"""
  <h2>Настройки хозяйства</h2>
  <form class="note" method="post" action="{escape(_link('/settings/profile', auth_token))}">
    <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
    <label><span class="label">Название хозяйства</span>
      <input name="farm_name" type="text" maxlength="120" value="{escape(str(settings.get('farm_name') or ''))}"></label>
    <label><span class="label">Время уведомлений и сводки</span>
      <input name="notification_time" type="time" required value="{escape(str(settings.get('notification_time') or '09:00'))}"></label>
    <label><span class="label">Часовой пояс</span>
      <input name="timezone" type="text" maxlength="64" required value="{escape(str(settings.get('timezone') or 'Europe/Moscow'))}"></label>
    <button type="submit">Сохранить настройки</button>
  </form>"""


# ----- Helpers -------------------------------------------------------------


def _page(title: str, subtitle: str, auth_token: str, active_path: str, body: str) -> str:
    from app.web.main import _page_header, _page_style

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  {_page_style()}
  <style>.pre {{ white-space: pre-wrap; line-height: 1.45; }}</style>
</head>
<body>
<main>
{_page_header(title, subtitle, auth_token, active_path=active_path)}
{body}
</main>
</body>
</html>"""


def _plain(text: str) -> str:
    # Bot texts mark section names as `Название`; show them as «Название».
    return re.sub(r"`([^`]*)`", r"«\1»", str(text or ""))


def _with_query(url: str, **params) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _parse_int(value: str, label: str) -> int:
    cleaned = str(value or "").strip().replace(" ", "")
    if not cleaned.lstrip("-").isdigit():
        raise ValueError(f"{label}: нужно целое число.")
    return int(cleaned)


def _optional_date(value: str, label: str) -> date | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"{label}: неверная дата.") from exc


def _parse_time(value: str) -> str:
    parts = str(value or "").strip().split(":")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError("Время уведомлений: формат ЧЧ:ММ, например 09:00.")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Время уведомлений должно быть от 00:00 до 23:59.")
    return f"{hour:02d}:{minute:02d}"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Europe/Moscow")


def _local_today(name: str) -> date:
    return datetime.now(timezone.utc).astimezone(_zone(name)).date()
