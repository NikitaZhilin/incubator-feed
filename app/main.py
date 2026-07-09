import asyncio
import logging
from logging.handlers import RotatingFileHandler
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramServerError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo

from app.config import load_config, should_send_admin_startup_notice, should_send_release_notice
from app.handlers import register_handlers
from app.middlewares.callbacks import StaleCallbackMiddleware
from app.middlewares.users import UserTrackingMiddleware
from app.services.incubation import IncubationService
from app.services.eggs import EggService
from app.services.feeds import FeedService
from app.services.heartbeats import HeartbeatLoop
from app.services.stock import StockService
from app.services.admin import AdminService
from app.services.poultry_advisor import PoultryAdvisorService
from app.services.release_notifications import AdminStartupNotificationService, ReleaseNotificationService
from app.services.reminders import ReminderRunner
from app.services.weather import OpenMeteoWeatherClient
from app.storage.database import Database
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.heartbeats import HeartbeatRepository
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.users import UserRepository
from app.storage.repositories.stock import StockRepository
from app.utils.single_instance import SingleInstanceLock
from app.version import APP_VERSION


POLLING_RETRY_INITIAL_SECONDS = 5
POLLING_RETRY_MAX_SECONDS = 60
RETRIABLE_POLLING_EXCEPTIONS = (TelegramNetworkError, TelegramServerError)


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
        heartbeats = HeartbeatRepository(database)
        heartbeat_version = config.release_version or APP_VERSION

        incubation_service = IncubationService(
            BatchRepository(database),
            ReminderRepository(database),
            users,
            analytics,
        )
        feed_repository = FeedRepository(database)
        feed_service = FeedService(feed_repository, analytics)
        egg_service = EggService(
            EggRepository(database),
            feed_repository,
            OpenMeteoWeatherClient(),
            timezone_name=config.timezone,
        )
        stock_service = StockService(StockRepository(database), feed_repository, analytics)
        poultry_advisor_service = PoultryAdvisorService(
            incubation_service=incubation_service,
            feed_service=feed_service,
            egg_service=egg_service,
            stock_service=stock_service,
            timezone_name=config.timezone,
        )
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
            session=build_bot_session(config),
        )
        await configure_telegram_menu_button(bot, config)
        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher["incubation_service"] = incubation_service
        dispatcher["feed_service"] = feed_service
        dispatcher["egg_service"] = egg_service
        dispatcher["stock_service"] = stock_service
        dispatcher["poultry_advisor_service"] = poultry_advisor_service
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
            egg_service=egg_service,
            stock_service=stock_service,
            poultry_advisor_service=poultry_advisor_service,
            users=users,
            notifications=notifications,
            heartbeats=heartbeats,
            heartbeat_version=heartbeat_version,
            started_at=config.runtime_started_at,
            timezone=config.timezone,
            interval_seconds=config.reminder_interval_seconds,
        )
        polling_heartbeat = HeartbeatLoop(
            heartbeats=heartbeats,
            service_name="polling_bot",
            version=heartbeat_version,
            started_at=config.runtime_started_at,
            interval_seconds=30,
            metadata={
                "environment": config.environment,
                "handlers_registered": True,
            },
        )
        polling_heartbeat.start()
        reminder_runner.start()
        if should_send_release_notice(config):
            try:
                result = await ReleaseNotificationService(
                    bot=bot,
                    users=users,
                    notifications=notifications,
                ).send_release_notice(
                    version=config.release_version,
                    notes=config.release_notes,
                    importance=config.release_importance,
                )
                logging.info(
                    "Release notice completed: sent=%s skipped=%s failed=%s",
                    result.sent,
                    result.skipped,
                    result.failed,
                )
            except Exception:
                logging.exception("Release notice failed")
        if config.admin_startup_notice_mode == "off":
            logging.info("Admin startup notice skipped: ADMIN_STARTUP_NOTICE_MODE=off")
        elif not config.admin_ids:
            logging.warning("Admin startup notice skipped: ADMIN_IDS is empty")
        else:
            if should_send_admin_startup_notice(config):
                try:
                    result = await AdminStartupNotificationService(
                        bot=bot,
                        admin_ids=config.admin_ids,
                        notifications=notifications,
                    ).send_startup_notice(
                        version=config.release_version,
                        started_at=config.runtime_started_at,
                        timezone_name=config.timezone,
                        mode=config.admin_startup_notice_mode,
                        deployment_id=(
                            config.release_commit
                            or config.release_deployed_at
                            or config.release_version
                        ),
                        commit=config.release_commit,
                    )
                    logging.info(
                        "Admin startup notice completed: sent=%s skipped=%s failed=%s",
                        result.sent,
                        result.skipped,
                        result.failed,
                    )
                except Exception:
                    logging.exception("Admin startup notice failed")
        try:
            polling_retry_delay = POLLING_RETRY_INITIAL_SECONDS
            while True:
                try:
                    await dispatcher.start_polling(bot)
                    break
                except RETRIABLE_POLLING_EXCEPTIONS as exc:
                    logging.warning(
                        "Polling temporarily failed; retrying in %s seconds: %s",
                        polling_retry_delay,
                        exc,
                    )
                    await asyncio.sleep(polling_retry_delay)
                    polling_retry_delay = min(
                        polling_retry_delay * 2,
                        POLLING_RETRY_MAX_SECONDS,
                    )
                except Exception as exc:
                    analytics.log_critical("polling", exc)
                    await notify_admins_about_failure(bot, config.admin_ids, exc)
                    raise
        finally:
            await polling_heartbeat.stop()
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


def build_bot_session(config) -> AiohttpSession:
    if config.telegram_proxy_url:
        logging.info("Telegram proxy is configured")
        return AiohttpSession(proxy=config.telegram_proxy_url)
    return AiohttpSession()


async def configure_telegram_menu_button(bot: Bot, config) -> None:
    try:
        if config.miniapp_open_url:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="АПП",
                    web_app=WebAppInfo(url=config.miniapp_open_url),
                )
            )
            logging.info("Telegram menu button set to Mini App")
            return
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logging.info("Telegram menu button set to commands")
    except Exception:
        logging.exception("Failed to configure Telegram menu button")


if __name__ == "__main__":
    asyncio.run(main())
