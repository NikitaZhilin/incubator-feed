from __future__ import annotations

from datetime import date, timedelta
from html import escape
from math import isfinite
import secrets
from urllib.parse import parse_qs, urlencode

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services.eggs import EggService
from app.services.feed_recipes import parse_feed_amount
from app.services.feeds import FeedService
from app.services.status_probe import build_status_report
from app.services.stock import STOCK_KIND_LABELS, StockService
from app.storage.database import Database
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.stock import StockRepository
from app.storage.repositories.users import UserRepository
from app.web.config import WebConfig, load_web_config
from app.web.summary import (
    build_web_eggs,
    build_web_feeds,
    build_web_incubation,
    build_web_livestock,
    build_web_mix,
    build_web_summary,
)


def create_app(config: WebConfig | None = None) -> FastAPI:
    web_config = config or load_web_config()
    app = FastAPI(title="tg_bot_inkubator web", version=web_config.release_version)
    app.state.web_config = web_config

    def require_web_access(
        authorization: str | None = Header(default=None),
        x_web_token: str | None = Header(default=None),
        auth: str | None = Query(default=None),
    ) -> None:
        current = app.state.web_config
        provided = _extract_access_token(authorization, x_web_token, auth)
        configured_tokens = [token for token in (current.admin_token, current.link_token) if token]
        if not configured_tokens:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="WEB_ADMIN_TOKEN or WEB_LINK_TOKEN is not configured.",
            )
        if not any(secrets.compare_digest(provided, token) for token in configured_tokens):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/status", dependencies=[Depends(require_web_access)])
    def status_report() -> dict:
        return build_status_report(app.state.web_config.db_path)

    @app.get("/version", dependencies=[Depends(require_web_access)])
    def version() -> dict:
        current = app.state.web_config
        return {
            "version": current.release_version,
            "channel": current.release_channel,
            "environment": current.environment,
            "release_notes": _release_note_items(current.release_notes),
            "release_importance": current.release_importance,
            "release_notice_enabled": current.release_notice_enabled,
            "admin_startup_notice_mode": current.admin_startup_notice_mode,
            "deployed_at": current.release_deployed_at or None,
            "commit": current.release_commit or None,
            "github_url": current.github_url,
            "changelog_url": current.changelog_url,
        }


    @app.get("/summary", dependencies=[Depends(require_web_access)])
    def summary(user_id: int | None = Query(default=None)) -> dict:
        current = app.state.web_config
        return build_web_summary(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )

    @app.get("/feeds/data", dependencies=[Depends(require_web_access)])
    def feeds_data(user_id: int | None = Query(default=None)) -> dict:
        current = app.state.web_config
        return build_web_feeds(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )

    @app.get("/feeds", response_class=HTMLResponse, dependencies=[Depends(require_web_access)])
    def feeds_page(
        request: Request,
        user_id: int | None = Query(default=None),
        auth: str | None = Query(default=None),
        notice: str | None = Query(default=None),
        error: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        sort: str | None = Query(default=None),
    ) -> str:
        current = request.app.state.web_config
        payload = build_web_feeds(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )
        payload["notice"] = notice or ""
        payload["error"] = error or ""
        payload["filter_kind"] = kind or ""
        payload["sort"] = sort or "name"
        return _render_feeds_page(current, payload, auth_token=auth or "")

    @app.post("/stock/purchases", dependencies=[Depends(require_web_access)])
    async def create_stock_purchase(
        request: Request,
        auth: str | None = Query(default=None),
    ) -> RedirectResponse:
        current = app.state.web_config
        redirect_base = _link("/feeds", auth or "")
        form = _parse_urlencoded_form((await request.body()).decode("utf-8", errors="replace"))
        raw_user_id = form.get("user_id", "")
        user_id = int(raw_user_id) if raw_user_id.strip().isdigit() else None
        name = form.get("name", "").strip()
        kind = form.get("kind", "ingredient").strip()
        amount = form.get("amount", "").strip()
        note = form.get("note", "").strip()
        if not current.db_path.exists():
            return _redirect_with_message(
                redirect_base,
                error="База данных не найдена. Покупка не добавлена.",
            )
        selected_user_id = _selected_user_for_write(current, user_id=user_id)
        if selected_user_id is None:
            return _redirect_with_message(
                redirect_base,
                error="Пользователь не выбран. Покупка не добавлена.",
            )
        try:
            if not name:
                raise ValueError("Введите название позиции.")
            if kind not in STOCK_KIND_LABELS:
                raise ValueError("Выберите корректный тип позиции.")
            amount_kg = parse_feed_amount(amount)
            database = Database(current.db_path)
            service = StockService(StockRepository(database), FeedRepository(database))
            estimate = service.add_purchase(
                user_id=selected_user_id,
                name=name,
                kind=kind,
                amount_kg=amount_kg,
                note=note,
            )
        except ValueError as exc:
            return _redirect_with_message(redirect_base, error=str(exc))
        return _redirect_with_message(
            redirect_base,
            notice=f"Покупка добавлена: {estimate.item.name}, {_kg(amount_kg)}.",
        )

    @app.get("/mix/data", dependencies=[Depends(require_web_access)])
    def mix_data(user_id: int | None = Query(default=None)) -> dict:
        current = app.state.web_config
        return build_web_mix(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )

    @app.get("/mix", response_class=HTMLResponse, dependencies=[Depends(require_web_access)])
    def mix_page(
        request: Request,
        user_id: int | None = Query(default=None),
        auth: str | None = Query(default=None),
        notice: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ) -> str:
        current = request.app.state.web_config
        payload = build_web_mix(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )
        payload["notice"] = notice or ""
        payload["error"] = error or ""
        return _render_mix_page(current, payload, auth_token=auth or "")

    @app.get("/mix/confirm", response_class=HTMLResponse, dependencies=[Depends(require_web_access)])
    def mix_confirm_page(
        request: Request,
        user_id: int | None = Query(default=None),
        mix_count: str = Query(default="1"),
        grain_base: str = Query(default=""),
        auth: str | None = Query(default=None),
    ):
        current = request.app.state.web_config
        redirect_base = _link("/mix", auth or "")
        if not current.db_path.exists():
            return _redirect_with_message(
                redirect_base,
                error="База данных не найдена. Замес не рассчитан.",
            )
        selected_user_id = _selected_user_for_write(current, user_id=user_id)
        if selected_user_id is None:
            return _redirect_with_message(
                redirect_base,
                error="Пользователь не выбран. Замес не рассчитан.",
            )
        try:
            count = _parse_positive_float(mix_count)
            service = _stock_service(current)
            base = grain_base.strip() or None
            plan = service.plan_mix(
                user_id=selected_user_id,
                mix_count=count,
                grain_base=base or "wheat",
            )
        except ValueError as exc:
            return _redirect_with_message(redirect_base, error=str(exc))
        return _render_mix_confirm_page(
            current,
            selected_user_id=selected_user_id,
            plan=plan,
            auth_token=auth or "",
        )

    @app.post("/feeds/mixes", dependencies=[Depends(require_web_access)])
    async def create_feed_mix(
        request: Request,
        auth: str | None = Query(default=None),
    ) -> RedirectResponse:
        current = app.state.web_config
        redirect_base = _link("/mix", auth or "")
        form = _parse_urlencoded_form((await request.body()).decode("utf-8", errors="replace"))
        raw_user_id = form.get("user_id", "")
        user_id = int(raw_user_id) if raw_user_id.strip().isdigit() else None
        mix_count = form.get("mix_count", "1")
        grain_base = form.get("grain_base", "wheat")
        if not current.db_path.exists():
            return _redirect_with_message(
                redirect_base,
                error="База данных не найдена. Замес не создан.",
            )
        selected_user_id = _selected_user_for_write(current, user_id=user_id)
        if selected_user_id is None:
            return _redirect_with_message(
                redirect_base,
                error="Пользователь не выбран. Замес не создан.",
            )
        try:
            count = _parse_positive_float(mix_count)
            plan = _stock_service(current).produce_mix(
                user_id=selected_user_id,
                mix_count=count,
                grain_base=grain_base.strip() or "wheat",
            )
        except ValueError as exc:
            return _redirect_with_message(redirect_base, error=str(exc))
        return _redirect_with_message(
            redirect_base,
            notice=f"Замес создан: {plan.mix_count:g} повт., получено {_kg(plan.output_kg)}.",
        )

    @app.get("/eggs/data", dependencies=[Depends(require_web_access)])
    def eggs_data(user_id: int | None = Query(default=None)) -> dict:
        current = app.state.web_config
        return build_web_eggs(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )

    @app.get("/eggs", response_class=HTMLResponse, dependencies=[Depends(require_web_access)])
    def eggs_page(
        request: Request,
        user_id: int | None = Query(default=None),
        auth: str | None = Query(default=None),
        notice: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ) -> str:
        current = request.app.state.web_config
        payload = build_web_eggs(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )
        payload["notice"] = notice or ""
        payload["error"] = error or ""
        return _render_eggs_page(current, payload, auth_token=auth or "")

    @app.post("/eggs/entries", dependencies=[Depends(require_web_access)])
    async def create_egg_entry(
        request: Request,
        auth: str | None = Query(default=None),
    ) -> RedirectResponse:
        current = app.state.web_config
        redirect_base = _link("/eggs", auth or "")
        form = _parse_urlencoded_form((await request.body()).decode("utf-8", errors="replace"))
        raw_user_id = form.get("user_id", "")
        user_id = int(raw_user_id) if raw_user_id.strip().isdigit() else None
        entry_day = form.get("entry_day", "today")
        eggs_count = form.get("eggs_count", "")
        note = form.get("note", "")
        if not current.db_path.exists():
            return _redirect_with_message(
                redirect_base,
                error="База данных не найдена. Запись не добавлена.",
            )
        selected_user_id = _selected_user_for_write(current, user_id=user_id)
        if selected_user_id is None:
            return _redirect_with_message(
                redirect_base,
                error="Пользователь не выбран. Запись не добавлена.",
            )
        try:
            count = int(str(eggs_count).strip())
            database = Database(current.db_path)
            service = EggService(
                EggRepository(database),
                FeedRepository(database),
                timezone_name=current.timezone_name,
            )
            entry_date = service.current_date()
            if entry_day == "yesterday":
                entry_date -= timedelta(days=1)
            elif entry_day != "today":
                raise ValueError("Выберите сегодня или вчера.")
            entry = service.record_today(
                selected_user_id,
                count,
                today=entry_date,
                note=note.strip(),
            )
        except ValueError as exc:
            return _redirect_with_message(redirect_base, error=str(exc))
        return _redirect_with_message(
            redirect_base,
            notice=f"Запись добавлена: {entry.entry_date.isoformat()}, {entry.eggs_count} шт.",
        )

    @app.get("/incubation/data", dependencies=[Depends(require_web_access)])
    def incubation_data(user_id: int | None = Query(default=None)) -> dict:
        current = app.state.web_config
        return build_web_incubation(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )

    @app.get("/incubation", response_class=HTMLResponse, dependencies=[Depends(require_web_access)])
    def incubation_page(
        request: Request,
        user_id: int | None = Query(default=None),
        auth: str | None = Query(default=None),
    ) -> str:
        current = request.app.state.web_config
        payload = build_web_incubation(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )
        return _render_incubation_page(current, payload, auth_token=auth or "")

    @app.get("/livestock/data", dependencies=[Depends(require_web_access)])
    def livestock_data(user_id: int | None = Query(default=None)) -> dict:
        current = app.state.web_config
        return build_web_livestock(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )

    @app.get("/livestock", response_class=HTMLResponse, dependencies=[Depends(require_web_access)])
    def livestock_page(
        request: Request,
        user_id: int | None = Query(default=None),
        auth: str | None = Query(default=None),
        notice: str | None = Query(default=None),
        error: str | None = Query(default=None),
        role: str | None = Query(default=None),
        sort: str | None = Query(default=None),
    ) -> str:
        current = request.app.state.web_config
        payload = build_web_livestock(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )
        payload["notice"] = notice or ""
        payload["error"] = error or ""
        payload["filter_role"] = role or ""
        payload["sort"] = sort or "name"
        return _render_livestock_page(current, payload, auth_token=auth or "")

    @app.post("/bird-groups", dependencies=[Depends(require_web_access)])
    async def create_bird_group(
        request: Request,
        auth: str | None = Query(default=None),
    ) -> RedirectResponse:
        current = app.state.web_config
        redirect_base = _link("/livestock", auth or "")
        form = _parse_urlencoded_form((await request.body()).decode("utf-8", errors="replace"))
        raw_user_id = form.get("user_id", "")
        user_id = int(raw_user_id) if raw_user_id.strip().isdigit() else None
        if not current.db_path.exists():
            return _redirect_with_message(
                redirect_base,
                error="База данных не найдена. Поголовье не добавлено.",
            )
        selected_user_id = _selected_user_for_write(current, user_id=user_id)
        if selected_user_id is None:
            return _redirect_with_message(
                redirect_base,
                error="Пользователь не выбран. Поголовье не добавлено.",
            )
        try:
            name = form.get("name", "").strip()
            bird_count = _parse_positive_int(
                form.get("bird_count", ""),
                empty_message="Введите количество птиц.",
                positive_message="Количество птиц должно быть больше нуля.",
            )
            species = form.get("species", "chicken").strip() or None
            group_kind = form.get("group_kind", "adult").strip() or "adult"
            role = form.get("role", "mixed").strip() or "mixed"
            if species not in {None, "chicken", "goose", "quail", "duck", "muscovy_duck"}:
                raise ValueError("Выберите корректный вид птицы.")
            if group_kind == "adult" and role == "chicks":
                raise ValueError("Для взрослого поголовья выберите роль взрослых птиц.")
            hatched_at = _parse_optional_date(form.get("hatched_at", ""), "Дата вывода")
            joined_at = _parse_optional_date(form.get("joined_at", ""), "Дата подсадки")
            reserve_percent = _parse_optional_float(form.get("reserve_percent", ""), default=0.0)
            database = Database(current.db_path)
            group = FeedService(FeedRepository(database)).create_bird_group(
                user_id=selected_user_id,
                name=name,
                bird_count=bird_count,
                species=species,
                group_kind=group_kind,
                role=role,
                hatched_at=hatched_at,
                joined_at=joined_at,
                reserve_percent=reserve_percent,
            )
        except ValueError as exc:
            return _redirect_with_message(redirect_base, error=str(exc))
        return _redirect_with_message(
            redirect_base,
            notice=f"Поголовье добавлено: {group.name}, {group.bird_count} птиц.",
        )

    @app.patch("/bird-groups/{group_id}", dependencies=[Depends(require_web_access)])
    @app.post("/bird-groups/{group_id}", dependencies=[Depends(require_web_access)])
    async def update_bird_group(
        group_id: int,
        request: Request,
        auth: str | None = Query(default=None),
    ) -> RedirectResponse:
        current = app.state.web_config
        redirect_base = _link("/livestock", auth or "")
        form = _parse_urlencoded_form((await request.body()).decode("utf-8", errors="replace"))
        raw_user_id = form.get("user_id", "")
        user_id = int(raw_user_id) if raw_user_id.strip().isdigit() else None
        if not current.db_path.exists():
            return _redirect_with_message(
                redirect_base,
                error="База данных не найдена. Поголовье не обновлено.",
            )
        selected_user_id = _selected_user_for_write(current, user_id=user_id)
        if selected_user_id is None:
            return _redirect_with_message(
                redirect_base,
                error="Пользователь не выбран. Поголовье не обновлено.",
            )
        try:
            bird_count = _parse_positive_int(
                form.get("bird_count", ""),
                empty_message="Введите количество птиц.",
                positive_message="Количество птиц должно быть больше нуля.",
            )
            role = form.get("role", "").strip() or None
            hatched_at = _parse_optional_date(form.get("hatched_at", ""), "Дата вывода")
            joined_at = _parse_optional_date(form.get("joined_at", ""), "Дата подсадки")
            reserve_percent = _parse_optional_float(form.get("reserve_percent", ""), default=0.0)
            database = Database(current.db_path)
            group = FeedService(FeedRepository(database)).update_bird_group(
                group_id=group_id,
                user_id=selected_user_id,
                name=form.get("name", "").strip(),
                bird_count=bird_count,
                role=role,
                hatched_at=hatched_at,
                joined_at=joined_at,
                reserve_percent=reserve_percent,
            )
            if group is None:
                raise ValueError("Поголовье не найдено.")
        except ValueError as exc:
            return _redirect_with_message(redirect_base, error=str(exc))
        return _redirect_with_message(
            redirect_base,
            notice=f"Поголовье обновлено: {group.name}.",
        )

    @app.post("/flocks", dependencies=[Depends(require_web_access)])
    async def create_flock(
        request: Request,
        auth: str | None = Query(default=None),
    ) -> RedirectResponse:
        current = app.state.web_config
        redirect_base = _link("/livestock", auth or "")
        form_values = _parse_urlencoded_lists(
            (await request.body()).decode("utf-8", errors="replace")
        )
        form = {key: values[-1] if values else "" for key, values in form_values.items()}
        raw_user_id = form.get("user_id", "")
        user_id = int(raw_user_id) if raw_user_id.strip().isdigit() else None
        if not current.db_path.exists():
            return _redirect_with_message(
                redirect_base,
                error="База данных не найдена. Стадо не создано.",
            )
        selected_user_id = _selected_user_for_write(current, user_id=user_id)
        if selected_user_id is None:
            return _redirect_with_message(
                redirect_base,
                error="Пользователь не выбран. Стадо не создано.",
            )
        try:
            name = form.get("name", "").strip()
            member_group_ids = _parse_positive_int_list(
                form_values.get("member_group_ids", []),
                empty_message="Выберите хотя бы одну группу поголовья для стада.",
            )
            database = Database(current.db_path)
            flock = FeedService(FeedRepository(database)).create_flock(
                user_id=selected_user_id,
                name=name,
                member_group_ids=member_group_ids,
            )
        except ValueError as exc:
            return _redirect_with_message(redirect_base, error=str(exc))
        return _redirect_with_message(
            redirect_base,
            notice=f"Стадо создано: {flock.name}.",
        )

    @app.patch("/flocks/{flock_id}", dependencies=[Depends(require_web_access)])
    @app.post("/flocks/{flock_id}", dependencies=[Depends(require_web_access)])
    async def update_flock(
        flock_id: int,
        request: Request,
        auth: str | None = Query(default=None),
    ) -> RedirectResponse:
        current = app.state.web_config
        redirect_base = _link("/livestock", auth or "")
        form_values = _parse_urlencoded_lists(
            (await request.body()).decode("utf-8", errors="replace")
        )
        form = {key: values[-1] if values else "" for key, values in form_values.items()}
        raw_user_id = form.get("user_id", "")
        user_id = int(raw_user_id) if raw_user_id.strip().isdigit() else None
        if not current.db_path.exists():
            return _redirect_with_message(
                redirect_base,
                error="База данных не найдена. Стадо не обновлено.",
            )
        selected_user_id = _selected_user_for_write(current, user_id=user_id)
        if selected_user_id is None:
            return _redirect_with_message(
                redirect_base,
                error="Пользователь не выбран. Стадо не обновлено.",
            )
        try:
            member_group_ids = _parse_positive_int_list(
                form_values.get("member_group_ids", []),
                empty_message="Выберите хотя бы одну группу поголовья для стада.",
            )
            database = Database(current.db_path)
            flock = FeedService(FeedRepository(database)).update_flock(
                flock_id=flock_id,
                user_id=selected_user_id,
                name=form.get("name", "").strip(),
                member_group_ids=member_group_ids,
            )
            if flock is None:
                raise ValueError("Стадо не найдено.")
        except ValueError as exc:
            return _redirect_with_message(redirect_base, error=str(exc))
        return _redirect_with_message(
            redirect_base,
            notice=f"Стадо обновлено: {flock.name}.",
        )

    @app.post("/flock-feed-assignments", dependencies=[Depends(require_web_access)])
    async def assign_flock_feed(
        request: Request,
        auth: str | None = Query(default=None),
    ) -> RedirectResponse:
        current = app.state.web_config
        redirect_base = _link("/livestock", auth or "")
        form = _parse_urlencoded_form((await request.body()).decode("utf-8", errors="replace"))
        raw_user_id = form.get("user_id", "")
        user_id = int(raw_user_id) if raw_user_id.strip().isdigit() else None
        if not current.db_path.exists():
            return _redirect_with_message(
                redirect_base,
                error="База данных не найдена. Смесь не назначена.",
            )
        selected_user_id = _selected_user_for_write(current, user_id=user_id)
        if selected_user_id is None:
            return _redirect_with_message(
                redirect_base,
                error="Пользователь не выбран. Смесь не назначена.",
            )
        try:
            flock_id = _parse_positive_int(
                form.get("flock_id", ""),
                empty_message="Выберите стадо.",
                positive_message="Выберите стадо.",
            )
            stock_item_id = _parse_positive_int(
                form.get("stock_item_id", ""),
                empty_message="Выберите готовую смесь.",
                positive_message="Выберите готовую смесь.",
            )
            assignment = _stock_service(current).assign_flock_feed(
                user_id=selected_user_id,
                flock_id=flock_id,
                stock_item_id=stock_item_id,
            )
        except ValueError as exc:
            return _redirect_with_message(redirect_base, error=str(exc))
        return _redirect_with_message(
            redirect_base,
            notice=f"Смесь назначена стаду: {assignment.stock_item_name}.",
        )

    @app.post("/settings/weather", dependencies=[Depends(require_web_access)])
    async def update_weather_settings(
        request: Request,
        auth: str | None = Query(default=None),
    ) -> RedirectResponse:
        current = app.state.web_config
        redirect_base = _link("/eggs", auth or "")
        form = _parse_urlencoded_form((await request.body()).decode("utf-8", errors="replace"))
        raw_user_id = form.get("user_id", "")
        user_id = int(raw_user_id) if raw_user_id.strip().isdigit() else None
        if not current.db_path.exists():
            return _redirect_with_message(
                redirect_base,
                error="База данных не найдена. Город не обновлен.",
            )
        selected_user_id = _selected_user_for_write(current, user_id=user_id)
        if selected_user_id is None:
            return _redirect_with_message(
                redirect_base,
                error="Пользователь не выбран. Город не обновлен.",
            )
        try:
            database = Database(current.db_path)
            settings = EggService(EggRepository(database), FeedRepository(database)).update_weather_city(
                user_id=selected_user_id,
                city=form.get("city", ""),
            )
        except ValueError as exc:
            return _redirect_with_message(redirect_base, error=str(exc))
        return _redirect_with_message(
            redirect_base,
            notice=f"Город погоды обновлен: {settings.city}.",
        )

    @app.patch("/settings/sections", dependencies=[Depends(require_web_access)])
    @app.post("/settings/sections", dependencies=[Depends(require_web_access)])
    async def update_sections_settings(
        request: Request,
        auth: str | None = Query(default=None),
    ) -> RedirectResponse:
        current = app.state.web_config
        redirect_base = _link("/about", auth or "")
        form_values = _parse_urlencoded_lists(
            (await request.body()).decode("utf-8", errors="replace")
        )
        form = {key: values[-1] if values else "" for key, values in form_values.items()}
        raw_user_id = form.get("user_id", "")
        user_id = int(raw_user_id) if raw_user_id.strip().isdigit() else None
        if not current.db_path.exists():
            return _redirect_with_message(
                redirect_base,
                error="База данных не найдена. Разделы не обновлены.",
            )
        selected_user_id = _selected_user_for_write(current, user_id=user_id)
        if selected_user_id is None:
            return _redirect_with_message(
                redirect_base,
                error="Пользователь не выбран. Разделы не обновлены.",
            )
        section_keys = set(form_values.get("sections", []))
        database = Database(current.db_path)
        UserRepository(database).update_settings(
            selected_user_id,
            notify_incubation="incubation" in section_keys,
            notify_feed="feeds" in section_keys,
            notify_eggs="eggs" in section_keys,
            notify_post_hatch_care="post_hatch_care" in section_keys,
            notify_service="service" in section_keys,
        )
        return _redirect_with_message(
            redirect_base,
            notice="Разделы Telegram-бота обновлены.",
        )

    @app.get("/about/data", dependencies=[Depends(require_web_access)])
    def about_data(user_id: int | None = Query(default=None)) -> dict:
        current = app.state.web_config
        return _build_about_payload(current, user_id=user_id)

    @app.get("/about", response_class=HTMLResponse, dependencies=[Depends(require_web_access)])
    def about_page(
        request: Request,
        user_id: int | None = Query(default=None),
        auth: str | None = Query(default=None),
        notice: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ) -> str:
        current = request.app.state.web_config
        payload = _build_about_payload(current, user_id=user_id)
        payload["notice"] = notice or ""
        payload["error"] = error or ""
        return _render_about_page(current, payload, auth_token=auth or "")

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        user_id: int | None = Query(default=None),
        auth: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
        x_web_token: str | None = Header(default=None),
    ):
        current = request.app.state.web_config
        if not auth and not authorization and not x_web_token and current.link_token:
            params: list[tuple[str, str]] = [("auth", current.link_token)]
            if user_id is not None:
                params.insert(0, ("user_id", str(user_id)))
            return RedirectResponse(url=f"/?{urlencode(params)}")

        require_web_access(authorization=authorization, x_web_token=x_web_token, auth=auth)
        report = build_status_report(current.db_path)
        summary_payload = build_web_summary(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )
        return _render_index(current, report, summary_payload, auth_token=auth or "")

    return app


