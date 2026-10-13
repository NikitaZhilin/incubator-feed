from aiogram import Dispatcher

from app.handlers.common import router as common_router
from app.handlers.admin import router as admin_router
from app.handlers.eggs import router as eggs_router
from app.handlers.errors import on_handler_error
from app.handlers.fallback import router as fallback_router
from app.handlers.feeds import router as feeds_router
from app.handlers.incubation import router as incubation_router
from app.handlers.poultry_advisor import router as poultry_advisor_router
from app.handlers.settings import router as settings_router


def register_handlers(dispatcher: Dispatcher) -> None:
    dispatcher.errors.register(on_handler_error)
    dispatcher.include_router(common_router)
    dispatcher.include_router(settings_router)
    dispatcher.include_router(admin_router)
    dispatcher.include_router(poultry_advisor_router)
    dispatcher.include_router(eggs_router)
    dispatcher.include_router(feeds_router)
    dispatcher.include_router(incubation_router)
    # Must stay last: answers buttons that no other handler accepted.
    dispatcher.include_router(fallback_router)
