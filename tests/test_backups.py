from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.services.backups import (
    DailyBackupLoop,
    backup_is_due,
    latest_backup_time,
    run_verified_backup,
)


class BackupTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "data" / "incubator.db"
        self.db_path.parent.mkdir()
        self.backup_dir = root / "backups"
        connection = sqlite3.connect(self.db_path)
        connection.execute("CREATE TABLE t (x INTEGER)")
        connection.execute("INSERT INTO t VALUES (42)")
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_backup_is_due_without_backups_and_not_due_right_after(self) -> None:
        self.assertTrue(backup_is_due(self.db_path, self.backup_dir, every=timedelta(hours=24)))

        run_verified_backup(self.db_path, self.backup_dir)

        self.assertFalse(backup_is_due(self.db_path, self.backup_dir, every=timedelta(hours=24)))
        tomorrow = datetime.now(timezone.utc) + timedelta(hours=25)
        self.assertTrue(
            backup_is_due(self.db_path, self.backup_dir, every=timedelta(hours=24), now=tomorrow)
        )

    def test_missing_database_is_not_backed_up(self) -> None:
        missing = self.db_path.parent / "absent.db"

        self.assertFalse(backup_is_due(missing, self.backup_dir, every=timedelta(hours=24)))

    def test_backup_contains_data(self) -> None:
        path = run_verified_backup(self.db_path, self.backup_dir)

        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute("SELECT x FROM t").fetchone()[0], 42)
        finally:
            connection.close()
        self.assertIsNotNone(latest_backup_time(self.db_path, self.backup_dir))

    async def test_loop_creates_one_backup_per_period(self) -> None:
        loop = DailyBackupLoop(db_path=self.db_path, backup_dir=self.backup_dir)

        first = await loop.run_once()
        second = await loop.run_once()

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(list(self.backup_dir.glob("incubator_*.db"))), 1)


if __name__ == "__main__":
    unittest.main()