def _build_about_payload(config: WebConfig, *, user_id: int | None = None) -> dict:
    report = build_status_report(config.db_path)
    summary = build_web_summary(
        config.db_path,
        user_id=user_id,
        timezone_name=config.timezone_name,
    )
    return {
        "generated_at": summary.get("generated_at"),
        "selected_user_id": summary.get("selected_user_id"),
        "db": summary.get("db"),
        "settings": summary.get("settings"),
        "runtime": {
            "status": report.get("status", "unknown"),
            "heartbeats": report.get("heartbeats", []),
            "critical_errors": report.get("errors", {}).get("critical_total", 0),
        },
        "release": {
            "version": config.release_version,
            "channel": config.release_channel,
            "environment": config.environment,
            "release_notes": _release_note_items(config.release_notes),
            "release_importance": config.release_importance,
            "release_notice_enabled": config.release_notice_enabled,
            "user_release_messages": (
                config.release_importance if config.release_notice_enabled else "off"
            ),
            "admin_startup_notice_mode": config.admin_startup_notice_mode,
            "deployed_at": config.release_deployed_at or None,
            "commit": config.release_commit or None,
            "github_url": config.github_url,
            "changelog_url": config.changelog_url,
        },
    }


def _selected_user_for_write(config: WebConfig, *, user_id: int | None = None) -> int | None:
    summary = build_web_summary(
        config.db_path,
        user_id=user_id,
        timezone_name=config.timezone_name,
    )
    selected = summary.get("selected_user_id")
    return int(selected) if selected is not None else None


