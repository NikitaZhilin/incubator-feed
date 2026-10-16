"""Backup copy sent to the admin in Telegram."""

from __future__ import annotations

import asyncio
import gzip
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec("aiogram"), "aiogram is not installed")
class AdminBackupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "incubator.db"
        connection = sqlite3.connect(self.db_path)
        connection.execute("CREATE TABLE t (x INTEGER)")
        connection.execute("INSERT INTO t VALUES (7)")
        connection.commit()
        connection.close()
        self.backup_dir = root / "backups"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_backup_is_sent_as_gzip_document(self) -> None:
        from app.handlers.admin import send_backup_to_admins
        from app.services.backups import run_verified_backup

        class Bot:
            def __init__(self) -> None:
                self.documents = []

            async def send_document(self, chat_id, document, caption=None):
                self.documents.append((chat_id, document, caption))

        bot = Bot()
        path = run_verified_backup(self.db_path, self.backup_dir)

        sent = asyncio.run(send_backup_to_admins(bot, frozenset({5}), path))

        self.assertTrue(sent)
        chat_id, document, caption = bot.documents[0]
        self.assertEqual(chat_id, 5)
        self.assertTrue(document.filename.endswith(".db.gz"))
        self.assertIn("/backup", caption)
        restored = Path(self.temp_dir.name) / "r.db"
        restored.write_bytes(gzip.decompress(document.data))
        self.assertEqual(sqlite3.connect(restored).execute("SELECT x FROM t").fetchone()[0], 7)


if __name__ == "__main__":
    unittest.main()
