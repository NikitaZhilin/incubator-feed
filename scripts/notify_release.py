from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import load_config
from app.services.release_notifications import ReleaseNotificationService
from app.storage.database import Database
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.users import UserRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send a deduplicated release notice to active bot users."
    )
    parser.add_argument(
        "--version",
        default=os.getenv("RELEASE_VERSION", "").strip(),
        help="Numeric beta release version, for example 0.1.42-beta.",
    )
    parser.add_argument(
        "--notes",
        default=os.getenv("RELEASE_NOTES", "").strip(),
        help="Release notes. Use new lines or semicolons for several items.",
    )
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    version = str(args.version).strip()
    if not version:
        raise SystemExit("Release version is required. Pass --version or RELEASE_VERSION.")

    config = load_config()
    database = Database(config.db_path)
    database.initialize()
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        service = ReleaseNotificationService(
            bot=bot,
            users=UserRepository(database),
            notifications=NotificationRepository(database),
        )
        result = await service.send_release_notice(
            version=version,
            notes=str(args.notes or ""),
        )
    finally:
        await bot.session.close()

    print(
        "Release notice completed: "
        f"sent={result.sent}, skipped={result.skipped}, failed={result.failed}"
    )


if __name__ == "__main__":
    asyncio.run(async_main())