def _stock_service(config: WebConfig) -> StockService:
    database = Database(config.db_path)
    feeds = FeedRepository(database)
    return StockService(StockRepository(database), feeds)


def _redirect_with_message(path: str, *, notice: str = "", error: str = "") -> RedirectResponse:
    separator = "&" if "?" in path else "?"
    params = {}
    if notice:
        params["notice"] = notice
    if error:
        params["error"] = error
    target = path if not params else f"{path}{separator}{urlencode(params)}"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def _parse_urlencoded_form(body: str) -> dict[str, str]:
    parsed = _parse_urlencoded_lists(body)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _parse_urlencoded_lists(body: str) -> dict[str, list[str]]:
    return parse_qs(body, keep_blank_values=True)


def _parse_positive_float(value: str) -> float:
    try:
        number = float(str(value).strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError("Введите количество замесов числом больше нуля.") from exc
    if number <= 0:
        raise ValueError("Количество замесов должно быть больше нуля.")
    return number


def _parse_positive_int(
    value: str,
    *,
    empty_message: str,
    positive_message: str,
) -> int:
    text = str(value).strip()
    if not text:
        raise ValueError(empty_message)
    try:
        number = int(text)
    except ValueError as exc:
        raise ValueError(empty_message) from exc
    if number <= 0:
        raise ValueError(positive_message)
    return number


def _parse_positive_int_list(values: list[str], *, empty_message: str) -> list[int]:
    result: list[int] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        try:
            number = int(text)
        except ValueError as exc:
            raise ValueError(empty_message) from exc
        if number <= 0:
            raise ValueError(empty_message)
        result.append(number)
    if not result:
        raise ValueError(empty_message)
    return result


def _parse_optional_float(value: str, *, default: float = 0.0) -> float:
    text = str(value).strip().replace(",", ".")
    if not text:
        return default
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError("Введите запас числом.") from exc
    if not isfinite(number):
        raise ValueError("Введите запас обычным числом.")
    return number


def _parse_optional_date(value: str, label: str) -> date | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label}: укажите дату в формате ГГГГ-ММ-ДД.") from exc


def _extract_token(authorization: str | None, x_web_token: str | None) -> str:
    if x_web_token:
        return x_web_token.strip()
    if not authorization:
        return ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def _extract_access_token(
    authorization: str | None,
    x_web_token: str | None,
    auth: str | None,
) -> str:
    if auth:
        return auth.strip()
    return _extract_token(authorization, x_web_token)


def _page_style() -> str:
    return """<style>
    :root {
      color-scheme: light dark;
      font-family: Arial, sans-serif;
    }
    body {
      margin: 0;
      background: #f4f1ea;
      color: #222;
    }
    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 28px 18px 48px;
    }
    header {
      margin-bottom: 24px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 28px;
    }
    h2 {
      margin: 28px 0 12px;
      font-size: 18px;
    }
    .nav-shell {
      position: relative;
      margin-top: 16px;
    }
    .nav-shell::after {
      content: "";
      position: absolute;
      top: 0;
      right: 0;
      bottom: 0;
      width: 34px;
      pointer-events: none;
      background: linear-gradient(90deg, rgba(244, 241, 234, 0), #f4f1ea 80%);
    }
    .nav {
      display: flex;
      flex-wrap: nowrap;
      gap: 8px;
      overflow-x: auto;
      overflow-y: hidden;
      padding: 0 34px 6px 0;
      scrollbar-width: thin;
      scroll-snap-type: x proximity;
      -webkit-overflow-scrolling: touch;
    }
    .nav a {
      border: 1px solid #cfc5b4;
      border-radius: 6px;
      flex: 0 0 auto;
      padding: 7px 10px;
      background: #fffaf2;
      text-decoration: none;
      color: #245b78;
      font-size: 14px;
      line-height: 1.25;
      scroll-snap-align: start;
      white-space: nowrap;
    }
    .nav a.active {
      background: #e6f1f5;
      border-color: #8bb8ca;
      color: #153d52;
      font-weight: 700;
    }
    .summary, .wide-summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 12px;
      margin: 20px 0;
    }
    .metric, .note {
      border: 1px solid #d5cec1;
      border-radius: 8px;
      padding: 14px;
      background: #fffaf2;
    }
    .label {
      display: block;
      color: #665f54;
      font-size: 13px;
      margin-bottom: 6px;
    }
    .value {
      font-size: 22px;
      font-weight: 700;
    }
    .small {
      color: #665f54;
      font-size: 13px;
      line-height: 1.45;
    }
    table {
      display: block;
      overflow-x: auto;
      width: 100%;
      border-collapse: collapse;
      background: #fffaf2;
      border: 1px solid #d5cec1;
    }
    th, td {
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid #ddd4c5;
      vertical-align: top;
    }
    th {
      color: #4d463d;
      font-size: 13px;
    }
    ul {
      margin: 8px 0 0 18px;
      padding: 0;
    }
    li {
      margin: 4px 0;
    }
    form.note {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      align-items: end;
    }
    input, select, button {
      box-sizing: border-box;
      width: 100%;
      border: 1px solid #cfc5b4;
      border-radius: 6px;
      padding: 9px 10px;
      background: #fff;
      color: #222;
      font: inherit;
    }
    input[type="checkbox"] {
      width: auto;
    }
    button {
      background: #245b78;
      border-color: #245b78;
      color: #fff;
      font-weight: 700;
      cursor: pointer;
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    summary {
      cursor: pointer;
      font-weight: 700;
    }
    .form-wide {
      grid-column: 1 / -1;
    }
    .stack {
      display: grid;
      gap: 12px;
      margin-top: 12px;
    }
    .checkbox-list {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 8px;
    }
    .checkbox-list label {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      border: 1px solid #d5cec1;
      border-radius: 6px;
      padding: 9px 10px;
      background: rgba(255, 255, 255, 0.45);
    }
    .message {
      border-radius: 8px;
      padding: 12px 14px;
      margin: 14px 0;
      border: 1px solid #b6cfbc;
      background: #eef8f0;
      color: #23482a;
    }
    .message.error {
      border-color: #e2b7b0;
      background: #fff0ee;
      color: #6b241b;
    }
    a {
      color: #245b78;
    }
    @media (prefers-color-scheme: dark) {
      body {
        background: #111820;
        color: #f1f4f7;
      }
      .metric, .note, table, .nav a {
        background: #1b2835;
        border-color: #2d3f50;
      }
      .nav-shell::after {
        background: linear-gradient(90deg, rgba(17, 24, 32, 0), #111820 80%);
      }
      .nav a.active {
        background: #254050;
        border-color: #44718a;
        color: #d9f1ff;
      }
      th, td {
        border-color: #2d3f50;
      }
      th, .label, .small {
        color: #b8c2ca;
      }
      input, select {
        background: #111820;
        border-color: #2d3f50;
        color: #f1f4f7;
      }
      .checkbox-list label {
        background: rgba(17, 24, 32, 0.35);
        border-color: #2d3f50;
      }
      .message {
        background: #183222;
        border-color: #315f3f;
        color: #d9f4df;
      }
      .message.error {
        background: #3a1d1a;
        border-color: #70372f;
        color: #ffd8d2;
      }
      a, .nav a {
        color: #88c7ef;
      }
    }
    @media (max-width: 900px) {
      main {
        padding: 22px 12px 42px;
      }
      header {
        margin-bottom: 18px;
      }
      h1 {
        font-size: 24px;
      }
      .nav-shell {
        margin-left: -12px;
        margin-right: -12px;
        padding-left: 12px;
      }
      .nav a {
        min-height: 38px;
        display: inline-flex;
        align-items: center;
      }
    }
    @media (max-width: 520px) {
      h1 {
        font-size: 22px;
      }
      .summary, .wide-summary {
        grid-template-columns: 1fr;
      }
      .nav a {
        font-size: 13px;
        padding: 8px 10px;
      }
    }
  </style>"""


