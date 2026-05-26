import sqlite3

from app.storage.migrations import add_column_if_missing


def up(connection: sqlite3.Connection) -> None:
    add_column_if_missing(connection, "daily_weather", "day_temperature_min_c", "REAL")
    add_column_if_missing(connection, "daily_weather", "day_temperature_max_c", "REAL")
    add_column_if_missing(connection, "daily_weather", "day_condition", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(connection, "daily_weather", "night_temperature_min_c", "REAL")
    add_column_if_missing(connection, "daily_weather", "night_temperature_max_c", "REAL")
    add_column_if_missing(connection, "daily_weather", "night_condition", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(connection, "daily_weather", "tomorrow_date", "TEXT")
    add_column_if_missing(connection, "daily_weather", "tomorrow_temperature_min_c", "REAL")
    add_column_if_missing(connection, "daily_weather", "tomorrow_temperature_max_c", "REAL")
    add_column_if_missing(connection, "daily_weather", "tomorrow_condition", "TEXT NOT NULL DEFAULT ''")
