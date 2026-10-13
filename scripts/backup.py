import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.services.backups import run_verified_backup


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a verified SQLite backup.")
    parser.add_argument(
        "--label",
        default="",
        help="Subfolder inside BACKUP_DIR, e.g. pre-deploy. Keeps these copies "
        "separate from the daily ones.",
    )
    parser.add_argument("--keep", type=int, default=7, help="How many copies to keep.")
    args = parser.parse_args()

    config = load_config()
    if not config.db_path.exists():
        print(f"Database not found, nothing to back up: {config.db_path}")
        return
    backup_dir = config.backup_dir / args.label if args.label else config.backup_dir
    try:
        backup_path = run_verified_backup(config.db_path, backup_dir, keep_last=args.keep)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Backup created: {backup_path}")


if __name__ == "__main__":
    main()
