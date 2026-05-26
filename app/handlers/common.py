from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import AppConfig
from app.keyboards.menu import main_menu_keyboard
from app.services.incubation import IncubationService
from app.version import APP_VERSION


router = Router()


FAQ_SECTIONS = {
    "main": {
        "title": "❓ FAQ: главное меню",
        "back": ("🏠 Главное меню", "menu:home"),
        "text": (
            "Главное меню открывает основные разделы бота.\n\n"
            "- Корма: склад, смесь, поголовье, стада и расчеты расхода.\n"
            "- Инкубация: партии, календарь работ, режимы и напоминания.\n"
            "- Яйца: ежедневный сбор, прогноз, исключения несушек и погода.\n"
            "- Настройки: хозяйство, уведомления, версия и разделы бота."
        ),
    },
    "incubation": {
        "title": "❓ FAQ: инкубация",
        "back": ("⬅️ К инкубации", "menu:incubation"),
        "text": (
            "Раздел нужен для ведения партий яиц в инкубаторе.\n\n"
            "- Добавить партию: вид птицы, количество яиц, дата закладки и название.\n"
            "- Активные партии: текущий день инкубации и ближайшие действия.\n"
            "- План на сегодня и календарь: что делать по дням.\n"
            "- Завершить вывод: записать количество выведенных птенцов.\n\n"
            "Если партия уже закончилась, ее можно вернуть в активные из истории."
        ),
    },
    "feeds": {
        "title": "❓ FAQ: корма",
        "back": ("⬅️ К кормам", "feeds:menu"),
        "text": (
            "Раздел объединяет склад, смесь, поголовье, стада и расчеты.\n\n"
            "- Добавить корм: добавляет покупку на склад.\n"
            "- Смесь: считает, сколько замесов можно сделать из ингредиентов.\n"
            "- Склад: хранит ингредиенты, готовую смесь и историю операций.\n"
            "- Поголовье и стада: группы птиц и стада, которые едят одну смесь.\n"
            "- Расчеты: расход по стадам и ориентировочные даты закупок."
        ),
    },
    "stock": {
        "title": "❓ FAQ: склад",
        "back": ("⬅️ К складу", "stock:menu"),
        "text": (
            "Склад хранит фактические позиции: ингредиенты, готовую смесь и готовые корма.\n\n"
            "- Добавить покупку: внести новое поступление.\n"
            "- Сделать замес: списать ингредиенты и добавить готовую смесь.\n"
            "- Задать фактический остаток: исправить расчет, если реальный остаток отличается.\n"
            "- История: показывает покупки, списания и замесы."
        ),
    },
    "mix": {
        "title": "❓ FAQ: смесь",
        "back": ("⬅️ К смеси", "stock:mix"),
        "text": (
            "Смесь считается по текущим остаткам склада.\n\n"
            "- Бот выбирает доступную зерновую основу: пшеница или зерносмесь.\n"
            "- Кнопки расчета не списывают склад, а только показывают план.\n"
            "- В чеклисте замеса ингредиенты показываются в частях: 1 часть = 1 литровая кружка.\n"
            "- Склад обновляется только после финальной кнопки `Замес готов, обновить склад`."
        ),
    },
    "livestock": {
        "title": "❓ FAQ: поголовье и стада",
        "back": ("⬅️ Поголовье и стада", "feeds:livestock"),
        "text": (
            "Здесь два разных уровня учета.\n\n"
            "Поголовье - это отдельные группы птиц. Сюда добавляйте то, из чего состоит хозяйство:\n"
            "- несушки: взрослые куры, которые несут яйца;\n"
            "- петухи: взрослые петухи;\n"
            "- цыплята: молодняк с датой вывода и датой подсадки;\n"
            "- смешанная взрослая группа: если пока не хотите делить кур и петухов.\n\n"
            "Стада - это наборы групп поголовья, которые едят одну готовую смесь. "
            "Например, стадо `Основное` может состоять из несушек, петухов и подсаженных цыплят.\n\n"
            "Порядок работы: сначала создайте поголовье, затем создайте стадо, добавьте в него группы и назначьте смесь."
        ),
    },
    "bird_groups": {
        "title": "❓ FAQ: поголовье",
        "back": ("⬅️ К поголовью", "feeds:groups"),
        "text": (
            "В этом разделе добавляются именно группы птиц, а не корм и не стадо.\n\n"
            "Что сюда добавлять:\n"
            "- `Куры/несушки` - взрослые куры, которые участвуют в расчете яиц;\n"
            "- `Петухи` - взрослые петухи, они учитываются в расходе корма, но не в яйцах;\n"
            "- `Цыплята` - молодняк, для них бот спросит дату вывода и дату подсадки;\n"
            "- `Смешанная взрослая группа` - временный вариант, если птицу пока не разделили.\n\n"
            "После создания группы зайдите в `Стада` и добавьте эту группу в нужное стадо. "
            "Сами по себе группы нужны для учета состава, а расход корма удобнее считать через стадо."
        ),
    },
    "flocks": {
        "title": "❓ FAQ: стада",
        "back": ("⬅️ К стадам", "feeds:flocks"),
        "text": (
            "Стадо - это не отдельная птица, а объединение групп поголовья, которые едят вместе.\n\n"
            "Что сюда добавлять:\n"
            "- создайте стадо, например `Основное`;\n"
            "- добавьте в него группы из раздела `Поголовье`: несушек, петухов, цыплят после подсадки;\n"
            "- назначьте стаду готовую `Смесь для кур` со склада.\n\n"
            "Зачем это нужно: бот считает, сколько это стадо съедает в день, на сколько хватит готовой смеси "
            "и когда нужно сделать новый замес или докупить ингредиенты."
        ),
    },
    "flock_card": {
        "title": "❓ FAQ: карточка стада",
        "back": ("⬅️ К стадам", "feeds:flocks"),
        "text": (
            "Карточка стада показывает, что входит в стадо и чем оно кормится.\n\n"
            "- `Изменить состав` - добавить или убрать группы поголовья из стада.\n"
            "- `Назначить смесь` - выбрать готовую смесь со склада. Для основного стада это обычно `Смесь для кур`.\n"
            "- `Архивировать` - убрать стадо из активных расчетов, если оно больше не используется.\n\n"
            "Если расчеты кормов пустые, обычно нужно проверить два пункта: у стада есть состав и стаду назначена смесь."
        ),
    },
    "feed_card": {
        "title": "❓ FAQ: карточка корма",
        "back": ("⬅️ К кормам", "feeds:menu"),
        "text": (
            "Карточка старого корма нужна для ручного учета отдельной позиции.\n\n"
            "- Пополнить и списать меняют остаток этой позиции.\n"
            "- Редактировать меняет название, нормы и привязку.\n"
            "- Для новых закупок и ингредиентов лучше использовать `Склад`."
        ),
    },
    "feed_stats": {
        "title": "❓ FAQ: расчеты кормов",
        "back": ("⬅️ К расчетам", "feeds:stats"),
        "text": (
            "Расчеты кормов смотрят на стада, назначенную смесь и склад.\n\n"
            "- Показывается примерный расход кг/день по стаду.\n"
            "- Готовая смесь на складе считается отдельно от ингредиентов.\n"
            "- Ингредиенты показывают, сколько еще замесов можно сделать.\n"
            "- Даты закупок ориентировочные и зависят от введенных остатков."
        ),
    },
    "eggs": {
        "title": "❓ FAQ: яйца",
        "back": ("⬅️ К яйцам", "eggs:menu"),
        "text": (
            "Раздел ведет ежедневный сбор яиц и прогноз.\n\n"
            "- Добавить яйца: выбрать сегодня или вчера и ввести количество.\n"
            "- Расчеты: средние за 7/30 дней и прогноз на неделю.\n"
            "- Не несутся: временно исключить наседку, линьку или болезнь из расчета.\n"
            "- Для расчета на одну курицу нужно добавить поголовье `Куры/несушки`."
        ),
    },
    "egg_exclusions": {
        "title": "❓ FAQ: не несутся",
        "back": ("⬅️ К яйцам", "eggs:exclusions"),
        "text": (
            "Исключения нужны, когда курица временно не несет яйца.\n\n"
            "- Наседка, линька, болезнь и уход за цыплятами уменьшают активных несушек.\n"
            "- Исключенная курица не участвует в прогнозе яйценоскости.\n"
            "- Когда курица снова несется, нажмите `Снова несется`."
        ),
    },
    "egg_weather": {
        "title": "❓ FAQ: город и погода",
        "back": ("⬅️ К погоде", "eggs:weather"),
        "text": (
            "Погода используется только как ориентировочная поправка к прогнозу яиц.\n\n"
            "- Бот хранит город и последнюю загруженную погоду.\n"
            "- Главная страница яиц не ходит в сеть, чтобы не зависать.\n"
            "- Обновление погоды запускается вручную кнопкой `Обновить погоду`.\n"
            "- Важнее фактические условия в курятнике: свет, тепло, корм и стресс."
        ),
    },
    "settings": {
        "title": "❓ FAQ: настройки",
        "back": ("⬅️ Настройки", "settings:menu"),
        "text": (
            "Настройки управляют профилем хозяйства и поведением бота.\n\n"
            "- Название хозяйства: отображаемое имя вашего хозяйства.\n"
            "- Часовой пояс и время уведомлений влияют на напоминания.\n"
            "- Разделы и уведомления включают или скрывают кнопки главного меню.\n"
            "- О боте показывает версию, GitHub, changelog и время последнего запуска."
        ),
    },
    "settings_sections": {
        "title": "❓ FAQ: разделы и уведомления",
        "back": ("⬅️ Настройки", "settings:sections"),
        "text": (
            "Этот экран включает и выключает крупные функции.\n\n"
            "- Если раздел выключен, его кнопка пропадает из главного меню.\n"
            "- Инкубация, корма и яйца можно скрывать отдельно.\n"
            "- Системные сообщения управляют служебными уведомлениями.\n"
            "- Данные при выключении раздела не удаляются."
        ),
    },
}


