import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config


def main() -> None:
    config = load_config()
    usage = shutil.disk_usage(config.db_path.parent)
    free_mb = usage.free // 1024 // 1024
    print(f"Free disk: {free_mb} MB")
    if free_mb < config.min_free_disk_mb:
        raise SystemExit(f"Low disk space: {free_mb} MB < {config.min_free_disk_mb} MB")


if __name__ == "__main__":
    main()
