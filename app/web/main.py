from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
import secrets
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.services.status_probe import build_status_report
from app.web.config import WebConfig, load_web_config
from app.web.summary import build_web_feeds, build_web_summary


class RestartRequest(BaseModel):
    target: str = "all"
    confirm: str
    requested_by: str = ""
    reason: str = ""


def create_app(config: WebConfig | None = None) -> FastAPI:
    web_config = config or load_web_config()
    app = FastAPI(title="tg_bot_inkubator web", version=web_config.release_version)
    app.state.web_config = web_config

    def require_admin(
        authorization: str | None = Header(default=None),
        x_web_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> None:
        expected = app.state.web_config.admin_token
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="WEB_ADMIN_TOKEN is not configured.",
            )
        provided = _extract_token(authorization, x_web_token, x_admin_token)
        if not provided or not secrets.compare_digest(provided, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def require_web_access(
        authorization: str | None = Header(default=None),
        x_web_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
        auth: str | None = Query(default=None),
    ) -> None:
        current = app.state.web_config
        provided = _extract_access_token(authorization, x_web_token, x_admin_token, auth)
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

    @app.get("/admin/service-status", dependencies=[Depends(require_admin)])
    def service_status() -> dict:
        report = build_status_report(app.state.web_config.db_path)
        services = {
            _status_bot_service_name(item): {
                "status": item.get("status", "unknown"),
                "last_seen_at": item.get("last_seen_at"),
                "last_error": item.get("last_error"),
                "required": item.get("required", True),
                "stale": item.get("stale", True),
                "seconds_since_seen": item.get("seconds_since_seen"),
            }
            for item in report.get("heartbeats", [])
        }
        return {
            "status": report.get("status", "unknown"),
            "version": report.get("version", ""),
            "generated_at": report.get("generated_at"),
            "database": report.get("db", {}).get("status", "unknown"),
            "db": report.get("db", {}),
            "last_errors_count": report.get("errors", {}).get("critical_total", 0),
            "heartbeat_down_after_seconds": report.get("heartbeat_down_after_seconds", 120),
            "services": services,
        }

    @app.get("/version", dependencies=[Depends(require_web_access)])
    def version() -> dict:
        current = app.state.web_config
        return {
            "version": current.release_version,
            "channel": current.release_channel,
            "environment": current.environment,
            "deployed_at": current.release_deployed_at or None,
            "commit": current.release_commit or None,
            "github_url": current.github_url,
            "changelog_url": current.changelog_url,
        }

    @app.post("/admin/restart", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_admin)])
    def restart(payload: RestartRequest) -> dict:
        allowed_targets = {"bot", "worker", "all"}
        target = payload.target.strip().lower()
        if payload.confirm != "restart:incubator":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid restart confirmation.")
        if target not in allowed_targets:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid restart target.")

        operation_id = f"incubator-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        request_dir = app.state.web_config.restart_request_dir
        try:
            request_dir.mkdir(parents=True, exist_ok=True)
            request_path = request_dir / f"{operation_id}.json"
            tmp_path = request_path.with_suffix(".tmp")
            request_payload = {
                "bot_key": "incubator",
                "target": target,
                "operation_id": operation_id,
                "requested_by": payload.requested_by[:120],
                "reason": payload.reason[:500],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            tmp_path.write_text(json.dumps(request_payload, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(request_path)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Restart request storage is unavailable: {exc}",
            ) from exc

        return {
            "status": "accepted",
            "operation_id": operation_id,
            "target": target,
            "message": "restart scheduled",
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
    ) -> str:
        current = request.app.state.web_config
        payload = build_web_feeds(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )
        return _render_feeds_page(current, payload, auth_token=auth or "")

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_web_access)])
    def index(
        request: Request,
        user_id: int | None = Query(default=None),
        auth: str | None = Query(default=None),
    ) -> str:
        current = request.app.state.web_config
        report = build_status_report(current.db_path)
        summary_payload = build_web_summary(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )
        return _render_index(current, report, summary_payload, auth_token=auth or "")

    return app


def _extract_token(
    authorization: str | None,
    x_web_token: str | None,
    x_admin_token: str | None = None,
) -> str:
    if x_admin_token:
        return x_admin_token.strip()
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
    x_admin_token: str | None,
    auth: str | None,
) -> str:
    if auth:
        return auth.strip()
    return _extract_token(authorization, x_web_token, x_admin_token)


