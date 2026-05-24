from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import load_config
from app.handlers import register_handlers
from app.services.admin import AdminService
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.users import UserRepository


def main() -> None:
    config = load_config()
    database = Database(config.db_path)
    database.initialize()
    users = UserRepository(database)
    analytics = AnalyticsRepository(database)
    notifications = NotificationRepository(database)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["incubation_service"] = IncubationService(
        BatchRepository(database),
        ReminderRepository(database),
        users,
        analytics,
    )
    dispatcher["feed_service"] = FeedService(FeedRepository(database), analytics)
    dispatcher["admin_service"] = AdminService(
        database=database,
        users=users,
        notifications=notifications,
        analytics=analytics,
        config=config,
    )
    dispatcher["analytics"] = analytics
    dispatcher["config"] = config
    register_handlers(dispatcher)
    Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    print("Smoke start OK: config, migrations, services and handlers initialized without polling.")


if __name__ == "__main__":
    main()
