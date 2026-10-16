"""Care calendar: parasites, worming, litter, disinfection — with «Сделал» and the next date."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.storage.database import Database


# code, title, every N days, hint shown with the reminder
DEFAULT_CARE_TASKS = (
    (
        "parasites",
        "Осмотр и обработка от клещей и пухоедов",
        30,
        "Осмотрите перья под крыльями и у клоаки, щели насестов. Обрабатывайте препаратом для птиц по его инструкции.",
    ),
    (
        "deworming",
        "Глистогонное",
        90,
        "Препарат и дозу подберите по инструкции или с ветеринаром; на время курса уточните срок, когда нельзя есть яйца.",
    ),
    (
        "litter",
        "Смена подстилки",
        14,
        "Сырая подстилка — аммиак, болезни лап и грязные яйца. Мокрые места у поилок меняйте чаще.",
    ),
    (
        "disinfection",
        "Чистка и дезинфекция курятника",
        90,
        "Уберите подстилку, отмойте насесты и гнёзда, обработайте средством, разрешённым при птице, проветрите и просушите.",
    ),
)
HINTS = {code: hint for code, _, _, hint in DEFAULT_CARE_TASKS}
REMIND_AGAIN_DAYS = 3
MAX_INTERVAL_DAYS = 365


@dataclass(frozen=True)
class CareTask:
    id: int
    user_id: int
    code: str
    title: str
    interval_days: int
    next_due: date
    last_done: date | None
    reminded_on: date | None
    is_active: bool

    @property
    def hint(self) -> str:
        return HINTS.get(self.code, "")

    def days_until(self, today: date) -> int:
        return (self.next_due - today).days


def _task(row) -> CareTask:
    return CareTask(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        code=str(row["code"]),
        title=str(row["title"]),
        interval_days=int(row["interval_days"]),
        next_due=date.fromisoformat(row["next_due"]),
        last_done=date.fromisoformat(row["last_done"]) if row["last_done"] else None,
        reminded_on=date.fromisoformat(row["reminded_on"]) if row["reminded_on"] else None,
        is_active=bool(row["is_active"]),
    )


def when_text(task: CareTask, today: date) -> str:
    days = task.days_until(today)
    if days < 0:
        return f"просрочено на {-days} дн."
    if days == 0:
        return "сегодня"
    if days == 1:
        return "завтра"
    return f"через {days} дн. ({task.next_due.strftime('%d.%m')})"


class CareService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def ensure_defaults(self, user_id: int, *, today: date) -> None:
        """First use: the standard tasks, due today, so the owner sets the real dates with one tap."""
        with self.database.connect() as connection:
            for code, title, interval, _ in DEFAULT_CARE_TASKS:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO care_tasks (user_id, code, title, interval_days, next_due)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, code, title, interval, today.isoformat()),
                )

    def list(self, user_id: int, *, today: date) -> list[CareTask]:
        self.ensure_defaults(user_id, today=today)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM care_tasks WHERE user_id = ? ORDER BY is_active DESC, next_due, id", (user_id,)
            ).fetchall()
        return [_task(row) for row in rows]

    def get(self, user_id: int, task_id: int) -> CareTask | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM care_tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
            ).fetchone()
        return _task(row) if row else None

    def _update(self, user_id: int, task_id: int, **fields) -> CareTask | None:
        if not fields:
            return self.get(user_id, task_id)
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = [value.isoformat() if isinstance(value, date) else value for value in fields.values()]
        with self.database.connect() as connection:
            connection.execute(
                f"UPDATE care_tasks SET {assignments} WHERE id = ? AND user_id = ?", (*values, task_id, user_id)
            )
        return self.get(user_id, task_id)

    def mark_done(self, user_id: int, task_id: int, *, today: date) -> CareTask | None:
        task = self.get(user_id, task_id)
        if task is None:
            return None
        return self._update(
            user_id, task_id, last_done=today, next_due=today + timedelta(days=task.interval_days), reminded_on=None
        )

    def snooze(self, user_id: int, task_id: int, *, today: date, days: int = REMIND_AGAIN_DAYS) -> CareTask | None:
        return self._update(user_id, task_id, next_due=today + timedelta(days=days), reminded_on=None)

    def set_interval(self, user_id: int, task_id: int, days: int) -> CareTask | None:
        if not 1 <= days <= MAX_INTERVAL_DAYS:
            raise ValueError(f"Срок — от 1 до {MAX_INTERVAL_DAYS} дней.")
        task = self.get(user_id, task_id)
        if task is None:
            return None
        base = task.last_done
        fields = {"interval_days": days}
        if base is not None:
            fields["next_due"] = base + timedelta(days=days)
        return self._update(user_id, task_id, **fields)

    def toggle(self, user_id: int, task_id: int, *, today: date) -> CareTask | None:
        task = self.get(user_id, task_id)
        if task is None:
            return None
        if task.is_active:
            return self._update(user_id, task_id, is_active=0)
        next_due = task.next_due if task.next_due >= today else today
        return self._update(user_id, task_id, is_active=1, next_due=next_due, reminded_on=None)

    def due_for_reminder(self, user_id: int, *, today: date) -> list[CareTask]:
        """Due today or overdue; an ignored reminder repeats every few days, not daily."""
        return [
            task
            for task in self.list(user_id, today=today)
            if task.is_active
            and task.next_due <= today
            and (task.reminded_on is None or (today - task.reminded_on).days >= REMIND_AGAIN_DAYS)
        ]

    def mark_reminded(self, user_id: int, task_ids: list[int], *, today: date) -> None:
        for task_id in task_ids:
            self._update(user_id, task_id, reminded_on=today)

    def due_soon(self, user_id: int, *, today: date, days: int = 3) -> list[CareTask]:
        return [
            task for task in self.list(user_id, today=today) if task.is_active and task.days_until(today) <= days
        ]


def format_care_list(tasks: list[CareTask], today: date) -> str:
    lines = ["🗓 Уход за птицей", ""]
    for task in tasks:
        if not task.is_active:
            lines.append(f"⏸ {task.title} — выключено")
            continue
        mark = "❗" if task.days_until(today) <= 0 else "•"
        last = f"; последний раз {task.last_done.strftime('%d.%m')}" if task.last_done else ""
        lines.append(f"{mark} {task.title}: {when_text(task, today)} (каждые {task.interval_days} дн.{last})")
    lines.extend(
        [
            "",
            "Нажмите «✅», когда сделали, — следующий раз бот напомнит через заданный срок. "
            "Если делали недавно, тоже нажмите «✅», чтобы отсчёт пошёл от сегодня.",
        ]
    )
    return "\n".join(lines)


def format_care_reminder(tasks: list[CareTask], today: date) -> str:
    lines = ["🗓 Пора по уходу:", ""]
    for task in tasks:
        lines.append(f"❗ {task.title} — {when_text(task, today)}.")
        if task.hint:
            lines.append(f"   {task.hint}")
    lines.extend(["", "Сделали — нажмите «✅». Следующее напоминание придёт через заданный срок."])
    if any(task.last_done is None for task in tasks):
        lines.append(
            "Это первое напоминание календаря: если делали недавно, тоже нажмите «✅» — отсчёт пойдёт от сегодня. "
            "Сроки меняются в «Птицевод → 🗓 Уход за птицей → ⚙️»."
        )
    return "\n".join(lines)