def _status_bot_service_name(item: dict) -> str:
    service_name = str(item.get("service_name", ""))
    return {
        "polling_bot": "bot",
        "reminder_runner": "worker",
    }.get(service_name, service_name)


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
  <style>
    :root {{
      color-scheme: light dark;
      font-family: Arial, sans-serif;
    }}
    body {{
      margin: 0;
      background: #f4f1ea;
      color: #222;
    }}
    main {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 28px 18px 48px;
    }}
    header {{
      margin-bottom: 24px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
    }}
    h2 {{
      margin: 26px 0 12px;
      font-size: 18px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 12px;
    }}
    .wide-summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    .metric {{
      border: 1px solid #d5cec1;
      border-radius: 8px;
      padding: 14px;
      background: #fffaf2;
    }}
    .label {{
      display: block;
      color: #665f54;
      font-size: 13px;
      margin-bottom: 6px;
    }}
    .value {{
      font-size: 22px;
      font-weight: 700;
    }}
    .small {{
      color: #665f54;
      font-size: 13px;
      line-height: 1.45;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fffaf2;
      border: 1px solid #d5cec1;
    }}
    th, td {{
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid #ddd4c5;
    }}
    th {{
      color: #4d463d;
      font-size: 13px;
    }}
    a {{
      color: #245b78;
    }}
    @media (prefers-color-scheme: dark) {{
      body {{
        background: #111820;
        color: #f1f4f7;
      }}
      .metric, table {{
        background: #1b2835;
        border-color: #2d3f50;
      }}
      th, td {{
        border-color: #2d3f50;
      }}
      th, .label {{
        color: #b8c2ca;
      }}
      .small {{
        color: #b8c2ca;
      }}
      a {{
        color: #88c7ef;
      }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>tg_bot_inkubator</h1>
    <div>Web-сводка хозяйства и технического состояния.</div>
  </header>

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
    <a href="{escape(_link('/feeds', auth_token))}">Корма и склад</a> ·
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
    stock_rows = "\n".join(_render_stock_row(item) for item in feeds.get("stock_items", []))
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
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Корма и склад</title>
  <style>
    :root {{ color-scheme: light dark; font-family: Arial, sans-serif; }}
    body {{ margin: 0; background: #f4f1ea; color: #222; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 28px 18px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 20px 0; }}
    .metric {{ border: 1px solid #d5cec1; border-radius: 8px; padding: 14px; background: #fffaf2; }}
    .label {{ display: block; color: #665f54; font-size: 13px; margin-bottom: 6px; }}
    .value {{ font-size: 22px; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; background: #fffaf2; border: 1px solid #d5cec1; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #ddd4c5; vertical-align: top; }}
    th {{ color: #4d463d; font-size: 13px; }}
    a {{ color: #245b78; }}
    @media (prefers-color-scheme: dark) {{
      body {{ background: #111820; color: #f1f4f7; }}
      .metric, table {{ background: #1b2835; border-color: #2d3f50; }}
      th, td {{ border-color: #2d3f50; }}
      th, .label {{ color: #b8c2ca; }}
      a {{ color: #88c7ef; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>Корма и склад</h1>
    <div>Read-only просмотр запасов, смеси, стад и последних операций.</div>
    <p><a href="{escape(_link('/', auth_token))}">Сводка</a></p>
  </header>

  <section class="summary">
    <div class="metric"><span class="label">Пользователь</span><span class="value">{escape(selected_user_label)}</span></div>
    <div class="metric"><span class="label">Готовая смесь</span><span class="value">{escape(_kg(ready_mix.get("remaining_kg")))}</span></div>
    <div class="metric"><span class="label">Хватит готовой смеси</span><span class="value">{escape(_days(ready_mix.get("days_left")))}</span></div>
    <div class="metric"><span class="label">Возможные замесы</span><span class="value">{escape(str(possible_mix.get("mix_count", 0)))}</span></div>
    <div class="metric"><span class="label">Будет получено</span><span class="value">{escape(_kg(possible_mix.get("output_kg")))}</span></div>
    <div class="metric"><span class="label">Ограничивает</span><span class="value">{escape(str(possible_mix.get("limiting_ingredient") or "не уточнено"))}</span></div>
  </section>

  <h2>Склад</h2>
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


def _kg(value) -> str:
    try:
        return f"{float(value):.1f} кг"
    except (TypeError, ValueError):
        return "0.0 кг"


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
