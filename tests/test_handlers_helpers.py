from datetime import date, datetime, timezone
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.config import AppConfig
from app.handlers.common import build_share_text, faq_keyboard, format_faq, format_web_unavailable_text
from app.handlers.incubation import _adjust_number, _user_today
from app.handlers.feeds import _format_flock_reports
from app.services.help_content import HELP_CONTENT_DIR, HELP_TOPICS
from app.handlers.settings import (
    _format_sections,
    _format_settings,
    _parse_notification_time,
    format_about_bot,
)
from app.domain import Flock, FlockFeedAssignment, FlockFeedUsage, FlockIngredientForecast, FlockReport
from app.keyboards.feeds import (
    bird_groups_keyboard,
    feed_actions_keyboard,
    feed_stats_keyboard,
    feeds_menu_keyboard,
    feed_history_keyboard,
    flock_actions_keyboard,
    flocks_keyboard,
    livestock_menu_keyboard,
    stock_assign_groups_keyboard,
    stock_cancel_keyboard,
    stock_history_keyboard,
    stock_mix_checklist_keyboard,
    stock_mix_entry_keyboard,
    stock_mix_fed_date_keyboard,
    stock_mix_mode_keyboard,
    stock_items_keyboard,
    stock_mix_quick_keyboard,
    stock_mix_unavailable_keyboard,
)
from app.keyboards.eggs import (
    egg_entry_date_keyboard,
    egg_entry_mode_keyboard,
    egg_multi_day_collection_date_keyboard,
    egg_multi_day_confirm_keyboard,
    egg_multi_day_period_keyboard,
    eggs_history_keyboard,
    eggs_menu_keyboard,
    exclusions_keyboard,
    weather_keyboard,
)
from app.keyboards.incubation import (
    batch_actions_keyboard,
    edit_batch_back_keyboard,
    edit_species_keyboard,
    guide_species_keyboard,
    number_adjust_keyboard,
)
from app.keyboards.menu import (
    about_bot_keyboard,
    daily_summary_keyboard,
    incubation_menu_keyboard,
    main_menu_keyboard,
    settings_keyboard,
    settings_sections_keyboard,
    web_choice_keyboard,
)
from app.keyboards.poultry_advisor import (
    advisor_back_keyboard,
    advisor_feed_keyboard,
    advisor_health_keyboard,
    advisor_menu_keyboard,
)


def _keyboard_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def _keyboard_callbacks(keyboard) -> list[str | None]:
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def _keyboard_urls(keyboard) -> list[str | None]:
    return [button.url for row in keyboard.inline_keyboard for button in row]


def _keyboard_web_app_urls(keyboard) -> list[str | None]:
    return [
        button.web_app.url
        for row in keyboard.inline_keyboard
        for button in row
        if button.web_app is not None
    ]


