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
from app.services.eggs import EggService
from app.services.feeds import FeedService
from app.services.stock import StockService
from app.services.incubation import IncubationService
from app.services.poultry_advisor import PoultryAdvisorService
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.users import UserRepository
from app.storage.repositories.stock import StockRepository


def main() -> None:
    config = load_config()
    database = Database(config.db_path)
    database.initialize()
    users = UserRepository(database)
    analytics = AnalyticsRepository(database)
    notifications = NotificationRepository(database)
    dispatcher = Dispatcher(storage=MemoryStorage())
    incubation_service = IncubationService(
        BatchRepository(database),
        ReminderRepository(database),
        users,
        analytics,
    )
    dispatcher["incubation_service"] = incubation_service
    feed_repository = FeedRepository(database)
    feed_service = FeedService(feed_repository, analytics)
    egg_service = EggService(EggRepository(database), feed_repository, timezone_name=config.timezone)
    stock_service = StockService(StockRepository(database), feed_repository, analytics)
    dispatcher["feed_service"] = feed_service
    dispatcher["egg_service"] = egg_service
    dispatcher["stock_service"] = stock_service
    dispatcher["poultry_advisor_service"] = PoultryAdvisorService(
        incubation_service=incubation_service,
        feed_service=feed_service,
        egg_service=egg_service,
        stock_service=stock_service,
        timezone_name=config.timezone,
    )
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
