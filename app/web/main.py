from __future__ import annotations

from html import escape
import secrets
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

from app.services.status_probe import build_status_report
from app.web.config import WebConfig, load_web_config
from app.web.summary import (
    build_web_eggs,
    build_web_feeds,
    build_web_incubation,
    build_web_livestock,
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
    ) -> str:
        current = request.app.state.web_config
        payload = build_web_feeds(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )
        return _render_feeds_page(current, payload, auth_token=auth or "")

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
    ) -> str:
        current = request.app.state.web_config
        payload = build_web_eggs(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )
        return _render_eggs_page(current, payload, auth_token=auth or "")

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
    ) -> str:
        current = request.app.state.web_config
        payload = build_web_livestock(
            current.db_path,
            user_id=user_id,
            timezone_name=current.timezone_name,
        )
        return _render_livestock_page(current, payload, auth_token=auth or "")

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
    .nav {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 16px;
    }
    .nav a {
      border: 1px solid #cfc5b4;
      border-radius: 6px;
      padding: 7px 10px;
      background: #fffaf2;
      text-decoration: none;
      color: #245b78;
      font-size: 14px;
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
      a, .nav a {
        color: #88c7ef;
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
        ("/livestock", "Поголовье и стада"),
        ("/eggs", "Яйца"),
        ("/incubation", "Инкубация"),
    )
    rendered = []
    for path, label in links:
        class_attr = ' class="active"' if path == active_path else ""
        current_attr = ' aria-current="page"' if path == active_path else ""
        rendered.append(
            f'<a href="{escape(_link(path, auth_token))}"{class_attr}{current_attr}>{escape(label)}</a>'
        )
    return '<nav class="nav" aria-label="Основные разделы">' + "\n      ".join(rendered) + "</nav>"


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


def _render_livestock_page(config: WebConfig, payload: dict, *, auth_token: str = "") -> str:
    groups = payload.get("bird_groups", [])
    flocks = payload.get("flocks", [])
    feeds = payload.get("feeds") or {}
    bird_groups = feeds.get("bird_groups") or {}
    group_rows = "\n".join(_render_bird_group_row(item) for item in groups)
    if not group_rows:
        group_rows = "<tr><td colspan=\"7\">Поголовье пока не добавлено.</td></tr>"
    flock_rows = "\n".join(_render_livestock_flock_row(item) for item in flocks)
    if not flock_rows:
        flock_rows = "<tr><td colspan=\"6\">Стада пока не созданы.</td></tr>"
    assignment_rows = "\n".join(
        _render_flock_assignment_row(flock, assignment)
        for flock in flocks
        for assignment in flock.get("assignments", [])
    )
    if not assignment_rows:
        assignment_rows = "<tr><td colspan=\"8\">Назначенной готовой смеси пока нет.</td></tr>"
    selected_user = payload.get("selected_user_id")
    selected_user_label = "не выбран" if selected_user is None else str(selected_user)
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
{_page_header("Поголовье и стада", "Read-only просмотр групп птиц, состава стад и назначенной смеси.", auth_token, active_path="/livestock")}

  <section class="summary">
    <div class="metric"><span class="label">Пользователь</span><span class="value">{escape(selected_user_label)}</span></div>
    <div class="metric"><span class="label">Всего птиц</span><span class="value">{escape(str(bird_groups.get("birds_total", 0)))}</span></div>
    <div class="metric"><span class="label">Групп поголовья</span><span class="value">{escape(str(bird_groups.get("total", len(groups))))}</span></div>
    <div class="metric"><span class="label">Стад</span><span class="value">{escape(str(len(flocks)))}</span></div>
    <div class="metric"><span class="label">Несушки</span><span class="value">{escape(str(bird_groups.get("hens", 0)))}</span></div>
    <div class="metric"><span class="label">Цыплята</span><span class="value">{escape(str(bird_groups.get("chicks", 0)))}</span></div>
  </section>

  <h2>Поголовье</h2>
  <table>
    <thead>
      <tr><th>Группа</th><th>Птиц</th><th>Вид</th><th>Тип</th><th>Роль</th><th>Вывод</th><th>Подсадка</th></tr>
    </thead>
    <tbody>{group_rows}</tbody>
  </table>

  <h2>Стада</h2>
  <table>
    <thead>
      <tr><th>Стадо</th><th>Птиц</th><th>Групп</th><th>Состав</th><th>Расход</th><th>Смесь</th></tr>
    </thead>
    <tbody>{flock_rows}</tbody>
  </table>

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

  <h2>Погода</h2>
  <p>{escape(weather_text)}</p>

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
