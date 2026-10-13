from datetime import datetime, timezone
import unittest

from app.services.reminders import _settings_allow_daily_summary


def _settings(**overrides) -> dict:
    settings = {
        "is_active": True,
        "timezone": "Europe/Moscow",
        "notification_time": "08:30",
        "notify_daily_summary": True,
    }
    settings.update(overrides)
    return settings


class DailySummarySettingsTest(unittest.TestCase):
    # 05:40 UTC = 08:40 Moscow
    NOW = datetime(2026, 10, 14, 5, 40, tzinfo=timezone.utc)

    def test_summary_follows_user_notification_time(self) -> None:
        self.assertTrue(_settings_allow_daily_summary(_settings(), self.NOW))
        self.assertFalse(
            _settings_allow_daily_summary(_settings(notification_time="09:00"), self.NOW)
        )

    def test_summary_can_be_turned_off(self) -> None:
        self.assertFalse(
            _settings_allow_daily_summary(_settings(notify_daily_summary=False), self.NOW)
        )

    def test_inactive_user_gets_no_summary(self) -> None:
        self.assertFalse(_settings_allow_daily_summary(_settings(is_active=False), self.NOW))


if __name__ == "__main__":
    unittest.main()