def _page_header(title: str, subtitle: str, auth_token: str, *, active_path: str) -> str:
    return (
        "  <header>\n"
        f"    <h1>{escape(title)}</h1>\n"
        f"    <div>{escape(subtitle)}</div>\n"
        f"    {_nav_links(auth_token, active_path=active_path)}\n"
        "  </header>"
    )


def _nav_links(auth_token: str, *, active_path: str) -> str:
    links = (
        ("/", "Сводка"),
        ("/feeds", "Корма и склад"),
        ("/mix", "Смесь"),
        ("/livestock", "Поголовье и стада"),
        ("/eggs", "Яйца"),
        ("/incubation", "Инкубация"),
        ("/about", "О боте"),
    )
    rendered = []
    for path, label in links:
        class_attr = ' class="active"' if path == active_path else ""
        current_attr = ' aria-current="page"' if path == active_path else ""
        rendered.append(
            f'<a href="{escape(_link(path, auth_token))}"{class_attr}{current_attr}>{escape(label)}</a>'
        )
    nav = '<nav class="nav" aria-label="Основные разделы">' + "\n      ".join(rendered) + "</nav>"
    return f'<div class="nav-shell">{nav}</div>'


def _render_index(config: WebConfig, report: dict, summary: dict, *, auth_token: str = "") -> str:
    status_value = escape(str(report.get("status", "unknown")))
    db_status = escape(str(report.get("db", {}).get("status", "unknown")))
    users_total = escape(str(report.get("users", {}).get("total", 0)))
    critical_total = escape(str(report.get("errors", {}).get("critical_total", 0)))
    selected_user = summary.get("selected_user_id")
    selected_user_label = "не выбран" if selected_user is None else str(selected_user)
    eggs = summary.get("eggs") or {}
    feeds = summary.get("feeds") or {}
    incubation = summary.get("incubation") or {}
    settings = summary.get("settings") or {}
    ready_mix = feeds.get("ready_mix") or {}
    possible_mix = feeds.get("possible_mix") or {}
    bird_groups = feeds.get("bird_groups") or {}
    heartbeat_rows = "\n".join(_render_heartbeat_row(item) for item in report.get("heartbeats", []))
    if not heartbeat_rows:
        heartbeat_rows = "<tr><td colspan=\"5\">Heartbeat пока не получен.</td></tr>"
    flock_rows = "\n".join(_render_flock_row(item) for item in feeds.get("flocks", []))
    if not flock_rows:
        flock_rows = "<tr><td colspan=\"5\">Стада пока не созданы.</td></tr>"
    batch_rows = "\n".join(_render_batch_row(item) for item in incubation.get("batches", []))
    if not batch_rows:
        batch_rows = "<tr><td colspan=\"5\">Активных партий нет.</td></tr>"
    weather_text = _weather_text((eggs.get("weather") or {}))

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>tg_bot_inkubator</title>
  {_page_style()}
</head>
<body>
<main>
{_page_header("tg_bot_inkubator", "Web-сводка хозяйства и технического состояния.", auth_token, active_path="/")}

  <section class="summary" aria-label="Сводка">
    <div class="metric"><span class="label">Статус</span><span class="value">{status_value}</span></div>
    <div class="metric"><span class="label">База данных</span><span class="value">{db_status}</span></div>
    <div class="metric"><span class="label">Пользователей</span><span class="value">{users_total}</span></div>
    <div class="metric"><span class="label">Критичных ошибок</span><span class="value">{critical_total}</span></div>
  </section>

  <h2>Хозяйство</h2>
  <section class="wide-summary" aria-label="Хозяйственная сводка">
    <div class="metric">
      <span class="label">Пользователь</span>
      <span class="value">{escape(selected_user_label)}</span>
      <div class="small">Хозяйство: {escape(str(settings.get("farm_name") or "не указано"))}</div>
    </div>
    <div class="metric">
      <span class="label">Яйца сегодня</span>
      <span class="value">{escape(str(eggs.get("today_eggs", 0)))}</span>
      <div class="small">Несутся: {escape(str(eggs.get("active_hens", 0)))} из {escape(str(eggs.get("total_hens", 0)))}. Прогноз на 7 дней: {escape(str(eggs.get("next_week_forecast", 0)))}</div>
    </div>
    <div class="metric">
      <span class="label">Готовая смесь</span>
      <span class="value">{escape(_kg(ready_mix.get("remaining_kg")))}</span>
      <div class="small">Расход: {escape(_kg(ready_mix.get("daily_usage_kg")))} в день. Дней: {escape(_days(ready_mix.get("days_left")))}</div>
    </div>
    <div class="metric">
      <span class="label">Возможные замесы</span>
      <span class="value">{escape(str(possible_mix.get("mix_count", 0)))}</span>
      <div class="small">Получится: {escape(_kg(possible_mix.get("output_kg")))}. Ограничивает: {escape(str(possible_mix.get("limiting_ingredient") or "не уточнено"))}</div>
    </div>
    <div class="metric">
      <span class="label">Птицы</span>
      <span class="value">{escape(str(bird_groups.get("birds_total", 0)))}</span>
      <div class="small">Несушки: {escape(str(bird_groups.get("hens", 0)))}, петухи: {escape(str(bird_groups.get("roosters", 0)))}, цыплята: {escape(str(bird_groups.get("chicks", 0)))}</div>
    </div>
    <div class="metric">
      <span class="label">Инкубация</span>
      <span class="value">{escape(str(incubation.get("active_batches", 0)))}</span>
      <div class="small">Активных партий. Завершено: {escape(str(incubation.get("completed_batches", 0)))}</div>
    </div>
  </section>

  <h2>Погода</h2>
  <p>{escape(weather_text)}</p>

  <h2>Стада</h2>
  <table>
    <thead>
      <tr>
        <th>Стадо</th>
        <th>Птиц</th>
        <th>Расход</th>
        <th>Запас</th>
        <th>Замесы</th>
      </tr>
    </thead>
    <tbody>
      {flock_rows}
    </tbody>
  </table>

  <h2>Активная инкубация</h2>
  <table>
    <thead>
      <tr>
        <th>Партия</th>
        <th>Вид</th>
        <th>День</th>
        <th>Этап</th>
        <th>Вывод</th>
      </tr>
    </thead>
    <tbody>
      {batch_rows}
    </tbody>
  </table>

  <h2>Версия</h2>
  <p>
    Версия: <strong>{escape(config.release_version)}</strong><br>
    Канал: {escape(config.release_channel)}<br>
    Окружение: {escape(config.environment)}<br>
    Commit: {escape(config.release_commit or "не указан")}<br>
    Последний деплой: {escape(config.release_deployed_at or "не указан")}
  </p>
  <p>
    <a href="{escape(config.github_url)}">GitHub</a> ·
    <a href="{escape(config.changelog_url)}">История изменений</a>
  </p>

  <h2>Runtime-сервисы</h2>
  <table>
    <thead>
      <tr>
        <th>Сервис</th>
        <th>Статус</th>
        <th>Свежесть</th>
        <th>Uptime</th>
        <th>Ошибка</th>
      </tr>
    </thead>
    <tbody>
      {heartbeat_rows}
    </tbody>
  </table>
</main>
</body>
</html>"""


def _render_feeds_page(config: WebConfig, payload: dict, *, auth_token: str = "") -> str:
    feeds = payload.get("feeds") or {}
    ready_mix = feeds.get("ready_mix") or {}
    possible_mix = feeds.get("possible_mix") or {}
    notice_html = _status_message_html(payload.get("notice"), payload.get("error"))
    filter_kind = str(payload.get("filter_kind") or "")
    sort_key = str(payload.get("sort") or "name")
    stock_items = _filter_stock_items(feeds.get("stock_items", []), kind=filter_kind, sort=sort_key)
    stock_rows = "\n".join(_render_stock_row(item) for item in stock_items)
    if not stock_rows:
        stock_rows = "<tr><td colspan=\"5\">Склад пока пуст.</td></tr>"
    flock_rows = "\n".join(_render_flock_row(item) for item in feeds.get("flocks", []))
    if not flock_rows:
        flock_rows = "<tr><td colspan=\"5\">Стада пока не созданы.</td></tr>"
    history_rows = "\n".join(_render_history_row(item) for item in payload.get("history", []))
    if not history_rows:
        history_rows = "<tr><td colspan=\"5\">Истории операций пока нет.</td></tr>"
    selected_user = payload.get("selected_user_id")
    selected_user_label = "не выбран" if selected_user is None else str(selected_user)
    kind_options = "".join(
        _option(value, label, selected=filter_kind == value)
        for value, label in (
            ("", "Все позиции"),
            ("ingredient", "Ингредиенты"),
            ("finished_mix", "Готовая смесь"),
            ("commercial_feed", "Готовый корм"),
            ("other", "Другое"),
        )
    )
    sort_options = "".join(
        _option(value, label, selected=sort_key == value)
        for value, label in (
            ("name", "По названию"),
            ("remaining_desc", "Остаток: больше сверху"),
            ("days_asc", "Сначала заканчивается"),
        )
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Корма и склад</title>
  {_page_style()}
</head>
<body>
<main>
{_page_header("Корма и склад", "Read-only просмотр запасов, смеси, стад и последних операций.", auth_token, active_path="/feeds")}

  <section class="summary">
    <div class="metric"><span class="label">Пользователь</span><span class="value">{escape(selected_user_label)}</span></div>
    <div class="metric"><span class="label">Готовая смесь</span><span class="value">{escape(_kg(ready_mix.get("remaining_kg")))}</span></div>
    <div class="metric"><span class="label">Хватит готовой смеси</span><span class="value">{escape(_days(ready_mix.get("days_left")))}</span></div>
    <div class="metric"><span class="label">Возможные замесы</span><span class="value">{escape(str(possible_mix.get("mix_count", 0)))}</span></div>
    <div class="metric"><span class="label">Будет получено</span><span class="value">{escape(_kg(possible_mix.get("output_kg")))}</span></div>
    <div class="metric"><span class="label">Ограничивает</span><span class="value">{escape(str(possible_mix.get("limiting_ingredient") or "не уточнено"))}</span></div>
  </section>

  {notice_html}

  <h2>Добавить покупку</h2>
  <form class="note" method="post" action="{escape(_link('/stock/purchases', auth_token))}">
    <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
    <label>
      <span class="label">Название</span>
      <input name="name" type="text" maxlength="120" required placeholder="например, премикс">
    </label>
    <label>
      <span class="label">Тип</span>
      <select name="kind">
        <option value="ingredient">Ингредиент</option>
        <option value="finished_mix">Готовая смесь</option>
        <option value="commercial_feed">Готовый корм</option>
        <option value="other">Другое</option>
      </select>
    </label>
    <label>
      <span class="label">Количество</span>
      <input name="amount" type="text" maxlength="80" required placeholder="25 кг, 1 мешок, 2 пачки 500 гр">
    </label>
    <label>
      <span class="label">Комментарий</span>
      <input name="note" type="text" maxlength="120" placeholder="необязательно">
    </label>
    <button type="submit">Добавить на склад</button>
  </form>

  <h2>Склад</h2>
  <form class="note" method="get" action="/feeds">
    <input type="hidden" name="auth" value="{escape(auth_token)}">
    <label>
      <span class="label">Показать</span>
      <select name="kind">{kind_options}</select>
    </label>
    <label>
      <span class="label">Сортировка</span>
      <select name="sort">{sort_options}</select>
    </label>
    <button type="submit">Применить</button>
  </form>
  <table>
    <thead>
      <tr><th>Позиция</th><th>Тип</th><th>Остаток</th><th>Расход в день</th><th>Дней</th></tr>
    </thead>
    <tbody>{stock_rows}</tbody>
  </table>

  <h2>Стада и расход</h2>
  <table>
    <thead>
      <tr><th>Стадо</th><th>Птиц</th><th>Расход</th><th>Запас</th><th>Замесы</th></tr>
    </thead>
    <tbody>{flock_rows}</tbody>
  </table>

  <h2>История операций</h2>
  <table>
    <thead>
      <tr><th>Дата</th><th>Позиция</th><th>Операция</th><th>Количество</th><th>Остаток</th></tr>
    </thead>
    <tbody>{history_rows}</tbody>
  </table>
</main>
</body>
</html>"""