def build_share_text(bot_username: str | None) -> str:
    if bot_username:
        link = f"https://t.me/{bot_username}?start=share"
        link_line = f"{link}\n\n"
    else:
        link_line = ""
    return (
        "Можно открыть этого бота с другого Telegram-аккаунта по ссылке:\n"
        f"{link_line}"
        "Каждый Telegram-аккаунт работает изолированно: свои партии, корма, "
        "поголовье, настройки и напоминания. Данные одного аккаунта не видны другому."
    )


@router.message(Command("start"))
async def start(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    await state.clear()
    incubation_service.track("bot_started", user_id=message.from_user.id if message.from_user else None)
    await message.answer(
        "Я помогу вести инкубацию, учет яиц и контролировать запас кормов.\n\n"
        "Выберите раздел в меню ниже.",
        reply_markup=main_menu_keyboard(incubation_service.get_user_settings(message.from_user.id)),
    )


@router.message(Command("share"))
async def share_command(message: Message) -> None:
    username = await _get_bot_username(message)
    await message.answer(build_share_text(username))


@router.callback_query(F.data == "menu:share")
async def share_callback(callback: CallbackQuery) -> None:
    username = await _get_bot_username(callback.message)
    await callback.message.answer(build_share_text(username))
    await callback.answer()


@router.callback_query(F.data.startswith("faq:"))
async def faq_callback(callback: CallbackQuery) -> None:
    section = str(callback.data).split(":", 1)[1]
    try:
        await callback.message.answer(format_faq(section), reply_markup=faq_keyboard(section))
    except KeyError:
        await callback.answer("Справка для этого раздела пока не добавлена.", show_alert=True)
        return
    await callback.answer()


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Добавление партии:\n"
        "/new - выбрать птицу, количество яиц, дату закладки и название.\n\n"
        "Редактирование:\n"
        "/edit ID яиц 24\n"
        "/edit ID дата 23.05.2026\n"
        "/edit ID название Моя партия\n"
        "/edit ID заметка Любая заметка\n"
        "/edit ID птица chicken|goose|quail|duck|muscovy_duck\n\n"
        "Разделы инкубации:\n"
        "/calendar - что делать по дням инкубации\n"
        "/care - уход после вывода\n"
        "/feed - добавить корм или ингредиент на склад\n\n"
        "Яйца:\n"
        "Главное меню -> Яйца - ежедневный сбор, прогноз и куры, которые временно не несутся.\n\n"
        "Настройки:\n"
        "/settings - уведомления, хозяйство, единицы\n"
        "/timezone Europe/Moscow - часовой пояс\n"
        "/farm Мое хозяйство - название хозяйства\n"
        "/disclaimer - справочный дисклеймер\n\n"
        "Закрытие партии:\n"
        "Нажмите кнопку Завершить вывод под партией и укажите количество выведенных птенцов.\n\n"
        "Напоминания:\n"
        "/remind 09:00 - включить ежедневный план\n"
        "/remind off - выключить\n\n"
        "Отмена текущего действия: /cancel."
    )


@router.message(Command("version"))
async def version_command(message: Message, config: AppConfig) -> None:
    version = config.release_version or APP_VERSION
    await message.answer(
        f"Текущая бета-версия бота: {version}\n"
        "Подробнее: Настройки -> О боте."
    )


@router.message(Command("menu"))
async def menu(message: Message, state: FSMContext, incubation_service: IncubationService) -> None:
    await state.clear()
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu_keyboard(incubation_service.get_user_settings(message.from_user.id)),
    )


@router.message(Command("cancel"))
async def cancel_any(
    message: Message,
    state: FSMContext,
    incubation_service: IncubationService | None = None,
) -> None:
    await state.clear()
    settings = incubation_service.get_user_settings(message.from_user.id) if incubation_service else None
    await message.answer("Действие отменено. Главное меню:", reply_markup=main_menu_keyboard(settings))


async def _get_bot_username(message: Message) -> str | None:
    me = await message.bot.get_me()
    return me.username


def format_faq(section: str) -> str:
    data = FAQ_SECTIONS[section]
    return f"{data['title']}\n\n{data['text']}"


def faq_keyboard(section: str) -> InlineKeyboardMarkup:
    label, callback_data = FAQ_SECTIONS[section]["back"]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=callback_data)],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
        ]
    )
