from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.storage.database import Database


def main() -> None:
    config = load_config()
    database = Database(config.db_path)
    database.initialize()
    print(f"Migrations applied: {config.db_path}")


if __name__ == "__main__":
    main()
