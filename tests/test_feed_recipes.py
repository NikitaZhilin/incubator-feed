import unittest

from app.services.feed_recipes import calculate_chicken_mix, parse_feed_amount


class FeedRecipesTest(unittest.TestCase):
    def test_parse_kg_and_bags(self) -> None:
        self.assertEqual(parse_feed_amount("25 кг"), 25)
        self.assertEqual(parse_feed_amount("30кг"), 30)
        self.assertEqual(parse_feed_amount("1 мешок"), 25)
        self.assertEqual(parse_feed_amount("2 мешка по 30"), 60)

    def test_chicken_mix_totals_match_target(self) -> None:
        calculation = calculate_chicken_mix(25)

        self.assertAlmostEqual(sum(item.kg for item in calculation.ingredients), 25, places=6)
        self.assertAlmostEqual(calculation.one_cycle_liters, 9.6)
        self.assertEqual(calculation.ingredients[0].ingredient.name, "Кукуруза")
        self.assertEqual(calculation.ingredients[-1].ingredient.name, "Премикс")

    def test_chicken_mix_can_replace_wheat_with_layer_grain_mix(self) -> None:
        calculation = calculate_chicken_mix(25, grain_base="layer_grain_mix")
        grain_mix = calculation.ingredients[1]

        self.assertEqual(grain_mix.ingredient.name, "Зерновая смесь для кур несушек")
        self.assertAlmostEqual(grain_mix.liters, 9.34, places=2)
        self.assertAlmostEqual(grain_mix.kg, 6.72, places=2)
        self.assertAlmostEqual(sum(item.kg for item in calculation.ingredients), 25, places=6)


if __name__ == "__main__":
    unittest.main()
