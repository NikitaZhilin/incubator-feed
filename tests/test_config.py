import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import load_config, read_bot_token
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
                },
                clear=True,
            ):
                with patch("app.config.get_project_root", return_value=root):
                    config = load_config()

        self.assertEqual(config.release_version, "0.1.42-beta")
        self.assertEqual(config.release_notes, "Добавлена ссылка на web-версию")
        self.assertFalse(config.release_notice_enabled)

    def test_prod_uses_app_version_as_release_fallback(self) -> None:
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
        self.assertTrue(config.release_notice_enabled)


if __name__ == "__main__":
    unittest.main()
