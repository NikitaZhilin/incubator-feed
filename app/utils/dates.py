from datetime import date, datetime, timedelta, timezone
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DATE_FORMAT_HINT = "ДД.ММ.ГГГГ или ГГГГ-ММ-ДД"
MAX_INCUBATION_START_OFFSET_DAYS = 60


def local_today(timezone_name: str | None = None) -> date:
    """Today in the farm's time zone (BOT_TIMEZONE), not the server's UTC date."""
    name = timezone_name or os.getenv("BOT_TIMEZONE", "Europe/Moscow")
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("Europe/Moscow")
    return datetime.now(timezone.utc).astimezone(zone).date()


def validate_incubation_start_date(start_date: date, *, today: date | None = None) -> None:
    """Catch typos in the year: a batch is set at most ~2 months back or ahead."""
    current = today or local_today()
    limit = timedelta(days=MAX_INCUBATION_START_OFFSET_DAYS)
    if start_date < current - limit:
        raise ValueError(
            f"Дата закладки {start_date.strftime('%d.%m.%Y')} больше чем на "
            f"{MAX_INCUBATION_START_OFFSET_DAYS} дней в прошлом. Проверьте год."
        )
    if start_date > current + limit:
        raise ValueError(
            f"Дата закладки {start_date.strftime('%d.%m.%Y')} больше чем на "
            f"{MAX_INCUBATION_START_OFFSET_DAYS} дней в будущем. Проверьте год."
        )


def parse_user_date(value: str) -> date:
    cleaned = value.strip().lower()
    if cleaned in {"сегодня", "today"}:
        return local_today()

    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Дата должна быть в формате {DATE_FORMAT_HINT}")