class HandlerHelpersTest(unittest.TestCase):
    def test_share_text_explains_isolated_accounts(self) -> None:
        text = build_share_text("test_incubator_bot")

        self.assertIn("https://t.me/test_incubator_bot?start=share", text)
        self.assertIn("Каждый Telegram-аккаунт работает изолированно", text)

    def test_web_unavailable_text_hides_technical_details_for_users(self) -> None:
        text = format_web_unavailable_text()

        self.assertIn("Сайт пока не подключен", text)
        self.assertIn("личный кабинет", text)
        self.assertNotIn("WEB_PUBLIC_URL", text)
        self.assertNotIn(".env", text)

        admin_text = format_web_unavailable_text(is_admin=True)

        self.assertIn("Для администратора", admin_text)
        self.assertIn("WEB_PUBLIC_URL", admin_text)

    def test_faq_text_and_navigation_are_available(self) -> None:
        main_text = format_faq("main")
        main_callbacks = _keyboard_callbacks(faq_keyboard("main"))

        self.assertIn("Корма - раздел для учета склада", main_text)
        self.assertIn("Яйца - раздел для ежедневного учета", main_text)
        self.assertEqual(main_callbacks.count("menu:home"), 1)

        feeds_text = format_faq("feeds")
        self.assertIn("что сейчас лежит на складе", feeds_text)
        self.assertIn("Добавить корм", feeds_text)
        self.assertIn("добавляет покупку в складские остатки", feeds_text)
        self.assertIn("сначала добавляются группы птиц", feeds_text)
        self.assertNotIn("Раздел объединяет склад", feeds_text)

        text = format_faq("mix")
        callbacks = _keyboard_callbacks(faq_keyboard("mix"))

        self.assertIn("FAQ: смесь", text)
        self.assertIn("это не покупка", text)
        self.assertIn("рецепт домашнего корма", text)
        self.assertIn("Если пшеницы нет", text)
        self.assertIn("1 часть = 1 литровая кружка", text)
        self.assertIn("stock:mix", callbacks)
        self.assertIn("menu:home", callbacks)

        advisor_text = format_faq("poultry_advisor")
        advisor_callbacks = _keyboard_callbacks(faq_keyboard("poultry_advisor"))
        self.assertIn("собирает данные из кормов", advisor_text)
        self.assertIn("не назначает лекарства", advisor_text)
        self.assertIn("advisor:menu", advisor_callbacks)

        stock_history_text = format_faq("stock_history")
        self.assertIn("почему изменился остаток", stock_history_text)
        self.assertIn("журнал операций", stock_history_text)

        feed_history_text = format_faq("feed_history")
        self.assertIn("старой ручной карточке", feed_history_text)
        self.assertIn("Склад -> История", feed_history_text)

        egg_history_text = format_faq("egg_history")
        self.assertIn("ежедневные итоги сбора", egg_history_text)
        self.assertIn("общий итог за этот день", egg_history_text)

        livestock_text = format_faq("livestock")
        self.assertIn("Поголовье - это отдельные группы птиц", livestock_text)
        self.assertIn("Стада - это наборы групп поголовья", livestock_text)
        self.assertIn("сначала создайте поголовье", livestock_text)

        flocks_text = format_faq("flocks")
        self.assertIn("назначьте стаду готовую", flocks_text)
        self.assertIn("сколько это стадо съедает в день", flocks_text)

    def test_faq_topics_are_backed_by_markdown_files(self) -> None:
        for key, topic in HELP_TOPICS.items():
            with self.subTest(topic=key):
                path = HELP_CONTENT_DIR / topic.filename
                self.assertTrue(path.exists())
                self.assertGreater(len(path.read_text(encoding="utf-8").strip()), 20)

    def test_faq_buttons_have_registered_file_topics(self) -> None:
        keyboard_dir = Path(__file__).resolve().parents[1] / "app" / "keyboards"
        topic_keys: set[str] = set()
        for path in keyboard_dir.glob("*.py"):
            topic_keys.update(re.findall(r'callback_data="faq:([a-z_]+)"', path.read_text(encoding="utf-8")))

        self.assertGreater(len(topic_keys), 10)
        self.assertEqual(set(), topic_keys - set(HELP_TOPICS))

    def test_adjust_number_respects_minimum(self) -> None:
        self.assertEqual(_adjust_number(1, "-10", min_value=1), 1)

    def test_adjust_number_respects_maximum(self) -> None:
        self.assertEqual(_adjust_number(8, "+10", min_value=0, max_value=10), 10)

    def test_adjust_number_supports_max_action(self) -> None:
        self.assertEqual(_adjust_number(3, "max", min_value=0, max_value=12), 12)

    def test_user_today_uses_user_timezone(self) -> None:
        class FakeIncubationService:
            def get_user_settings(self, user_id):
                return {"timezone": "Pacific/Kiritimati"}

        local_today = _user_today(
            1,
            FakeIncubationService(),
            datetime(2026, 7, 9, 11, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(local_today, date(2026, 7, 10))

    def test_about_bot_contains_version_links_and_release_notes(self) -> None:
        config = AppConfig(
            bot_token="123:test",
            db_path=Path("test.db"),
            log_file=Path("bot.log"),
            backup_dir=Path("backups"),
            admin_ids=frozenset(),
            environment="dev",
            log_level=20,
            reminder_interval_seconds=60,
            min_free_disk_mb=512,
            release_version="0.1.42-beta",
            release_notes="Исправлен расчет смеси; Добавлен экран версии",
            release_notice_enabled=False,
            release_channel="beta",
            release_importance="minor",
            github_url="https://github.com/example/project",
            changelog_url="https://github.com/example/project/blob/main/CHANGELOG.md",
            release_deployed_at="2026-05-26T08:30:00Z",
            release_commit="abcdef1234567890",
            runtime_started_at=datetime(2026, 5, 26, 9, 15, tzinfo=timezone.utc),
        )

        text = format_about_bot(config)

        self.assertIn("Версия: 0.1.42-beta", text)
        self.assertIn("Канал: beta", text)
        self.assertIn("Последний запуск: 26.05.2026 12:15", text)
        self.assertIn("Последний деплой: 26.05.2026 11:30", text)
        self.assertIn("Коммит: abcdef123456", text)
        self.assertIn("сайт пока не подключен", text)
        self.assertIn("https://github.com/example/project", text)
        self.assertIn("Документация:", text)
        self.assertIn("- Исправлен расчет смеси", text)
        self.assertIn("Бот находится в тестировании", text)

    def test_about_bot_contains_web_public_url_when_configured(self) -> None:
        config = AppConfig(
            bot_token="123:test",
            db_path=Path("test.db"),
            log_file=Path("bot.log"),
            backup_dir=Path("backups"),
            admin_ids=frozenset(),
            environment="dev",
            log_level=20,
            reminder_interval_seconds=60,
            min_free_disk_mb=512,
            release_version="0.1.42-beta",
            release_notes="",
            release_notice_enabled=False,
            release_channel="beta",
            release_importance="minor",
            github_url="https://github.com/example/project",
            changelog_url="https://github.com/example/project/blob/main/CHANGELOG.md",
            web_public_url="https://incubator.example.test/",
        )

        text = format_about_bot(config)

        self.assertIn("сайт настроен", text)
        self.assertIn("https://incubator.example.test", text)

    def test_about_keyboard_contains_documentation_link(self) -> None:
        keyboard = about_bot_keyboard(
            github_url="https://github.com/example/project",
            changelog_url="https://github.com/example/project/blob/main/docs/CHANGELOG.md",
            docs_url="https://github.com/example/project/tree/main/docs",
        )

        self.assertIn("📚 Документация", _keyboard_texts(keyboard))
        self.assertIn("https://github.com/example/project/tree/main/docs", _keyboard_urls(keyboard))

    def test_settings_summary_is_russian_and_command_free(self) -> None:
        text = _format_settings(
            {
                "farm_name": "",
                "timezone": "Europe/Moscow",
                "notification_time": "09:00",
                "units": "metric",
            }
        )

        self.assertIn("Хозяйство: не указано", text)
        self.assertIn("Единицы: кг и граммы", text)
        self.assertNotIn("metric", text)
        self.assertNotIn("Команды:", text)

    def test_sections_summary_explains_hidden_menu_buttons(self) -> None:
        text = _format_sections(
            {
                "notify_incubation": False,
                "notify_feed": True,
                "notify_eggs": True,
                "notify_post_hatch_care": False,
                "notify_poultry_advisor": True,
                "notify_service": True,
            }
        )

        self.assertIn("пропадает из главного меню", text)
        self.assertIn("Инкубация: выключено", text)
        self.assertIn("Яйца: включено", text)
        self.assertIn("Птицевод: включено", text)
        self.assertIn("Системные сообщения: включено", text)
        self.assertNotIn("Сервисные", text)

    def test_settings_keyboard_moves_toggles_deeper(self) -> None:
        texts = _keyboard_texts(settings_keyboard())

        self.assertIn("🧩 Разделы и уведомления", texts)
        self.assertIn("🏷 Название хозяйства", texts)
        self.assertIn("❓ FAQ", texts)
        self.assertNotIn("Инкубация вкл/выкл", texts)

        self.assertIn("❓ FAQ", _keyboard_texts(settings_sections_keyboard({"notify_feed": True})))
        self.assertIn("🐔 Птицевод: включено", _keyboard_texts(settings_sections_keyboard({"notify_poultry_advisor": True})))

    def test_main_menu_hides_disabled_sections(self) -> None:
        keyboard = main_menu_keyboard(
            {
                "notify_feed": False,
                "notify_eggs": False,
                "notify_incubation": True,
                "notify_poultry_advisor": False,
            }
        )
        texts = _keyboard_texts(keyboard)

        self.assertNotIn("🌾 Корма", texts)
        self.assertNotIn("🥚 Яйца", texts)
        self.assertIn("🥚 Инкубация", texts)
        self.assertIn("⚙️ Настройки", texts)
        self.assertIn("❓ FAQ", texts)
        self.assertIn("📊 Посмотреть сводку", texts)
        self.assertNotIn("🐔 Птицевод", texts)
        self.assertIn("menu:summary", _keyboard_callbacks(keyboard))
        self.assertIn("🌐 Открыть сайт", texts)
        self.assertIn("menu:web", _keyboard_callbacks(keyboard))

    def test_main_menu_shows_poultry_advisor_when_enabled(self) -> None:
        keyboard = main_menu_keyboard({"notify_poultry_advisor": True})

        self.assertIn("🐔 Птицевод", _keyboard_texts(keyboard))
        self.assertIn("advisor:menu", _keyboard_callbacks(keyboard))

    def test_poultry_advisor_keyboards_have_expected_callbacks(self) -> None:
        menu_callbacks = _keyboard_callbacks(advisor_menu_keyboard())
        menu_texts = _keyboard_texts(advisor_menu_keyboard())

        self.assertIn("📋 План на сегодня", menu_texts)
        self.assertIn("🌾 Корма и замес", menu_texts)
        self.assertIn("🥚 Мало яиц", menu_texts)
        self.assertIn("🩺 Проблема с птицей", menu_texts)
        self.assertIn("advisor:today", menu_callbacks)
        self.assertIn("advisor:feed", menu_callbacks)
        self.assertIn("advisor:health", menu_callbacks)
        self.assertIn("faq:poultry_advisor", menu_callbacks)
        self.assertIn("advisor:menu", _keyboard_callbacks(advisor_back_keyboard()))
        self.assertIn("advisor:mix_timing", _keyboard_callbacks(advisor_feed_keyboard()))
        self.assertIn("advisor:health:red_flags", _keyboard_callbacks(advisor_health_keyboard()))

    def test_main_menu_and_settings_show_web_button_and_use_url_when_configured(self) -> None:
        main_keyboard = main_menu_keyboard(
            web_url="https://incubator.example.test/?auth=secret",
            miniapp_url="https://incubator.example.test/?auth=secret",
        )
        settings_markup = settings_keyboard(
            web_url="https://incubator.example.test/?auth=secret",
            miniapp_url="https://incubator.example.test/?auth=secret",
        )

        self.assertIn("🌐 Открыть сайт", _keyboard_texts(main_keyboard))
        self.assertIn("📱 Открыть Mini App", _keyboard_texts(main_keyboard))
        self.assertIn("🌐 Открыть сайт", _keyboard_texts(settings_markup))
        self.assertIn("📱 Открыть Mini App", _keyboard_texts(settings_markup))
        self.assertIn("https://incubator.example.test/?auth=secret", _keyboard_urls(main_keyboard))
        self.assertIn("https://incubator.example.test/?auth=secret", _keyboard_web_app_urls(main_keyboard))
        self.assertIn("🌐 Открыть сайт", _keyboard_texts(settings_keyboard()))
        self.assertIn("menu:web", _keyboard_callbacks(settings_keyboard()))

    def test_web_choice_keyboard_shows_site_and_miniapp(self) -> None:
        markup = web_choice_keyboard(
            web_url="https://incubator.example.test/?auth=secret",
            miniapp_url="https://incubator.example.test/?auth=secret",
        )

        self.assertIn("🌐 Открыть сайт", _keyboard_texts(markup))
        self.assertIn("📱 Открыть Mini App", _keyboard_texts(markup))
        self.assertIn("https://incubator.example.test/?auth=secret", _keyboard_urls(markup))
        self.assertIn("https://incubator.example.test/?auth=secret", _keyboard_web_app_urls(markup))

    def test_daily_summary_keyboard_has_workflow_buttons(self) -> None:
        keyboard = daily_summary_keyboard()

        self.assertEqual(
            _keyboard_texts(keyboard),
            ["Добавить яйца", "Переход в раздел корма", "Выйти в меню"],
        )
        self.assertEqual(
            _keyboard_callbacks(keyboard),
            ["eggs:add", "feeds:menu", "menu:home"],
        )

    def test_eggs_keyboards_have_section_navigation(self) -> None:
        self.assertIn("➕ Добавить яйца", _keyboard_texts(eggs_menu_keyboard()))
        self.assertIn("📊 Расчеты", _keyboard_texts(eggs_menu_keyboard()))
        self.assertIn("❓ FAQ", _keyboard_texts(eggs_menu_keyboard()))
        self.assertIn("✏️ Исправить запись", _keyboard_texts(eggs_history_keyboard()))
        self.assertIn("❓ FAQ", _keyboard_texts(eggs_history_keyboard()))
        self.assertIn("Обычный сбор", _keyboard_texts(egg_entry_mode_keyboard()))
        self.assertIn("Сбор за несколько дней", _keyboard_texts(egg_entry_mode_keyboard()))
        self.assertIn("Сегодня", _keyboard_texts(egg_entry_date_keyboard()))
        self.assertIn("Вчера", _keyboard_texts(egg_entry_date_keyboard()))
        self.assertIn("Сегодня", _keyboard_texts(egg_multi_day_collection_date_keyboard()))
        self.assertIn("Ввести дату", _keyboard_texts(egg_multi_day_collection_date_keyboard()))
        self.assertIn("Указать количество дней", _keyboard_texts(egg_multi_day_period_keyboard()))
        self.assertIn("Не помню период", _keyboard_texts(egg_multi_day_period_keyboard()))
        self.assertIn("Записать", _keyboard_texts(egg_multi_day_confirm_keyboard()))
        self.assertIn("⬅️ К яйцам", _keyboard_texts(exclusions_keyboard([])))
        self.assertIn("❓ FAQ", _keyboard_texts(exclusions_keyboard([])))
        self.assertIn("✏️ Изменить город", _keyboard_texts(weather_keyboard()))
        self.assertIn("❓ FAQ", _keyboard_texts(weather_keyboard()))

    def test_incubation_menu_hides_post_hatch_care_when_disabled(self) -> None:
        keyboard = incubation_menu_keyboard({"notify_post_hatch_care": False})
        texts = _keyboard_texts(keyboard)

        self.assertNotIn("После вывода", texts)
        self.assertIn("Режимы", texts)
        self.assertIn("❓ FAQ", texts)

    def test_parse_notification_time_normalizes_and_validates(self) -> None:
        self.assertEqual(_parse_notification_time("9:05"), "09:05")
        with self.assertRaises(ValueError):
            _parse_notification_time("24:00")

    def test_incubation_view_keyboards_have_parent_back_buttons(self) -> None:
        self.assertIn("⬅️ К инкубации", _keyboard_texts(batch_actions_keyboard(7)))
        self.assertIn("⬅️ К инкубации", _keyboard_texts(guide_species_keyboard("calendar_species")))
        self.assertIn("⬅️ Назад к редактированию", _keyboard_texts(edit_species_keyboard(7)))
        self.assertIn("⬅️ Назад к редактированию", _keyboard_texts(edit_batch_back_keyboard(7)))

    def test_edit_number_keyboard_can_return_to_edit_menu(self) -> None:
        keyboard = number_adjust_keyboard(
            value=12,
            prefix="edit_eggs",
            min_value=1,
            back_callback="batch_edit:7",
            back_text="⬅️ Назад к редактированию",
        )
        texts = _keyboard_texts(keyboard)

        self.assertIn("⬅️ Назад к редактированию", texts)
        self.assertIn("Отмена", texts)

    def test_feed_and_stock_keyboards_have_section_back_buttons(self) -> None:
        self.assertIn("⬅️ К кормам", _keyboard_texts(feed_actions_keyboard(3)))
        self.assertIn("⬅️ К складу", _keyboard_texts(stock_mix_quick_keyboard("wheat", 3)))
        self.assertIn("⬅️ К выбору режима", _keyboard_texts(stock_mix_quick_keyboard("wheat", 3)))
        self.assertIn("❓ FAQ", _keyboard_texts(feeds_menu_keyboard()))
        self.assertIn("❓ FAQ", _keyboard_texts(feed_history_keyboard(3)))
        self.assertIn("❓ FAQ", _keyboard_texts(stock_history_keyboard()))
        self.assertIn("❓ FAQ", _keyboard_texts(stock_mix_quick_keyboard("wheat", 3)))
        self.assertIn("Отмена", _keyboard_texts(stock_cancel_keyboard()))

    def test_mix_entry_keyboard_separates_current_and_past_mix_flows(self) -> None:
        texts = _keyboard_texts(stock_mix_entry_keyboard())
        callbacks = _keyboard_callbacks(stock_mix_entry_keyboard())

        self.assertIn("Сделать новый замес сейчас", texts)
        self.assertIn("Записать прошлый замес как уже скормленный", texts)
        self.assertIn("stock:mix_flow:now", callbacks)
        self.assertIn("stock:mix_flow:already_fed", callbacks)

    def test_mix_checklist_keyboard_uses_recipe_parts(self) -> None:
        plan = SimpleNamespace(
            mix_count=2,
            grain_base_code="wheat",
            can_produce=True,
            ingredients=(
                SimpleNamespace(name="Кукуруза", parts=3.5, required_kg=5.04),
                SimpleNamespace(name="Премикс", parts=0.1, required_kg=0.15),
            ),
        )

        keyboard = stock_mix_checklist_keyboard(plan, checked_indices={0}, current_cycle=1, total_cycles=2)
        texts = _keyboard_texts(keyboard)

        self.assertIn("✅ Кукуруза: 3.5 части", texts)
        self.assertIn("⬜ Премикс: 0.1 части", texts)
        self.assertIn("Отметить все ингредиенты", texts)
        self.assertNotIn("🕘 Записать как уже скормленные", texts)
        self.assertNotIn("Продолжить после отметок", texts)

    def test_mix_checklist_final_button_updates_stock(self) -> None:
        plan = SimpleNamespace(
            mix_count=1,
            grain_base_code="wheat",
            can_produce=True,
            ingredients=(
                SimpleNamespace(name="Кукуруза", parts=3.5, required_kg=2.52),
            ),
        )

        keyboard = stock_mix_checklist_keyboard(plan, checked_indices={0}, current_cycle=1, total_cycles=1)
        texts = _keyboard_texts(keyboard)

        self.assertIn("✅ Замес готов, обновить склад", texts)
        self.assertNotIn("🕘 Записать как уже скормленный", texts)
        self.assertNotIn("✅ Завершить и списать склад", texts)

    def test_mix_mode_keyboard_allows_current_or_already_fed_record(self) -> None:
        plan = SimpleNamespace(
            mix_count=2,
            grain_base_code="wheat",
            can_produce=True,
            ingredients=(
                SimpleNamespace(name="Кукуруза", parts=3.5, required_kg=2.52),
            ),
        )

        keyboard = stock_mix_mode_keyboard(plan)
        texts = _keyboard_texts(keyboard)
        callbacks = _keyboard_callbacks(keyboard)

        self.assertIn("Сделать сейчас", texts)
        self.assertIn("🕘 Записать как уже скормленные", texts)
        self.assertIn("stock:mix_mode:now", callbacks)
        self.assertIn("stock:mix_mode:already_fed", callbacks)

    def test_mix_unavailable_keyboard_allows_already_fed_record(self) -> None:
        plan = SimpleNamespace(mix_count=3, grain_base_code="wheat", max_mix_count=2)

        keyboard = stock_mix_unavailable_keyboard(plan)
        texts = _keyboard_texts(keyboard)
        callbacks = _keyboard_callbacks(keyboard)

        self.assertIn("🕘 Записать как уже скормленные", texts)
        self.assertIn("stock:mix_fed_start:wheat:3", callbacks)
        self.assertIn("stock:mix_plan:wheat:1", callbacks)
        self.assertNotIn("stock:mix_confirm:wheat:3", callbacks)

    def test_mix_fed_date_keyboard_has_unknown_instead_of_yesterday(self) -> None:
        texts = _keyboard_texts(stock_mix_fed_date_keyboard())

        self.assertIn("Сегодня", texts)
        self.assertIn("7 дней назад", texts)
        self.assertIn("Без даты / не помню", texts)
        self.assertIn("Ввести дату", texts)
        self.assertNotIn("Вчера", texts)

    def test_mix_quick_buttons_open_plan_before_writeoff(self) -> None:
        quick_keyboard = stock_mix_quick_keyboard("wheat", 3)
        callbacks = _keyboard_callbacks(quick_keyboard)
        texts = _keyboard_texts(quick_keyboard)

        self.assertIn("Сделать 1 замес", texts)
        self.assertIn("stock:mix_plan:wheat:1", callbacks)
        self.assertNotIn("stock:mix_confirm:wheat:1", callbacks)

        fed_texts = _keyboard_texts(stock_mix_quick_keyboard("wheat", 3, record_mode="already_fed"))
        self.assertIn("Списать 1 замес", fed_texts)

    def test_feed_menu_nests_groups_and_flocks(self) -> None:
        self.assertIn("🐔 Поголовье и стада", _keyboard_texts(feeds_menu_keyboard()))
        self.assertNotIn("🐓 Стада", _keyboard_texts(feeds_menu_keyboard()))
        self.assertIn("🐔 Поголовье", _keyboard_texts(livestock_menu_keyboard()))
        self.assertIn("🐓 Стада", _keyboard_texts(livestock_menu_keyboard()))
        self.assertIn("❓ FAQ", _keyboard_texts(livestock_menu_keyboard()))
        self.assertIn("➕ Добавить поголовье", _keyboard_texts(livestock_menu_keyboard()))
        self.assertIn("➕ Создать стадо", _keyboard_texts(livestock_menu_keyboard()))
        self.assertNotIn("🐔 Стада", _keyboard_texts(bird_groups_keyboard()))
        self.assertIn("❓ FAQ", _keyboard_texts(bird_groups_keyboard()))
        self.assertIn("⬅️ Поголовье и стада", _keyboard_texts(bird_groups_keyboard()))
        self.assertNotIn("🐔 Поголовье", _keyboard_texts(flocks_keyboard()))
        self.assertIn("❓ FAQ", _keyboard_texts(flocks_keyboard()))
        self.assertIn("⬅️ Поголовье и стада", _keyboard_texts(flocks_keyboard()))
        self.assertIn("🍽 Назначить смесь", _keyboard_texts(flock_actions_keyboard(1)))
        self.assertIn("❓ FAQ", _keyboard_texts(flock_actions_keyboard(1)))

    def test_feed_stats_keyboard_stays_in_stats_context(self) -> None:
        texts = _keyboard_texts(feed_stats_keyboard())

        self.assertIn("🐔 Поголовье и стада", texts)
        self.assertIn("⬅️ К кормам", texts)
        self.assertIn("❓ FAQ", texts)
        self.assertNotIn("➕ Добавить корм", texts)
        self.assertNotIn("📊 Расчеты", texts)

    def test_flock_report_formats_purchase_forecast_with_spacing(self) -> None:
        now = datetime(2026, 5, 26, 9, 0, tzinfo=timezone.utc)
        report = FlockReport(
            flock=Flock(
                id=1,
                user_id=1,
                name="Основное",
                is_active=True,
                created_at=now,
                updated_at=now,
            ),
            members=(),
            assignments=(
                FlockFeedUsage(
                    assignment=FlockFeedAssignment(
                        id=1,
                        user_id=1,
                        flock_id=1,
                        stock_item_id=1,
                        is_active=True,
                        share_percent=100,
                        daily_per_hen_g=120,
                        daily_per_rooster_g=150,
                        daily_per_adult_g=120,
                        reserve_percent=0,
                        started_at=now,
                        stock_item_name="Смесь для кур",
                    ),
                    daily_usage_kg=2,
                    remaining_kg=10,
                    days_left=5,
                    producible_mix_count=4,
                    producible_mix_kg=100,
                    total_days_left=55,
                    ingredient_forecasts=(
                        FlockIngredientForecast("Пшеница", 20, 1, 20),
                        FlockIngredientForecast("Кукуруза", 40, 1, 40),
                    ),
                ),
            ),
            daily_usage_kg=2,
        )

        text = _format_flock_reports([report])

        self.assertIn("\n\nСмесь: Смесь для кур", text)
        self.assertIn("Закупки по ингредиентам:", text)
        self.assertIn("первым докупить: Пшеница", text)
        self.assertIn("Остальные ингредиенты:", text)
        self.assertIn("Кукуруза", text)

    def test_stock_selection_keyboards_cancel_to_stock_menu(self) -> None:
        class Item:
            id = 1
            name = "Комбикорм"

        class Group:
            id = 2
            name = "Несушки"
            bird_count = 12

        item_keyboard = stock_items_keyboard(
            [Item()],
            prefix="stock:adjust_item",
            back_callback="stock:menu",
        )
        group_keyboard = stock_assign_groups_keyboard([Group()])

        self.assertIn("⬅️ К складу", _keyboard_texts(item_keyboard))
        self.assertIn("Отмена", _keyboard_texts(group_keyboard))
        self.assertIn("stock:menu", _keyboard_callbacks(item_keyboard))
        self.assertIn("stock:menu", _keyboard_callbacks(group_keyboard))


if __name__ == "__main__":
    unittest.main()
