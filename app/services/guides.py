from app.domain import CONTENT, CONTENT_VERSION, DISCLAIMER_TEXT, IncubationProfile


def incubation_calendar(profile: IncubationProfile) -> str:
    cooling = (
        f"\nС {profile.cooling_from_day} дня: охлаждение/проветривание по самочувствию яйца."
        if profile.cooling_from_day
        else ""
    )
    candles = ", ".join(str(day) for day in profile.candle_days)
    return (
        f"Календарь: {profile.title}\n"
        f"Версия рекомендаций: {CONTENT_VERSION}\n\n"
        f"1 день: закладка, стабилизировать температуру {profile.temperature_main}.\n"
        f"2-{profile.turn_until_day} день: переворот 3-6 раз в день, контроль воды и температуры.\n"
        f"Овоскопирование: {candles} день.\n"
        f"{profile.lockdown_from_day} день: финальный этап, переворот прекратить, "
        f"влажность поднять до {profile.humidity_lockdown}.\n"
        f"{profile.hatch_days} день: ожидаемый вывод.\n"
        f"После вывода: дать обсохнуть, затем перенести в теплый брудер."
        f"{cooling}\n\n"
        f"Примечание: {profile.note}\n\n"
        f"{DISCLAIMER_TEXT}"
    )


def post_hatch_care(species_title: str) -> str:
    lines = "\n".join(f"- {item}" for item in CONTENT["post_hatch_care"]["common"])
    return (
        f"Уход после вывода: {species_title}\n"
        f"Версия рекомендаций: {CONTENT_VERSION}\n\n"
        f"{lines}\n\n"
        f"{DISCLAIMER_TEXT}"
    )


def disclaimer_text() -> str:
    return DISCLAIMER_TEXT