def _render_mix_page(config: WebConfig, payload: dict, *, auth_token: str = "") -> str:
    mix = payload.get("mix") or {}
    feeds = payload.get("feeds") or {}
    ready_mix = feeds.get("ready_mix") or {}
    notice_html = _status_message_html(payload.get("notice"), payload.get("error"))
    ingredient_rows = "\n".join(
        _render_mix_ingredient_row(item) for item in mix.get("ingredients", [])
    )
    if not ingredient_rows:
        ingredient_rows = "<tr><td colspan=\"6\">Формула смеси пока не рассчитана.</td></tr>"
    variant_rows = "\n".join(
        _render_mix_variant_row(item) for item in mix.get("grain_base_options", [])
    )
    if not variant_rows:
        variant_rows = "<tr><td colspan=\"4\">Варианты основы пока не рассчитаны.</td></tr>"
    history_rows = "\n".join(_render_mix_history_row(item) for item in payload.get("history", []))
    if not history_rows:
        history_rows = "<tr><td colspan=\"5\">Созданных замесов пока нет.</td></tr>"
    selected_user = payload.get("selected_user_id")
    selected_user_label = "не выбран" if selected_user is None else str(selected_user)
    base_options = "\n".join(
        _render_grain_base_option(item, selected_code=str(mix.get("grain_base_code") or ""))
        for item in mix.get("grain_base_options", [])
    )
    if not base_options:
        base_options = '<option value="wheat">Пшеница</option>'
    quick_counts = mix.get("quick_mix_counts") or []
    quick_counts_text = ", ".join(str(item) for item in quick_counts) if quick_counts else "нет"
    missing = mix.get("missing_ingredients") or []
    missing_text = ", ".join(str(item) for item in missing) if missing else "ничего не нужно"
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Смесь</title>
  {_page_style()}
</head>
<body>
<main>
{_page_header("Смесь", "Read-only просмотр формулы замеса, доступных повторов и истории готовой смеси.", auth_token, active_path="/mix")}

  <section class="summary">
    <div class="metric"><span class="label">Пользователь</span><span class="value">{escape(selected_user_label)}</span></div>
    <div class="metric"><span class="label">Основа</span><span class="value">{escape(str(mix.get("grain_base_label") or "не выбрана"))}</span></div>
    <div class="metric"><span class="label">Один замес</span><span class="value">{escape(_kg(mix.get("one_cycle_kg")))}</span><div class="small">{escape(str(mix.get("one_cycle_parts", 0)))} частей</div></div>
    <div class="metric"><span class="label">Можно сделать</span><span class="value">{escape(str(mix.get("possible_mix_count", 0)))}</span><div class="small">полных замесов</div></div>
    <div class="metric"><span class="label">Будет смеси</span><span class="value">{escape(_kg(mix.get("possible_output_kg")))}</span></div>
    <div class="metric"><span class="label">Готовой смеси сейчас</span><span class="value">{escape(_kg(ready_mix.get("remaining_kg")))}</span><div class="small">Хватит: {escape(_days(ready_mix.get("days_left")))}</div></div>
  </section>

  {notice_html}

  <section class="note">
    <strong>Как читать расчет</strong>
    <div class="small">
      Формула показана в частях: если одна часть равна одной литровой кружке, то 3.5 части означает 3.5 кружки.
      Вес рядом нужен только для складского расчета. Если делается несколько замесов, это повторы одного базового цикла, а не один большой общий замес.
    </div>
  </section>

  <h2>Формула одного замеса</h2>
  <table>
    <thead>
      <tr><th>Ингредиент</th><th>Группа</th><th>Части</th><th>Нужно по складу</th><th>Есть</th><th>Статус</th></tr>
    </thead>
    <tbody>{ingredient_rows}</tbody>
  </table>

  <h2>Выбор основы</h2>
  <table>
    <thead>
      <tr><th>Основа</th><th>Полных замесов</th><th>Ограничивает</th><th>Не хватает</th></tr>
    </thead>
    <tbody>{variant_rows}</tbody>
  </table>

  <h2>Подсказка для замеса</h2>
  <section class="note">
    <div class="small">
      Быстрые количества, которые сейчас можно безопасно повторить по складу: {escape(quick_counts_text)}.
      Ограничивающий ингредиент: {escape(str(mix.get("limiting_ingredient") or "не уточнен"))}.
      Докупить для полного замеса: {escape(missing_text)}.
    </div>
  </section>

  <h2>Создать замес</h2>
  <form class="note" method="get" action="{escape(_link('/mix/confirm', auth_token))}">
    <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
    <label>
      <span class="label">Повторов базового замеса</span>
      <input name="mix_count" type="number" min="1" step="1" value="1" required>
    </label>
    <label>
      <span class="label">Основа</span>
      <select name="grain_base">
        {base_options}
      </select>
    </label>
    <button type="submit">Рассчитать и подтвердить</button>
  </form>

  <h2>Последние замесы</h2>
  <table>
    <thead>
      <tr><th>Дата</th><th>Замес</th><th>Позиция</th><th>Получено</th><th>Остаток после</th></tr>
    </thead>
    <tbody>{history_rows}</tbody>
  </table>
</main>
</body>
</html>"""


def _render_mix_confirm_page(
    config: WebConfig,
    *,
    selected_user_id: int,
    plan,
    auth_token: str = "",
) -> str:
    ingredient_rows = "\n".join(_render_mix_plan_required_row(item) for item in plan.ingredients)
    if not ingredient_rows:
        ingredient_rows = "<tr><td colspan=\"5\">Ингредиенты не рассчитаны.</td></tr>"
    confirm_button = ""
    if plan.can_produce:
        confirm_button = f"""
  <form class="note" method="post" action="{escape(_link('/feeds/mixes', auth_token))}">
    <input type="hidden" name="user_id" value="{escape(str(selected_user_id))}">
    <input type="hidden" name="mix_count" value="{escape(str(plan.mix_count))}">
    <input type="hidden" name="grain_base" value="{escape(str(plan.grain_base_code))}">
    <button type="submit">Создать замес и обновить склад</button>
  </form>"""
    else:
        confirm_button = (
            '<div class="message error">Ингредиентов недостаточно. '
            f'<a href="{escape(_link("/mix", auth_token))}">Вернуться к смеси</a>.</div>'
        )
    status_text = "ингредиентов хватает" if plan.can_produce else "ингредиентов недостаточно"
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Подтверждение замеса</title>
  {_page_style()}
</head>
<body>
<main>
{_page_header("Подтверждение замеса", "Проверьте списание ингредиентов перед изменением склада.", auth_token, active_path="/mix")}

  <section class="summary">
    <div class="metric"><span class="label">Повторов</span><span class="value">{escape(f"{plan.mix_count:g}")}</span></div>
    <div class="metric"><span class="label">Основа</span><span class="value">{escape(str(plan.grain_base_label))}</span></div>
    <div class="metric"><span class="label">Будет получено</span><span class="value">{escape(_kg(plan.output_kg))}</span></div>
    <div class="metric"><span class="label">Статус</span><span class="value">{escape(status_text)}</span></div>
  </section>

  <h2>Что будет списано</h2>
  <table>
    <thead>
      <tr><th>Ингредиент</th><th>Части на цикл</th><th>Нужно</th><th>Есть</th><th>Не хватает</th></tr>
    </thead>
    <tbody>{ingredient_rows}</tbody>
  </table>

  {confirm_button}
</main>
</body>
</html>"""


def _render_livestock_page(config: WebConfig, payload: dict, *, auth_token: str = "") -> str:
    groups = payload.get("bird_groups", [])
    flocks = payload.get("flocks", [])
    feeds = payload.get("feeds") or {}
    bird_groups = feeds.get("bird_groups") or {}
    stock_items = feeds.get("stock_items") or []
    filter_role = str(payload.get("filter_role") or "")
    sort_key = str(payload.get("sort") or "name")
    visible_groups = _filter_bird_groups(groups, role=filter_role, sort=sort_key)
    ready_mix_options = "\n".join(
        _render_stock_item_option(item)
        for item in stock_items
        if item.get("kind") == "finished_mix"
    )
    selected_user = payload.get("selected_user_id")
    selected_user_label = "не выбран" if selected_user is None else str(selected_user)
    notice_html = _status_message_html(payload.get("notice"), payload.get("error"))
    group_rows = "\n".join(_render_bird_group_row(item) for item in visible_groups)
    if not group_rows:
        group_rows = "<tr><td colspan=\"7\">Поголовье пока не добавлено.</td></tr>"
    role_options = "".join(
        _option(value, label, selected=filter_role == value)
        for value, label in (
            ("", "Все группы"),
            ("hens", "Куры/несушки"),
            ("roosters", "Петухи"),
            ("mixed", "Смешанные"),
            ("chicks", "Цыплята"),
        )
    )
    group_sort_options = "".join(
        _option(value, label, selected=sort_key == value)
        for value, label in (
            ("name", "По названию"),
            ("count_desc", "Больше птиц сверху"),
        )
    )
    member_options = "\n".join(_render_flock_member_option(item) for item in groups)
    flock_form_button = '<button type="submit">Создать стадо</button>'
    if not member_options:
        member_options = '<p class="small">Сначала добавьте хотя бы одну группу поголовья.</p>'
        flock_form_button = '<button type="submit" disabled>Создать стадо</button>'
    group_edit_forms = "\n".join(
        _render_bird_group_edit_form(item, selected_user=selected_user, auth_token=auth_token)
        for item in groups
    )
    if not group_edit_forms:
        group_edit_forms = '<p class="small">Поголовье пока не добавлено.</p>'
    flock_rows = "\n".join(_render_livestock_flock_row(item) for item in flocks)
    if not flock_rows:
        flock_rows = "<tr><td colspan=\"6\">Стада пока не созданы.</td></tr>"
    flock_options = "\n".join(_render_flock_option(item) for item in flocks)
    flock_edit_forms = "\n".join(
        _render_flock_edit_form(
            item,
            groups=groups,
            selected_user=selected_user,
            auth_token=auth_token,
        )
        for item in flocks
    )
    if not flock_edit_forms:
        flock_edit_forms = '<p class="small">Стада пока не созданы.</p>'
    assignment_rows = "\n".join(
        _render_flock_assignment_row(flock, assignment)
        for flock in flocks
        for assignment in flock.get("assignments", [])
    )
    if not assignment_rows:
        assignment_rows = "<tr><td colspan=\"8\">Назначенной готовой смеси пока нет.</td></tr>"
    assignment_form = ""
    if flock_options and ready_mix_options:
        assignment_form = f"""
  <h2>Назначить смесь стаду</h2>
  <form class="note" method="post" action="{escape(_link('/flock-feed-assignments', auth_token))}">
    <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
    <label>
      <span class="label">Стадо</span>
      <select name="flock_id">{flock_options}</select>
    </label>
    <label>
      <span class="label">Готовая смесь</span>
      <select name="stock_item_id">{ready_mix_options}</select>
    </label>
    <button type="submit">Назначить смесь</button>
  </form>"""
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Поголовье и стада</title>
  {_page_style()}
