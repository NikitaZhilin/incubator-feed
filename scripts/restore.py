import argparse
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.services.backups import verify_sqlite_backup


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore SQLite database from a verified backup.")
    parser.add_argument("backup", help="Path to backup .db file")
    parser.add_argument("--target", help="Target database path. Defaults to DATABASE_PATH.")
    args = parser.parse_args()

    config = load_config()
    backup_path = Path(args.backup)
    target = Path(args.target) if args.target else config.db_path
    if not verify_sqlite_backup(backup_path):
        raise SystemExit(f"Backup integrity check failed: {backup_path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, target)
    print(f"Restored {backup_path} -> {target}")


if __name__ == "__main__":
    main()
