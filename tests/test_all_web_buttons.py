"""Open every link and submit every form of the web version on a seeded database.

Starting from the main page, every internal link is opened (must answer 200) and
every form is submitted with the values shown on the page, filling empty
required fields with plausible input. A submit must never fail with 4xx/5xx and
must land on a page that renders. Forms that reject their own default values are
reported, because the user would see an error right after pressing the button.
"""

from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi.testclient import TestClient

from app.storage.database import Database
from app.web.config import WebConfig
from app.web.main import create_app
try:
    from test_all_buttons import USER_ID, _seed
except ImportError:  # running from the repository root as a package
    from tests.test_all_buttons import USER_ID, _seed


REPORT_PATH = Path(__file__).resolve().parent.parent / "button_report.txt"
TOKEN = "link-token"
MAX_REQUESTS = 600


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.forms: list[dict] = []
        self._form: dict | None = None
        self._select: dict | None = None
        self._textarea: dict | None = None

    def handle_data(self, data):
        if self._textarea is not None:
            self._textarea["value"] += data

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        elif tag == "form":
            self._form = {
                "action": attrs.get("action") or "",
                "method": (attrs.get("method") or "get").lower(),
                "fields": [],
                "buttons": [],
            }
        elif self._form is not None and tag == "input":
            self._form["fields"].append(attrs)
        elif self._form is not None and tag == "select":
            self._select = {"name": attrs.get("name"), "value": None, "multiple": "multiple" in attrs}
        elif self._select is not None and tag == "option":
            if self._select["value"] is None or "selected" in attrs:
                self._select["value"] = attrs.get("value", "")
        elif self._form is not None and tag == "button":
            self._form["buttons"].append(attrs)
        elif self._form is not None and tag == "textarea":
            self._textarea = {"name": attrs.get("name"), "type": "textarea", "value": ""}

    def handle_endtag(self, tag):
        if tag == "textarea" and self._textarea is not None and self._form is not None:
            self._form["fields"].append(self._textarea)
            self._textarea = None
        elif tag == "select" and self._select is not None and self._form is not None:
            self._form["fields"].append(
                {"name": self._select["name"], "type": "select", "value": self._select["value"] or ""}
            )
            self._select = None
        elif tag == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None


def _form_values(form: dict) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    today = date.today().isoformat()
    for field in form["fields"]:
        name = field.get("name")
        if not name:
            continue
        kind = (field.get("type") or "text").lower()
        value = field.get("value")
        if kind == "checkbox":
            # Confirmations ("подтвердить") must be ticked to test the real action.
            if "checked" in field or "required" in field:
                values.setdefault(name, []).append(value or "on")
            continue
        if kind == "radio":
            if "checked" in field:
                values[name] = [value or ""]
            continue
        if value in (None, ""):
            if kind == "number":
                value = field.get("min") or "1"
                if value in ("0", "0.0"):
                    value = "1"
            elif kind == "date":
                value = field.get("max") or today
            elif kind == "time":
                value = "09:00"
            elif kind == "hidden":
                value = ""
            elif "required" in field:
                value = "Тест"
            else:
                value = ""
        values.setdefault(name, []).append(value)
    return values


class AllWebButtonsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "web.db"
        self.database = Database(db_path)
        self.database.initialize()
        _seed(self.database)
        config = WebConfig(
            enabled=True,
            host="127.0.0.1",
            port=8080,
            admin_token="secret",
            db_path=db_path,
            environment="test",
            release_version="0.1.99-beta",
            release_channel="beta",
            release_deployed_at="2026-10-13T12:00:00Z",
            release_commit="abc123",
            github_url="https://github.com/example/project",
            changelog_url="https://github.com/example/project/blob/main/docs/CHANGELOG.md",
            link_token=TOKEN,
        )
        self.client = TestClient(create_app(config), raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_every_link_and_form_works(self) -> None:
        problems: dict[str, list[str]] = {"broken": [], "rejected_defaults": []}
        visited_pages: set[str] = set()
        submitted: set[tuple[str, str]] = set()
        queue = [f"/?auth={TOKEN}&user_id={USER_ID}"]
        requests = 0

        while queue and requests < MAX_REQUESTS:
            url = queue.pop(0)
            key = urlsplit(url).path + "?" + "&".join(
                sorted(f"{k}={v}" for k, v in parse_qs(urlsplit(url).query).items() if k not in {"notice", "error"})
            )
            if key in visited_pages:
                continue
            visited_pages.add(key)
            requests += 1
            response = self.client.get(url)
            if response.status_code != 200:
                problems["broken"].append(f"GET {url} -> {response.status_code}")
                continue
            if "text/html" not in response.headers.get("content-type", ""):
                continue
            parser = _PageParser()
            parser.feed(response.text)

            for href in parser.links:
                parts = urlsplit(href)
                if parts.scheme or parts.netloc or href.startswith("#"):
                    continue
                queue.append(href)

            for form in parser.forms:
                action = form["action"] or urlsplit(url).path
                path = urlsplit(action).path
                signature = (form["method"], path.rstrip("0123456789/"))
                if signature in submitted:
                    continue
                submitted.add(signature)
                values = _form_values(form)
                requests += 1
                if form["method"] == "get":
                    joined = action + ("&" if "?" in action else "?") + urlencode(values, doseq=True)
                    queue.append(joined)
                    continue
                result = self.client.post(action, data=values, follow_redirects=False)
                label = f"POST {path}"
                if result.status_code >= 400:
                    problems["broken"].append(f"{label} -> {result.status_code}")
                    continue
                location = result.headers.get("location", "")
                if location:
                    error = parse_qs(urlsplit(location).query).get("error")
                    if error:
                        problems["rejected_defaults"].append(f"{label}: {error[0]}")
                    landing = self.client.get(location)
                    if landing.status_code != 200:
                        problems["broken"].append(f"{label} -> {location} -> {landing.status_code}")

        lines = [
            f"Сайт: открыто страниц {len(visited_pages)}, отправлено форм {len(submitted)}",
        ]
        for name, items in problems.items():
            if items:
                lines.append(f"{name} ({len(items)}): " + " | ".join(items[:40]))
        with REPORT_PATH.open("a", encoding="utf-8") as report:
            report.write("\n".join(lines) + "\n")

        self.assertGreater(len(visited_pages), 8)
        self.assertGreater(len(submitted), 15)
        self.assertEqual(problems["broken"], [], "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
