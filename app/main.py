import asyncio
import logging
from logging.handlers import RotatingFileHandler
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import load_config
from app.handlers import register_handlers
from app.middlewares.callbacks import StaleCallbackMiddleware
from app.middlewares.users import UserTrackingMiddleware
from app.services.incubation import IncubationService
from app.services.feeds import FeedService
from app.services.stock import StockService
from app.services.admin import AdminService
from app.services.release_notifications import ReleaseNotificationService
from app.services.reminders import ReminderRunner
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.users import UserRepository
from app.storage.repositories.stock import StockRepository
from app.utils.single_instance import SingleInstanceLock


def setup_logging(log_file, level: int) -> None:
    handlers: list[logging.Handler] = []
    try:
        handlers.append(
            RotatingFileHandler(
                log_file,
                maxBytes=2_000_000,
                backupCount=5,
                encoding="utf-8",
            )
        )
    except OSError:
        fallback_log = log_file.parent.parent / "bot.log"
        try:
            handlers.append(
                RotatingFileHandler(
                    fallback_log,
                    maxBytes=2_000_000,
                    backupCount=5,
                    encoding="utf-8",
                )
            )
        except OSError:
            pass
    handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


async def main() -> None:
    config = load_config()
    setup_logging(config.log_file, config.log_level)
    runtime_root = config.db_path.parent.parent
    lock_path = runtime_root / "bot.lock"

    try:
        lock = SingleInstanceLock(lock_path)
        lock.__enter__()
    except RuntimeError as exc:
        logging.error("%s", exc)
        return

    try:
        database = Database(config.db_path)
        database.initialize()
        users = UserRepository(database)
        analytics = AnalyticsRepository(database)
        notifications = NotificationRepository(database)

        incubation_service = IncubationService(
            BatchRepository(database),
            ReminderRepository(database),
            users,
            analytics,
        )
        feed_repository = FeedRepository(database)
        feed_service = FeedService(feed_repository, analytics)
        stock_service = StockService(StockRepository(database), feed_repository, analytics)
        admin_service = AdminService(
            database=database,
            users=users,
            notifications=notifications,
            analytics=analytics,
            config=config,
        )

        bot = Bot(
            token=config.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher["incubation_service"] = incubation_service
        dispatcher["feed_service"] = feed_service
        dispatcher["stock_service"] = stock_service
        dispatcher["admin_service"] = admin_service
        dispatcher["analytics"] = analytics
        dispatcher["config"] = config
        dispatcher.message.middleware(UserTrackingMiddleware())
        dispatcher.callback_query.middleware(StaleCallbackMiddleware())
        dispatcher.callback_query.middleware(UserTrackingMiddleware())
        register_handlers(dispatcher)

        reminder_runner = ReminderRunner(
            bot=bot,
            incubation_service=incubation_service,
            feed_service=feed_service,
            notifications=notifications,
            timezone=config.timezone,
            interval_seconds=config.reminder_interval_seconds,
        )
        reminder_runner.start()
        if config.release_notice_enabled and config.release_version:
            try:
                result = await ReleaseNotificationService(
                    bot=bot,
                    users=users,
                    notifications=notifications,
                ).send_release_notice(
                    version=config.release_version,
                    notes=config.release_notes,
                )
                logging.info(
                    "Release notice completed: sent=%s skipped=%s failed=%s",
                    result.sent,
                    result.skipped,
                    result.failed,
                )
            except Exception:
                logging.exception("Release notice failed")
        try:
            try:
                await dispatcher.start_polling(bot)
            except Exception as exc:
                analytics.log_critical("polling", exc)
                await notify_admins_about_failure(bot, config.admin_ids, exc)
                raise
        finally:
            await reminder_runner.stop()
            await bot.session.close()
    finally:
        lock.__exit__(None, None, None)


async def notify_admins_about_failure(bot: Bot, admin_ids: frozenset[int], exc: BaseException) -> None:
    if not admin_ids:
        return
    message = (
        "Критическая ошибка бота.\n\n"
        f"{type(exc).__name__}: {exc}\n\n"
        f"{traceback.format_exc()[-2500:]}"
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, message)
        except Exception:
            logging.exception("Failed to notify admin %s about failure", admin_id)


if __name__ == "__main__":
    asyncio.run(main())
