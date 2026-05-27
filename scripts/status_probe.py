from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_project_root, load_dotenv
from app.services.status_probe import build_status_report, status_exit_code


def main() -> int:
    root = get_project_root()
    load_dotenv(root)
    db_path = _database_path(root)
    report = build_status_report(db_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return status_exit_code(report)


def _database_path(root: Path) -> Path:
    environment = os.getenv("ENVIRONMENT", "dev").strip().lower() or "dev"
    default_name = "incubator.db" if environment == "prod" else "incubator_dev.db"
    raw_path = os.getenv("DATABASE_PATH", str(Path("data") / default_name)).strip()
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = root / path
    return path


if __name__ == "__main__":
    raise SystemExit(main())
