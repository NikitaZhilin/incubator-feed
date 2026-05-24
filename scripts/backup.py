from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.services.backups import create_sqlite_backup, verify_sqlite_backup


def main() -> None:
    config = load_config()
    backup_path = create_sqlite_backup(config.db_path, config.backup_dir)
    ok = verify_sqlite_backup(backup_path)
    if not ok:
        raise SystemExit(f"Backup integrity check failed: {backup_path}")
    print(f"Backup created: {backup_path}")


if __name__ == "__main__":
    main()