</head>
<body>
<main>
{_page_header("Поголовье и стада", "Группы птиц, состав стад, назначенная смесь, добавление поголовья и создание стад.", auth_token, active_path="/livestock")}

  <section class="summary">
    <div class="metric"><span class="label">Пользователь</span><span class="value">{escape(selected_user_label)}</span></div>
    <div class="metric"><span class="label">Всего птиц</span><span class="value">{escape(str(bird_groups.get("birds_total", 0)))}</span></div>
    <div class="metric"><span class="label">Групп поголовья</span><span class="value">{escape(str(bird_groups.get("total", len(groups))))}</span></div>
    <div class="metric"><span class="label">Стад</span><span class="value">{escape(str(len(flocks)))}</span></div>
    <div class="metric"><span class="label">Несушки</span><span class="value">{escape(str(bird_groups.get("hens", 0)))}</span></div>
    <div class="metric"><span class="label">Цыплята</span><span class="value">{escape(str(bird_groups.get("chicks", 0)))}</span></div>
  </section>

  {notice_html}

  <h2>Добавить поголовье</h2>
  <form class="note" method="post" action="{escape(_link('/bird-groups', auth_token))}">
    <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
    <label>
      <span class="label">Название</span>
      <input name="name" type="text" maxlength="120" required placeholder="например, Несушки">
    </label>
    <label>
      <span class="label">Количество птиц</span>
      <input name="bird_count" type="number" min="1" step="1" required>
    </label>
    <label>
      <span class="label">Птица</span>
      <select name="species">
        <option value="chicken">Куры</option>
        <option value="goose">Гуси</option>
        <option value="quail">Перепела</option>
        <option value="duck">Утки</option>
        <option value="muscovy_duck">Мускусные утки</option>
      </select>
    </label>
    <label>
      <span class="label">Тип</span>
      <select name="group_kind">
        <option value="adult">Взрослые птицы</option>
        <option value="chicks">Цыплята</option>
      </select>
    </label>
    <label>
      <span class="label">Роль</span>
      <select name="role">
        <option value="hens">Куры/несушки</option>
        <option value="roosters">Петухи</option>
        <option value="mixed">Смешанная взрослая группа</option>
        <option value="chicks">Цыплята</option>
      </select>
    </label>
    <label>
      <span class="label">Дата вывода</span>
      <input name="hatched_at" type="date">
    </label>
    <label>
      <span class="label">Дата подсадки</span>
      <input name="joined_at" type="date">
    </label>
    <label>
      <span class="label">Запас для расчета, %</span>
      <input name="reserve_percent" type="number" min="0" step="1" value="0">
    </label>
    <button type="submit">Добавить поголовье</button>
  </form>

  <h2>Создать стадо</h2>
  <form class="note" method="post" action="{escape(_link('/flocks', auth_token))}">
    <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
    <label>
      <span class="label">Название стада</span>
      <input name="name" type="text" maxlength="120" required placeholder="например, Основное стадо">
    </label>
    <div class="form-wide">
      <span class="label">Состав стада</span>
      <div class="checkbox-list">
        {member_options}
      </div>
    </div>
    {flock_form_button}
  </form>

  <h2>Поголовье</h2>
  <form class="note" method="get" action="/livestock">
    <input type="hidden" name="auth" value="{escape(auth_token)}">
    <label>
      <span class="label">Показать</span>
      <select name="role">{role_options}</select>
    </label>
    <label>
      <span class="label">Сортировка</span>
      <select name="sort">{group_sort_options}</select>
    </label>
    <button type="submit">Применить</button>
  </form>
  <table>
    <thead>
      <tr><th>Группа</th><th>Птиц</th><th>Вид</th><th>Тип</th><th>Роль</th><th>Вывод</th><th>Подсадка</th></tr>
    </thead>
    <tbody>{group_rows}</tbody>
  </table>

  <details class="note">
    <summary>Редактировать поголовье</summary>
    <div class="stack">
      {group_edit_forms}
    </div>
  </details>

  <h2>Стада</h2>
  <table>
    <thead>
      <tr><th>Стадо</th><th>Птиц</th><th>Групп</th><th>Состав</th><th>Расход</th><th>Смесь</th></tr>
    </thead>
    <tbody>{flock_rows}</tbody>
  </table>

  <details class="note">
    <summary>Редактировать стада</summary>
    <div class="stack">
      {flock_edit_forms}
    </div>
  </details>

  {assignment_form}

  <h2>Назначенная смесь</h2>
  <table>
    <thead>
      <tr><th>Стадо</th><th>Смесь</th><th>Доля</th><th>Расход</th><th>Остаток</th><th>Хватит</th><th>Замесы</th><th>Всего дней</th></tr>
    </thead>
    <tbody>{assignment_rows}</tbody>
  </table>
</main>
</body>
</html>"""


def _render_eggs_page(config: WebConfig, payload: dict, *, auth_token: str = "") -> str:
    eggs = payload.get("eggs") or {}
    weather_text = _weather_text((eggs.get("weather") or {}))
    notice_html = _status_message_html(payload.get("notice"), payload.get("error"))
    history_rows = "\n".join(_render_egg_history_row(item) for item in payload.get("history", []))
    if not history_rows:
        history_rows = "<tr><td colspan=\"5\">Записей по яйцам пока нет.</td></tr>"
    exclusion_rows = "\n".join(_render_exclusion_row(item) for item in payload.get("open_exclusions", []))
    if not exclusion_rows:
        exclusion_rows = "<tr><td colspan=\"4\">Активных исключений нет.</td></tr>"
    selected_user = payload.get("selected_user_id")
    selected_user_label = "не выбран" if selected_user is None else str(selected_user)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Яйца</title>
  {_page_style()}
</head>
<body>
<main>
{_page_header("Яйца", "Read-only просмотр сбора, прогноза, исключений несушек и сохраненной погоды.", auth_token, active_path="/eggs")}

  <section class="summary">
    <div class="metric"><span class="label">Пользователь</span><span class="value">{escape(selected_user_label)}</span></div>
    <div class="metric"><span class="label">Сегодня</span><span class="value">{escape(str(eggs.get("today_eggs", 0)))} шт.</span></div>
    <div class="metric"><span class="label">За 7 дней</span><span class="value">{escape(str(eggs.get("week_eggs", 0)))} шт.</span></div>
    <div class="metric"><span class="label">За 30 дней</span><span class="value">{escape(str(eggs.get("month_eggs", 0)))} шт.</span></div>
    <div class="metric"><span class="label">Прогноз на 7 дней</span><span class="value">{escape(str(eggs.get("next_week_forecast", 0)))} шт.</span></div>
    <div class="metric">
      <span class="label">Несутся сейчас</span>
      <span class="value">{escape(str(eggs.get("active_hens", 0)))} из {escape(str(eggs.get("total_hens", 0)))}</span>
      <div class="small">Исключено: {escape(str(eggs.get("excluded_hens", 0)))}</div>
    </div>
  </section>

  {notice_html}

  <h2>Добавить сбор</h2>
  <form class="note" method="post" action="{escape(_link('/eggs/entries', auth_token))}">
    <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
    <label>
      <span class="label">День</span>
      <select name="entry_day">
        <option value="today">Сегодня</option>
        <option value="yesterday">Вчера</option>
      </select>
    </label>
    <label>
      <span class="label">Яиц</span>
      <input name="eggs_count" type="number" min="0" step="1" required>
    </label>
    <label>
      <span class="label">Комментарий</span>
      <input name="note" type="text" maxlength="120" placeholder="необязательно">
    </label>
    <button type="submit">Добавить запись</button>
  </form>

  <h2>Погода</h2>
  <p>{escape(weather_text)}</p>
  <form class="note" method="post" action="{escape(_link('/settings/weather', auth_token))}">
    <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
    <label>
      <span class="label">Город погоды</span>
      <input name="city" type="text" maxlength="120" required value="{escape(str(eggs.get('weather_city') or 'Курск'))}">
    </label>
    <button type="submit">Сохранить город</button>
  </form>

  <h2>История сбора</h2>
  <table>
    <thead>
      <tr><th>Дата</th><th>Яиц</th><th>Несушек</th><th>Исключено</th><th>Комментарий</th></tr>
    </thead>
    <tbody>{history_rows}</tbody>
  </table>

  <h2>Не несутся</h2>
  <table>
    <thead>
      <tr><th>Кур</th><th>Причина</th><th>С</th><th>Ожидаемо до</th></tr>
    </thead>
    <tbody>{exclusion_rows}</tbody>
  </table>
</main>
</body>
</html>"""


def _render_incubation_page(config: WebConfig, payload: dict, *, auth_token: str = "") -> str:
    incubation = payload.get("incubation") or {}
    active_rows = "\n".join(_render_active_incubation_row(item) for item in payload.get("active_batches", []))
    if not active_rows:
        active_rows = "<tr><td colspan=\"7\">Активных партий пока нет.</td></tr>"
    completed_rows = "\n".join(_render_completed_incubation_row(item) for item in payload.get("completed_batches", []))
    if not completed_rows:
        completed_rows = "<tr><td colspan=\"6\">Завершенных партий пока нет.</td></tr>"
    recommendation_blocks = "\n".join(
        _render_recommendation_block(item) for item in payload.get("active_batches", [])
    )
    if not recommendation_blocks:
        recommendation_blocks = "<p>Нет активных партий, для которых нужны рекомендации.</p>"
    selected_user = payload.get("selected_user_id")
    selected_user_label = "не выбран" if selected_user is None else str(selected_user)
    hatch_rate = incubation.get("hatch_rate")
    hatch_rate_label = "не рассчитано" if hatch_rate is None else f"{hatch_rate}%"
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Инкубация</title>
  {_page_style()}
</head>
<body>
<main>
{_page_header("Инкубация", "Read-only просмотр активных партий, этапов, ближайшего вывода и истории.", auth_token, active_path="/incubation")}

  <section class="summary">
    <div class="metric"><span class="label">Пользователь</span><span class="value">{escape(selected_user_label)}</span></div>
    <div class="metric"><span class="label">Активных партий</span><span class="value">{escape(str(incubation.get("active_batches", 0)))}</span></div>
    <div class="metric"><span class="label">Завершенных</span><span class="value">{escape(str(incubation.get("completed_batches", 0)))}</span></div>
    <div class="metric"><span class="label">Всего партий</span><span class="value">{escape(str(incubation.get("total_batches", 0)))}</span></div>
    <div class="metric"><span class="label">Выводимость</span><span class="value">{escape(hatch_rate_label)}</span></div>
  </section>

  <h2>Активные партии</h2>
  <table>
    <thead>
      <tr><th>Партия</th><th>Птица</th><th>Яиц</th><th>День</th><th>Этап</th><th>Вывод</th><th>Режим</th></tr>
    </thead>
    <tbody>{active_rows}</tbody>
  </table>

  <h2>Рекомендации</h2>
  {recommendation_blocks}

  <h2>История выводов</h2>
  <table>
    <thead>
      <tr><th>Партия</th><th>Птица</th><th>Яиц</th><th>Вывелось</th><th>Дата завершения</th><th>Процент</th></tr>
    </thead>
    <tbody>{completed_rows}</tbody>
  </table>
