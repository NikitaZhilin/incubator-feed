from datetime import date, datetime


DATE_FORMAT_HINT = "ДД.ММ.ГГГГ или ГГГГ-ММ-ДД"


def parse_user_date(value: str) -> date:
    cleaned = value.strip().lower()
    if cleaned in {"сегодня", "today"}:
        return date.today()

    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Дата должна быть в формате {DATE_FORMAT_HINT}")
