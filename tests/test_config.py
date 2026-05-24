import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import read_bot_token


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


if __name__ == "__main__":
    unittest.main()