</main>
</body>
</html>"""


def _render_about_page(config: WebConfig, payload: dict, *, auth_token: str = "") -> str:
    release = payload.get("release") or {}
    settings = payload.get("settings") or {}
    sections = settings.get("sections") or {}
    runtime = payload.get("runtime") or {}
    notice_html = _status_message_html(payload.get("notice"), payload.get("error"))
    heartbeat_rows = "\n".join(
        _render_heartbeat_row(item) for item in runtime.get("heartbeats", [])
    )
    if not heartbeat_rows:
        heartbeat_rows = "<tr><td colspan=\"5\">Heartbeat пока не получен.</td></tr>"
    notes = release.get("release_notes") or []
    if notes:
        notes_html = "<ul>" + "".join(f"<li>{escape(str(item))}</li>" for item in notes) + "</ul>"
    else:
        notes_html = "<p class=\"small\">Краткое описание текущей версии не задано.</p>"
    selected_user = payload.get("selected_user_id")
    selected_user_label = "не выбран" if selected_user is None else str(selected_user)
    release_enabled = "включены" if release.get("release_notice_enabled") else "выключены"
    commit = str(release.get("commit") or "не указан")
    short_commit = commit[:12] if commit != "не указан" else commit
    sections_form = _render_sections_form(
        sections,
        selected_user=selected_user,
        auth_token=auth_token,
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>О боте</title>
  {_page_style()}
</head>
<body>
<main>
{_page_header("О боте", "Версия, деплой, ссылки, настройки хозяйства и технический статус.", auth_token, active_path="/about")}

  {notice_html}

  <section class="summary">
    <div class="metric"><span class="label">Версия</span><span class="value">{escape(str(release.get("version", "")))}</span></div>
    <div class="metric"><span class="label">Канал</span><span class="value">{escape(str(release.get("channel", "")))}</span></div>
    <div class="metric"><span class="label">Окружение</span><span class="value">{escape(str(release.get("environment", "")))}</span></div>
    <div class="metric"><span class="label">Runtime</span><span class="value">{escape(str(runtime.get("status", "unknown")))}</span></div>
    <div class="metric"><span class="label">Последний деплой</span><span class="value">{escape(_short_datetime(release.get("deployed_at")))}</span></div>
    <div class="metric"><span class="label">Commit</span><span class="value">{escape(short_commit)}</span></div>
  </section>

  <h2>Релиз</h2>
  <section class="wide-summary">
    <div class="note">
      <strong>Что нового</strong>
      {notes_html}
    </div>
    <div class="note">
      <strong>Уведомления об обновлениях</strong>
      <div class="small">
        Пользовательские сообщения: {escape(release_enabled)}<br>
        Важность релиза: {escape(str(release.get("release_importance") or "minor"))}<br>
        Фактический режим для пользователей: {escape(str(release.get("user_release_messages") or "off"))}<br>
        Admin-уведомления о старте: {escape(str(release.get("admin_startup_notice_mode") or "off"))}
      </div>
    </div>
  </section>

  <h2>Ссылки</h2>
  <p>
    <a href="{escape(str(release.get("github_url") or config.github_url))}">GitHub</a> ·
    <a href="{escape(str(release.get("changelog_url") or config.changelog_url))}">История изменений</a>
  </p>

  <h2>Настройки хозяйства</h2>
  <section class="summary">
    <div class="metric"><span class="label">Пользователь</span><span class="value">{escape(selected_user_label)}</span></div>
    <div class="metric"><span class="label">Хозяйство</span><span class="value">{escape(str(settings.get("farm_name") or "не указано"))}</span></div>
    <div class="metric"><span class="label">Часовой пояс</span><span class="value">{escape(str(settings.get("timezone") or config.timezone_name))}</span></div>
    <div class="metric"><span class="label">Уведомления</span><span class="value">{escape(str(settings.get("notification_time") or "09:00"))}</span></div>
  </section>

  <h2>Разделы Telegram-бота</h2>
  {sections_form}
  <table>
    <thead>
      <tr><th>Раздел</th><th>Статус</th></tr>
    </thead>
    <tbody>
      <tr><td>Инкубация</td><td>{escape(_enabled_label(sections.get("incubation", True)))}</td></tr>
      <tr><td>Корма</td><td>{escape(_enabled_label(sections.get("feeds", True)))}</td></tr>
      <tr><td>Яйца</td><td>{escape(_enabled_label(sections.get("eggs", True)))}</td></tr>
      <tr><td>Уход после вывода</td><td>{escape(_enabled_label(sections.get("post_hatch_care", True)))}</td></tr>
      <tr><td>Системные сообщения</td><td>{escape(_enabled_label(sections.get("service", True)))}</td></tr>
    </tbody>
  </table>

  <details class="note">
    <summary>Технический статус</summary>
    <table>
      <thead>
        <tr><th>Сервис</th><th>Статус</th><th>Свежесть</th><th>Uptime</th><th>Ошибка</th></tr>
      </thead>
      <tbody>{heartbeat_rows}</tbody>
    </table>
  </details>
</main>
</body>
</html>"""


def _link(path: str, auth_token: str = "") -> str:
    if not auth_token:
        return path
    return f"{path}?{urlencode({'auth': auth_token})}"


def _render_heartbeat_row(item: dict) -> str:
    stale = "просрочен" if item.get("stale") else "свежий"
    seconds = item.get("seconds_since_seen")
    freshness = stale if seconds is None else f"{stale}, {int(seconds)} сек."
    return (
        "<tr>"
        f"<td>{escape(str(item.get('service_name', '')))}</td>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td>{escape(freshness)}</td>"
        f"<td>{escape(str(item.get('uptime_seconds', 0)))} сек.</td>"
        f"<td>{escape(str(item.get('last_error') or ''))}</td>"
        "</tr>"
    )


def _render_sections_form(sections: dict, *, selected_user, auth_token: str) -> str:
    items = (
        ("incubation", "Инкубация"),
        ("feeds", "Корма"),
        ("eggs", "Яйца"),
        ("post_hatch_care", "Уход после вывода"),
        ("service", "Системные сообщения"),
    )
    checkboxes = "".join(
        (
            "<label>"
            f'<input type="checkbox" name="sections" value="{escape(key)}"'
            f'{" checked" if sections.get(key, True) else ""}>'
            f"<span>{escape(label)}</span>"
            "</label>"
        )
        for key, label in items
    )
    return f"""
  <form class="note" method="post" action="{escape(_link('/settings/sections', auth_token))}">
    <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
    <div class="form-wide">
      <span class="label">Кнопки главного меню Telegram-бота</span>
      <div class="checkbox-list">{checkboxes}</div>
    </div>
    <button type="submit">Сохранить разделы</button>
  </form>"""


def _render_flock_row(item: dict) -> str:
    assignments = item.get("assignments") or []
    first = assignments[0] if assignments else {}
    return (
        "<tr>"
        f"<td>{escape(str(item.get('name', '')))}</td>"
        f"<td>{escape(str(item.get('birds_total', 0)))}</td>"
        f"<td>{escape(_kg(item.get('daily_usage_kg')))} / день</td>"
        f"<td>{escape(_days(first.get('total_days_left') if first else None))}</td>"
        f"<td>{escape(str(first.get('producible_mix_count', 0) if first else 0))}</td>"
        "</tr>"
    )


def _render_batch_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(item.get('title', '')))}</td>"
        f"<td>{escape(str(item.get('species', '')))}</td>"
        f"<td>{escape(str(item.get('day', '')))}</td>"
        f"<td>{escape(str(item.get('stage', '')))}</td>"
        f"<td>{escape(str(item.get('hatch_date', '')))} ({escape(_days(item.get('days_left')))} )</td>"
        "</tr>"
    )


def _render_stock_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(item.get('name', '')))}</td>"
        f"<td>{escape(str(item.get('kind_label', item.get('kind', ''))))}</td>"
        f"<td>{escape(_kg(item.get('remaining_kg')))}</td>"
        f"<td>{escape(_kg(item.get('daily_usage_kg')))}</td>"
        f"<td>{escape(_days(item.get('days_left')))}</td>"
        "</tr>"
    )


def _filter_stock_items(items: list[dict], *, kind: str, sort: str) -> list[dict]:
    result = [item for item in items if not kind or item.get("kind") == kind]
    if sort == "remaining_desc":
        return sorted(result, key=lambda item: float(item.get("remaining_kg") or 0), reverse=True)
    if sort == "days_asc":
        return sorted(
            result,
            key=lambda item: (
                item.get("days_left") is None,
                int(item.get("days_left") or 0),
                str(item.get("name") or ""),
            ),
        )
    return sorted(result, key=lambda item: str(item.get("name") or "").lower())


def _render_history_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(_short_datetime(item.get('created_at')))}</td>"
        f"<td>{escape(str(item.get('item_name', '')))}</td>"
        f"<td>{escape(str(item.get('type_label', item.get('type', ''))))}</td>"
        f"<td>{escape(_kg(item.get('amount_kg')))}</td>"
        f"<td>{escape(_kg(item.get('balance_after_kg')))}</td>"
        "</tr>"
    )


def _render_mix_ingredient_row(item: dict) -> str:
    status_text = "хватает" if item.get("is_enough") else f"не хватает {_kg(item.get('missing_kg'))}"
    return (
        "<tr>"
        f"<td>{escape(str(item.get('name', '')))}</td>"
        f"<td>{escape(str(item.get('group', '')))}</td>"
        f"<td>{escape(_parts(item.get('parts')))}</td>"
        f"<td>{escape(_kg(item.get('required_kg')))}</td>"
        f"<td>{escape(_kg(item.get('available_kg')))}</td>"
        f"<td>{escape(status_text)}</td>"
        "</tr>"
    )


def _render_grain_base_option(item: dict, *, selected_code: str) -> str:
    code = str(item.get("code", ""))
    selected_attr = " selected" if code == selected_code else ""
    label = str(item.get("label") or code or "основа")
    count = str(item.get("possible_mix_count", 0))
    return f'<option value="{escape(code)}"{selected_attr}>{escape(label)} - {escape(count)} замесов</option>'


def _render_mix_plan_required_row(item) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(item.name))}</td>"
        f"<td>{escape(_parts(item.parts))}</td>"
        f"<td>{escape(_kg(item.required_kg))}</td>"
        f"<td>{escape(_kg(item.available_kg))}</td>"
        f"<td>{escape(_kg(item.missing_kg))}</td>"
        "</tr>"
    )


def _render_mix_variant_row(item: dict) -> str:
    missing = item.get("missing_ingredients") or []
    missing_text = ", ".join(str(value) for value in missing) if missing else "ничего"
    return (
        "<tr>"
        f"<td>{escape(str(item.get('label', '')))}</td>"
        f"<td>{escape(str(item.get('possible_mix_count', 0)))}</td>"
        f"<td>{escape(str(item.get('limiting_ingredient') or 'не уточнено'))}</td>"
        f"<td>{escape(missing_text)}</td>"
        "</tr>"
    )


