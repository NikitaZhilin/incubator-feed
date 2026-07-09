from pathlib import Path
import unittest

from app.services.poultry_advisor import load_poultry_advisor_content


class PoultryAdvisorContentTest(unittest.TestCase):
    def test_content_structure_is_valid(self) -> None:
        content = load_poultry_advisor_content()

        self.assertTrue(content["version"])
        self.assertIn("disclaimer", content)
        self.assertIn("daily_care", content)
        self.assertIn("red_flags", content)
        self.assertGreater(len(content["red_flags"]), 0)
        for item in content["red_flags"]:
            self.assertTrue(item["code"])
            self.assertTrue(item["title"])
            self.assertTrue(item["safe_action"])

    def test_content_does_not_include_medicine_dosages(self) -> None:
        text = Path("app/content/poultry_advisor.json").read_text(encoding="utf-8").lower()

        self.assertNotIn("мг/кг", text)
        self.assertNotIn("мл/кг", text)
        self.assertNotIn("доза", text)


if __name__ == "__main__":
    unittest.main()
