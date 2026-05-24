import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.smoke_start import main as smoke_main


class SmokeStartTest(unittest.TestCase):
    def test_application_initializes_without_polling(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "BOT_TOKEN": "123456:ABCDEFabcdef1234567890",
                "ENVIRONMENT": "dev",
                "DATABASE_PATH": str(Path(temp_dir) / "smoke.db"),
                "BACKUP_DIR": str(Path(temp_dir) / "backups"),
                "LOG_FILE": str(Path(temp_dir) / "bot.log"),
                "ADMIN_IDS": "",
            }
            with patch.dict(os.environ, env, clear=False):
                smoke_main()


if __name__ == "__main__":
    unittest.main()
