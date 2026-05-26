from dataclasses import dataclass, field
from datetime import datetime, timezone as datetime_timezone
import logging
import os
from pathlib import Path

from app.version import APP_VERSION


@dataclass(frozen=True)
class AppConfig:
    bot_token: str
    db_path: Path
    log_file: Path
    backup_dir: Path
    admin_ids: frozenset[int]
    environment: str
    log_level: int
    reminder_interval_seconds: int
    min_free_disk_mb: int
    release_version: str
    release_notes: str
    release_notice_enabled: bool
    release_channel: str
    release_importance: str
    github_url: str
    changelog_url: str
    timezone: str = "Europe/Moscow"
    admin_startup_notice_mode: str = "once_per_version"
    release_deployed_at: str = ""
    release_commit: str = ""
    runtime_started_at: datetime = field(default_factory=lambda: datetime.now(datetime_timezone.utc))


def get_project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).resolve().parent.parent


def load_dotenv(project_root: Path) -> None:
    """Load simple KEY=VALUE pairs from .env without external dependencies."""
    environment = os.getenv("ENVIRONMENT", "").strip().lower()
    candidates = []
    if environment:
        candidates.append(project_root / f".env.{environment}")
    candidates.append(project_root / ".env")

    for env_file in candidates:
        if not env_file.exists():
            continue
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def read_bot_token(project_root: Path, *, environment: str) -> str:
    """Read bot token from environment or local token files."""
    env_token = os.getenv("BOT_TOKEN", "").strip()
    if env_token:
        return env_token

    if environment == "prod":
        raise FileNotFoundError(
            "Bot token was not found. Set BOT_TOKEN in the production environment. "
            "Production mode does not read id/id.txt."
        )

    candidates = (
        project_root / "id",
        project_root / "id.txt",
    )
    for token_file in candidates:
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                return token

    raise FileNotFoundError(
        "Bot token was not found. Set BOT_TOKEN. In dev mode only, id/id.txt "
        "is still accepted for legacy local setups."
    )


def load_config() -> AppConfig:
    """Load application config and create runtime directories."""
    root = get_project_root()
    load_dotenv(root)
    environment = os.getenv("ENVIRONMENT", "dev").strip().lower() or "dev"
    data_dir = root / "data"
    logs_dir = root / "logs"
    backups_dir = root / "backups"

    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    backups_dir.mkdir(parents=True, exist_ok=True)

    db_default = data_dir / ("incubator.db" if environment == "prod" else "incubator_dev.db")
    db_path = Path(os.getenv("DATABASE_PATH", str(db_default))).expanduser()
    if not db_path.is_absolute():
        db_path = root / db_path

    log_file = Path(os.getenv("LOG_FILE", str(logs_dir / "bot.log"))).expanduser()
    if not log_file.is_absolute():
        log_file = root / log_file

    backup_dir = Path(os.getenv("BACKUP_DIR", str(backups_dir))).expanduser()
    if not backup_dir.is_absolute():
        backup_dir = root / backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)

    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    release_notice_enabled = _parse_bool_env(
        "RELEASE_NOTICE_ENABLED",
        default=False,
    )
    release_version = os.getenv("RELEASE_VERSION", os.getenv("APP_VERSION", "")).strip()
    if not release_version and environment == "prod":
        release_version = APP_VERSION
    release_importance = os.getenv("RELEASE_IMPORTANCE", "minor").strip().lower() or "minor"

    default_github_url = "https://github.com/NikitaZhilin/incubator-feed"
    default_changelog_url = "https://github.com/NikitaZhilin/incubator-feed/blob/main/docs/CHANGELOG.md"

    return AppConfig(
        bot_token=read_bot_token(root, environment=environment),
        db_path=db_path,
        log_file=log_file,
        backup_dir=backup_dir,
        admin_ids=frozenset(admin_ids),
        environment=environment,
        log_level=int(log_level),
        reminder_interval_seconds=_parse_int_env("REMINDER_INTERVAL_SECONDS", 60, minimum=5),
        min_free_disk_mb=_parse_int_env("MIN_FREE_DISK_MB", 512, minimum=1),
        release_version=release_version,
        release_notes=os.getenv("RELEASE_NOTES", "").strip(),
        release_notice_enabled=release_notice_enabled,
        admin_startup_notice_mode=_parse_admin_startup_notice_mode(
            os.getenv("ADMIN_STARTUP_NOTICE_MODE", "once_per_version")
        ),
        release_channel=os.getenv("RELEASE_CHANNEL", "beta").strip() or "beta",
        release_importance=release_importance,
        github_url=os.getenv("GITHUB_URL", default_github_url).strip() or default_github_url,
        changelog_url=os.getenv("CHANGELOG_URL", default_changelog_url).strip()
        or default_changelog_url,
        timezone=os.getenv("BOT_TIMEZONE", "Europe/Moscow"),
        release_deployed_at=os.getenv("RELEASE_DEPLOYED_AT", "").strip(),
        release_commit=os.getenv("RELEASE_COMMIT", "").strip(),
    )


def should_send_release_notice(config: AppConfig) -> bool:
    if not config.release_notice_enabled or not config.release_version:
        return False
    return config.release_importance in {"medium", "major", "critical"}


def should_send_admin_startup_notice(config: AppConfig) -> bool:
    return bool(config.admin_ids) and config.admin_startup_notice_mode != "off"


def _parse_admin_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for item in raw.replace(";", ",").split(","):
        value = item.strip()
        if not value:
            continue
        ids.add(int(value))
    return ids


def _parse_int_env(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < minimum:
        return minimum
    return value


def _parse_bool_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _parse_admin_startup_notice_mode(raw: str) -> str:
    value = raw.strip().lower()
    if value in {"off", "always", "once_per_version"}:
        return value
    return "once_per_version"
