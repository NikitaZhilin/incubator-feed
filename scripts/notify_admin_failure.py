from pathlib import Path
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_project_root, load_dotenv


def main() -> None:
    root = get_project_root()
    load_dotenv(root)
    token = os.getenv("BOT_TOKEN", "").strip()
    admin_ids = [
        item.strip()
        for item in os.getenv("ADMIN_IDS", "").replace(";", ",").split(",")
        if item.strip()
    ]
    reason = " ".join(sys.argv[1:]).strip() or "process failure"
    if not token or not admin_ids:
        print("BOT_TOKEN or ADMIN_IDS is empty; cannot notify admins")
        return
    text = f"Сервис Telegram-бота упал или был перезапущен внешним монитором.\n\nПричина: {reason}"
    for admin_id in admin_ids:
        payload = urllib.parse.urlencode({"chat_id": admin_id, "text": text}).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
        except Exception as exc:
            print(f"Failed to notify admin {admin_id}: {exc}")


if __name__ == "__main__":
    main()
