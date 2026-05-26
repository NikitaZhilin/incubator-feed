import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import (
    load_config,
    read_bot_token,
    should_send_admin_startup_notice,
    should_send_release_notice,
)
from app.version import APP_VERSION


class ConfigTest(unittest.TestCase):
    def test_prod_does_not_read_legacy_token_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "id.txt").write_text("legacy-token", encoding="utf-8")
            with patch.dict(os.environ, {"BOT_TOKEN": ""}, clear=False):
                with self.assertRaises(FileNotFoundError):
                    read_bot_token(root, environment="prod")

    def test_dev_can_read_legacy_token_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "id.txt").write_text("legacy-token", encoding="utf-8")
            with patch.dict(os.environ, {"BOT_TOKEN": ""}, clear=False):
                self.assertEqual(read_bot_token(root, environment="dev"), "legacy-token")

    def test_release_version_and_notes_are_loaded_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            root = Path(temp_dir)
            with patch.dict(
                os.environ,
                {
                    "ENVIRONMENT": "dev",
                    "BOT_TOKEN": "123456:test",
                    "DATABASE_PATH": str(db_path),
                    "RELEASE_VERSION": "0.1.42-beta",
                    "RELEASE_NOTES": "Добавлена ссылка на web-версию",
                    "RELEASE_CHANNEL": "beta",
                    "RELEASE_IMPORTANCE": "major",
                    "RELEASE_DEPLOYED_AT": "2026-05-26T08:30:00Z",
                    "RELEASE_COMMIT": "abcdef123456",
                    "ADMIN_STARTUP_NOTICE_MODE": "off",
                    "GITHUB_URL": "https://github.com/example/project",
                    "CHANGELOG_URL": "https://github.com/example/project/releases",
                },
                clear=True,
            ):
                with patch("app.config.get_project_root", return_value=root):
                    config = load_config()

        self.assertEqual(config.release_version, "0.1.42-beta")
        self.assertEqual(config.release_notes, "Добавлена ссылка на web-версию")
        self.assertEqual(config.release_channel, "beta")
        self.assertEqual(config.release_importance, "major")
        self.assertEqual(config.release_deployed_at, "2026-05-26T08:30:00Z")
        self.assertEqual(config.release_commit, "abcdef123456")
        self.assertEqual(config.admin_startup_notice_mode, "off")
        self.assertEqual(config.github_url, "https://github.com/example/project")
        self.assertEqual(config.changelog_url, "https://github.com/example/project/releases")
        self.assertFalse(config.release_notice_enabled)

    def test_prod_uses_app_version_as_release_fallback_without_startup_notice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.db"
            with patch.dict(
                os.environ,
                {
                    "ENVIRONMENT": "prod",
                    "BOT_TOKEN": "123456:test",
                    "DATABASE_PATH": str(db_path),
                },
                clear=True,
            ):
                with patch("app.config.get_project_root", return_value=root):
                    config = load_config()

        self.assertEqual(config.release_version, APP_VERSION)
        self.assertFalse(config.release_notice_enabled)
        self.assertFalse(should_send_release_notice(config))

    def test_admin_startup_notice_policy_requires_admin_ids_and_enabled_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.db"
            base_env = {
                "ENVIRONMENT": "prod",
                "BOT_TOKEN": "123456:test",
                "DATABASE_PATH": str(db_path),
            }
            with patch.dict(os.environ, base_env, clear=True):
                with patch("app.config.get_project_root", return_value=root):
                    no_admins = load_config()
            with patch.dict(os.environ, {**base_env, "ADMIN_IDS": "1,2"}, clear=True):
                with patch("app.config.get_project_root", return_value=root):
                    enabled = load_config()
            with patch.dict(
                os.environ,
                {**base_env, "ADMIN_IDS": "1,2", "ADMIN_STARTUP_NOTICE_MODE": "off"},
                clear=True,
            ):
                with patch("app.config.get_project_root", return_value=root):
                    disabled = load_config()

        self.assertFalse(should_send_admin_startup_notice(no_admins))
        self.assertEqual(enabled.admin_startup_notice_mode, "once_per_deploy")
        self.assertTrue(should_send_admin_startup_notice(enabled))
        self.assertFalse(should_send_admin_startup_notice(disabled))

    def test_release_notice_policy_requires_enabled_medium_major_or_critical(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.db"
            base_env = {
                "ENVIRONMENT": "prod",
                "BOT_TOKEN": "123456:test",
                "DATABASE_PATH": str(db_path),
                "RELEASE_NOTICE_ENABLED": "1",
                "RELEASE_VERSION": "0.1.42-beta",
            }
            with patch.dict(os.environ, {**base_env, "RELEASE_IMPORTANCE": "minor"}, clear=True):
                with patch("app.config.get_project_root", return_value=root):
                    minor = load_config()
            with patch.dict(os.environ, {**base_env, "RELEASE_IMPORTANCE": "medium"}, clear=True):
                with patch("app.config.get_project_root", return_value=root):
                    medium = load_config()
            with patch.dict(os.environ, {**base_env, "RELEASE_IMPORTANCE": "major"}, clear=True):
                with patch("app.config.get_project_root", return_value=root):
                    major = load_config()

        self.assertFalse(should_send_release_notice(minor))
        self.assertTrue(should_send_release_notice(medium))
        self.assertTrue(should_send_release_notice(major))


if __name__ == "__main__":
    unittest.main()
