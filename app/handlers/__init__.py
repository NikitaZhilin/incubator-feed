from aiogram import Dispatcher

from app.handlers.common import router as common_router
from app.handlers.admin import router as admin_router
from app.handlers.feeds import router as feeds_router
from app.handlers.incubation import router as incubation_router
from app.handlers.settings import router as settings_router


def register_handlers(dispatcher: Dispatcher) -> None:
    dispatcher.include_router(common_router)
    dispatcher.include_router(settings_router)
    dispatcher.include_router(admin_router)
    dispatcher.include_router(feeds_router)
    dispatcher.include_router(incubation_router)
