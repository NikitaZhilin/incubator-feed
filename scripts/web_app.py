from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from app.web.main import create_app
from app.web.config import load_web_config


def main() -> None:
    config = load_web_config()
    if not config.enabled:
        raise SystemExit("WEB_ENABLED is not true. Set WEB_ENABLED=true to start web service.")
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
