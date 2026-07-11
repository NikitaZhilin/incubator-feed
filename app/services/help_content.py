from dataclasses import dataclass
from pathlib import Path


HELP_CONTENT_DIR = Path(__file__).resolve().parents[1] / "content" / "help"


@dataclass(frozen=True)
class HelpTopic:
    title: str
    back_label: str
    back_callback: str
    filename: str


HELP_TOPICS: dict[str, HelpTopic] = {
    "main": HelpTopic("FAQ: главное меню", "Главное меню", "menu:home", "main.md"),
    "poultry_advisor": HelpTopic("FAQ: птицевод", "К птицеводу", "advisor:menu", "poultry_advisor.md"),
    "incubation": HelpTopic("FAQ: инкубация", "К инкубации", "menu:incubation", "incubation.md"),
    "feeds": HelpTopic("FAQ: корма", "К кормам", "feeds:menu", "feeds.md"),
    "stock": HelpTopic("FAQ: склад", "К складу", "stock:menu", "stock.md"),
    "mix": HelpTopic("FAQ: смесь", "К смеси", "stock:mix", "mix.md"),
    "stock_history": HelpTopic("FAQ: история склада", "К складу", "stock:menu", "stock_history.md"),
    "livestock": HelpTopic("FAQ: поголовье и стада", "Поголовье и стада", "feeds:livestock", "livestock.md"),
    "bird_groups": HelpTopic("FAQ: поголовье", "К поголовью", "feeds:groups", "bird_groups.md"),
    "flocks": HelpTopic("FAQ: стада", "К стадам", "feeds:flocks", "flocks.md"),
    "flock_card": HelpTopic("FAQ: карточка стада", "К стадам", "feeds:flocks", "flock_card.md"),
    "feed_card": HelpTopic("FAQ: карточка корма", "К кормам", "feeds:menu", "feed_card.md"),
    "feed_history": HelpTopic("FAQ: история корма", "К кормам", "feeds:menu", "feed_history.md"),
    "feed_stats": HelpTopic("FAQ: расчеты кормов", "К расчетам", "feeds:stats", "feed_stats.md"),
    "eggs": HelpTopic("FAQ: яйца", "К яйцам", "eggs:menu", "eggs.md"),
    "egg_history": HelpTopic("FAQ: история яиц", "К яйцам", "eggs:menu", "egg_history.md"),
    "egg_exclusions": HelpTopic("FAQ: не несутся", "К яйцам", "eggs:exclusions", "egg_exclusions.md"),
    "egg_weather": HelpTopic("FAQ: город и погода", "К погоде", "eggs:weather", "egg_weather.md"),
    "settings": HelpTopic("FAQ: настройки", "Настройки", "settings:menu", "settings.md"),
    "settings_sections": HelpTopic(
        "FAQ: разделы и уведомления",
        "Настройки",
        "settings:sections",
        "settings_sections.md",
    ),
}


def format_help_topic(topic_key: str) -> str:
    topic = HELP_TOPICS[topic_key]
    body = load_help_body(topic)
    return f"{topic.title}\n\n{body}"


def load_help_body(topic: HelpTopic) -> str:
    path = HELP_CONTENT_DIR / topic.filename
    return path.read_text(encoding="utf-8").strip()
