from __future__ import annotations

from html import escape
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.services.status_probe import build_status_report
from app.web.config import WebConfig, load_web_config


def create_app(config: WebConfig | None = None) -> FastAPI:
    web_config = config or load_web_config()
    app = FastAPI(title="tg_bot_inkubator web", version=web_config.release_version)
    app.state.web_config = web_config

    def require_admin(
        authorization: str | None = Header(default=None),
        x_web_token: str | None = Header(default=None),
    ) -> None:
        expected = app.state.web_config.admin_token
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="WEB_ADMIN_TOKEN is not configured.",
            )
        provided = _extract_token(authorization, x_web_token)
        if not provided or not secrets.compare_digest(provided, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/status", dependencies=[Depends(require_admin)])
    def status_report() -> dict:
        return build_status_report(app.state.web_config.db_path)

    @app.get("/version", dependencies=[Depends(require_admin)])
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

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def index(request: Request) -> str:
        current = request.app.state.web_config
        report = build_status_report(current.db_path)
        return _render_index(current, report)

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


def _render_index(config: WebConfig, report: dict) -> str:
    status_value = escape(str(report.get("status", "unknown")))
    db_status = escape(str(report.get("db", {}).get("status", "unknown")))
    users_total = escape(str(report.get("users", {}).get("total", 0)))
    critical_total = escape(str(report.get("errors", {}).get("critical_total", 0)))
    heartbeat_rows = "\n".join(_render_heartbeat_row(item) for item in report.get("heartbeats", []))
    if not heartbeat_rows:
        heartbeat_rows = "<tr><td colspan=\"5\">Heartbeat пока не получен.</td></tr>"

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