def _render_mix_history_row(item: dict) -> str:
    mix_id = item.get("mix_id")
    mix_label = f"#{mix_id}" if mix_id else str(item.get("note") or "")
    return (
        "<tr>"
        f"<td>{escape(_short_datetime(item.get('created_at')))}</td>"
        f"<td>{escape(mix_label)}</td>"
        f"<td>{escape(str(item.get('item_name', '')))}</td>"
        f"<td>{escape(_kg(item.get('amount_kg')))}</td>"
        f"<td>{escape(_kg(item.get('balance_after_kg')))}</td>"
        "</tr>"
    )


def _render_bird_group_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(item.get('name', '')))}</td>"
        f"<td>{escape(str(item.get('bird_count', 0)))}</td>"
        f"<td>{escape(str(item.get('species_label', '')))}</td>"
        f"<td>{escape(str(item.get('group_kind_label', '')))}</td>"
        f"<td>{escape(str(item.get('role_label', '')))}</td>"
        f"<td>{escape(str(item.get('hatched_at') or ''))}</td>"
        f"<td>{escape(str(item.get('joined_at') or ''))}</td>"
        "</tr>"
    )


def _filter_bird_groups(items: list[dict], *, role: str, sort: str) -> list[dict]:
    result = [item for item in items if not role or item.get("role") == role]
    if sort == "count_desc":
        return sorted(result, key=lambda item: int(item.get("bird_count") or 0), reverse=True)
    return sorted(result, key=lambda item: str(item.get("name") or "").lower())


def _render_bird_group_edit_form(item: dict, *, selected_user, auth_token: str) -> str:
    group_id = item.get("id")
    role = str(item.get("role") or "mixed")
    role_options = "".join(
        _option(value, label, selected=role == value)
        for value, label in (
            ("hens", "Куры/несушки"),
            ("roosters", "Петухи"),
            ("mixed", "Смешанная взрослая группа"),
            ("chicks", "Цыплята"),
        )
    )
    return f"""
      <form class="note" method="post" action="{escape(_link(f'/bird-groups/{group_id}', auth_token))}">
        <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
        <label>
          <span class="label">Название</span>
          <input name="name" type="text" maxlength="120" required value="{escape(str(item.get('name') or ''))}">
        </label>
        <label>
          <span class="label">Количество</span>
          <input name="bird_count" type="number" min="1" step="1" required value="{escape(str(item.get('bird_count') or 1))}">
        </label>
        <label>
          <span class="label">Роль</span>
          <select name="role">{role_options}</select>
        </label>
        <label>
          <span class="label">Дата вывода</span>
          <input name="hatched_at" type="date" value="{escape(str(item.get('hatched_at') or ''))}">
        </label>
        <label>
          <span class="label">Дата подсадки</span>
          <input name="joined_at" type="date" value="{escape(str(item.get('joined_at') or ''))}">
        </label>
        <label>
          <span class="label">Запас, %</span>
          <input name="reserve_percent" type="number" min="0" step="1" value="{escape(str(item.get('reserve_percent') or 0))}">
        </label>
        <button type="submit">Сохранить поголовье</button>
      </form>"""


def _render_livestock_flock_row(item: dict) -> str:
    members = item.get("members") or []
    member_text = "; ".join(
        f"{member.get('bird_group_name') or 'без названия'}: {member.get('bird_count', 0)}"
        for member in members
    )
    assignments = item.get("assignments") or []
    feed_text = ", ".join(
        str(assignment.get("feed_name") or "смесь не указана") for assignment in assignments
    )
    return (
        "<tr>"
        f"<td>{escape(str(item.get('name', '')))}</td>"
        f"<td>{escape(str(item.get('birds_total', 0)))}</td>"
        f"<td>{escape(str(item.get('members_count', 0)))}</td>"
        f"<td>{escape(member_text or 'нет состава')}</td>"
        f"<td>{escape(_kg(item.get('daily_usage_kg')))} / день</td>"
        f"<td>{escape(feed_text or 'не назначена')}</td>"
        "</tr>"
    )


def _render_flock_option(item: dict) -> str:
    return _option(item.get("id"), item.get("name") or "стадо", selected=False)


def _render_stock_item_option(item: dict) -> str:
    label = f"{item.get('name') or 'смесь'} - {_kg(item.get('remaining_kg'))}"
    return _option(item.get("id"), label, selected=False)


def _render_flock_member_option(item: dict, *, checked: bool = False) -> str:
    group_id = item.get("id")
    checked_attr = " checked" if checked else ""
    label = (
        f"{item.get('name') or 'без названия'}: "
        f"{item.get('bird_count', 0)} птиц, "
        f"{item.get('role_label') or item.get('group_kind_label') or 'группа'}"
    )
    return (
        "<label>"
        f'<input type="checkbox" name="member_group_ids" value="{escape(str(group_id))}"{checked_attr}>'
        f"<span>{escape(label)}</span>"
        "</label>"
    )


def _render_flock_edit_form(
    item: dict,
    *,
    groups: list[dict],
    selected_user,
    auth_token: str,
) -> str:
    flock_id = item.get("id")
    selected_group_ids = {
        member.get("bird_group_id")
        for member in (item.get("members") or [])
    }
    member_options = "\n".join(
        _render_flock_member_option(group, checked=group.get("id") in selected_group_ids)
        for group in groups
    )
    return f"""
      <form class="note" method="post" action="{escape(_link(f'/flocks/{flock_id}', auth_token))}">
        <input type="hidden" name="user_id" value="{escape(str(selected_user or ''))}">
        <label>
          <span class="label">Название стада</span>
          <input name="name" type="text" maxlength="120" required value="{escape(str(item.get('name') or ''))}">
        </label>
        <div class="form-wide">
          <span class="label">Состав стада</span>
          <div class="checkbox-list">{member_options}</div>
        </div>
        <button type="submit">Сохранить стадо</button>
      </form>"""


def _render_flock_assignment_row(flock: dict, assignment: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(flock.get('name', '')))}</td>"
        f"<td>{escape(str(assignment.get('feed_name') or ''))}</td>"
        f"<td>{escape(str(assignment.get('share_percent', 100)))}%</td>"
        f"<td>{escape(_kg(assignment.get('daily_usage_kg')))} / день</td>"
        f"<td>{escape(_kg(assignment.get('remaining_kg')))}</td>"
        f"<td>{escape(_days(assignment.get('days_left')))}</td>"
        f"<td>{escape(str(assignment.get('producible_mix_count', 0)))}</td>"
        f"<td>{escape(_days(assignment.get('total_days_left')))}</td>"
        "</tr>"
    )


def _render_egg_history_row(item: dict) -> str:
    hens = f"{item.get('active_hens_count', 0)} из {item.get('total_hens_count', 0)}"
    return (
        "<tr>"
        f"<td>{escape(str(item.get('entry_date', '')))}</td>"
        f"<td>{escape(str(item.get('eggs_count', 0)))}</td>"
        f"<td>{escape(hens)}</td>"
        f"<td>{escape(str(item.get('excluded_hens_count', 0)))}</td>"
        f"<td>{escape(str(item.get('note') or ''))}</td>"
        "</tr>"
    )


def _render_exclusion_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(item.get('hens_count', 0)))}</td>"
        f"<td>{escape(str(item.get('reason', '')))}</td>"
        f"<td>{escape(str(item.get('started_at') or ''))}</td>"
        f"<td>{escape(str(item.get('expected_until') or 'не указано'))}</td>"
        "</tr>"
    )


def _render_active_incubation_row(item: dict) -> str:
    mode = f"{item.get('temperature') or ''}; {item.get('humidity') or ''}"
    days_left = item.get("days_left")
    hatch = str(item.get("hatch_date") or "")
    if days_left is not None:
        hatch = f"{hatch} ({_days(days_left)})"
    return (
        "<tr>"
        f"<td>{escape(str(item.get('title', '')))}</td>"
        f"<td>{escape(str(item.get('species_label', item.get('species', ''))))}</td>"
        f"<td>{escape(str(item.get('eggs_count', 0)))}</td>"
        f"<td>{escape(str(item.get('day', '')))}</td>"
        f"<td>{escape(str(item.get('stage', '')))}</td>"
        f"<td>{escape(hatch)}</td>"
        f"<td>{escape(mode)}</td>"
        "</tr>"
    )


def _render_completed_incubation_row(item: dict) -> str:
    hatch_rate = item.get("hatch_rate")
    hatch_rate_label = "не рассчитано" if hatch_rate is None else f"{hatch_rate}%"
    return (
        "<tr>"
        f"<td>{escape(str(item.get('title', '')))}</td>"
        f"<td>{escape(str(item.get('species_label', item.get('species', ''))))}</td>"
        f"<td>{escape(str(item.get('eggs_count', 0)))}</td>"
        f"<td>{escape(str(item.get('hatched_count') or 0))}</td>"
        f"<td>{escape(str(item.get('completed_at') or ''))}</td>"
        f"<td>{escape(hatch_rate_label)}</td>"
        "</tr>"
    )


def _option(value, label, *, selected: bool = False) -> str:
    selected_attr = " selected" if selected else ""
    return f'<option value="{escape(str(value))}"{selected_attr}>{escape(str(label))}</option>'


def _render_recommendation_block(item: dict) -> str:
    recommendations = item.get("recommendations") or []
    if recommendations:
        body = "<ul>" + "".join(f"<li>{escape(str(text))}</li>" for text in recommendations) + "</ul>"
    else:
        body = "<p class=\"small\">Рекомендаций на сегодня нет.</p>"
    note = item.get("note")
    note_text = f"<p class=\"small\">Заметка: {escape(str(note))}</p>" if note else ""
    return (
        "<section class=\"note\">"
        f"<strong>{escape(str(item.get('title', '')))}</strong>"
        f"<div class=\"small\">День {escape(str(item.get('day', '')))}, {escape(str(item.get('stage', '')))}</div>"
        f"{body}{note_text}"
        "</section>"
    )


def _kg(value) -> str:
    try:
        return f"{float(value):.1f} кг"
    except (TypeError, ValueError):
        return "0.0 кг"


def _parts(value) -> str:
    try:
        return f"{float(value):g} части"
    except (TypeError, ValueError):
        return "0 частей"


def _enabled_label(value) -> str:
    return "включен" if bool(value) else "выключен"


def _status_message_html(notice, error) -> str:
    if error:
        return f'<div class="message error">{escape(str(error))}</div>'
    if notice:
        return f'<div class="message">{escape(str(notice))}</div>'
    return ""


def _release_note_items(notes: str) -> list[str]:
    result = []
    for raw in str(notes or "").replace(";", "\n").splitlines():
        item = raw.strip(" -\t")
        if item:
            result.append(item)
    return result


def _days(value) -> str:
    if value is None:
        return "не рассчитано"
    return f"{int(value)} дн."


def _short_datetime(value) -> str:
    if not value:
        return ""
    text = str(value)
    return text[:16].replace("T", " ")


def _weather_text(weather: dict) -> str:
    if not weather:
        return "Погода за сегодня еще не загружена."
    day = weather.get("day") or {}
    night = weather.get("night") or {}
    tomorrow = weather.get("tomorrow") or {}
    return (
        f"{weather.get('city', '')}: день {day.get('temperature_min_c')}.."
        f"{day.get('temperature_max_c')} °C, {day.get('condition') or 'без описания'}; "
        f"ночь {night.get('temperature_min_c')}..{night.get('temperature_max_c')} °C, "
        f"{night.get('condition') or 'без описания'}; завтра "
        f"{tomorrow.get('temperature_min_c')}..{tomorrow.get('temperature_max_c')} °C, "
        f"{tomorrow.get('condition') or 'без описания'}."
    )
