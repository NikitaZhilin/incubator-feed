from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from app.config import get_project_root, load_dotenv
from app.version import APP_VERSION


@dataclass(frozen=True)
class WebConfig:
    enabled: bool
    host: str
    port: int
    admin_token: str
    db_path: Path
    environment: str
    release_version: str
    release_channel: str
    release_deployed_at: str
    release_commit: str
    github_url: str
    changelog_url: str
    timezone_name: str = "Europe/Moscow"
    link_token: str = ""


def load_web_config() -> WebConfig:
    root = get_project_root()
    load_dotenv(root)
    environment = os.getenv("ENVIRONMENT", "dev").strip().lower() or "dev"
    data_dir = root / "data"
    db_default = data_dir / ("incubator.db" if environment == "prod" else "incubator_dev.db")
    db_path = Path(os.getenv("DATABASE_PATH", str(db_default))).expanduser()
    if not db_path.is_absolute():
        db_path = root / db_path

    default_github_url = "https://github.com/NikitaZhilin/incubator-feed"
    default_changelog_url = "https://github.com/NikitaZhilin/incubator-feed/blob/main/docs/CHANGELOG.md"
    release_version = os.getenv("RELEASE_VERSION", os.getenv("APP_VERSION", "")).strip()
    if not release_version and environment == "prod":
        release_version = APP_VERSION

    return WebConfig(
        enabled=_parse_bool("WEB_ENABLED", default=False),
        host=os.getenv("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_parse_int("WEB_PORT", 8080, minimum=1),
        admin_token=os.getenv("WEB_ADMIN_TOKEN", "").strip(),
        db_path=db_path,
        environment=environment,
        release_version=release_version or APP_VERSION,
        release_channel=os.getenv("RELEASE_CHANNEL", "beta").strip() or "beta",
        release_deployed_at=os.getenv("RELEASE_DEPLOYED_AT", "").strip(),
        release_commit=os.getenv("RELEASE_COMMIT", "").strip(),
        github_url=os.getenv("GITHUB_URL", default_github_url).strip() or default_github_url,
        changelog_url=os.getenv("CHANGELOG_URL", default_changelog_url).strip()
        or default_changelog_url,
        timezone_name=os.getenv("BOT_TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow",
        link_token=os.getenv("WEB_LINK_TOKEN", "").strip(),
    )


def _parse_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _parse_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < minimum:
        return minimum
    return value
