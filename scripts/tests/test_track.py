"""Run with:  python3 -m unittest discover -s scripts/tests -v"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import off  # noqa: E402
import track  # noqa: E402

D = dt.date(2026, 1, 5)  # a Monday

FOODS = {
    "_meta": {"note": "test"},
    "pasta_secca": {"name": "Pasta di semola", "state": "crudo", "source": "label",
                    "per100g": {"kcal": 359, "protein": 13.0, "carbs": 71.0, "fat": 1.5,
                                "fiber": 3.0, "sugar": 3.5, "sodium_mg": 3}},
    "pollo_petto": {"name": "Petto di pollo", "state": "crudo", "source": "manual",
                    "per100g": {"kcal": 100, "protein": 23.3, "carbs": 0.0, "fat": 0.8,
                                "fiber": 0.0, "sugar": 0.0, "sodium_mg": None}},
}
PROFILE = """
timezone: Europe/Rome
targets: {kcal: 2000, protein: 150, carbs: 220, fat: 60, fiber: 30, sugar: null, sodium_mg: 2300}
track: {fiber: true, sugar: false, sodium: true}
"""
RECIPE = """
name: Pasta e pollo
portions: 2
ingredients:
  - {food_id: pasta_secca, grams: 200}
  - {food_id: pollo_petto, grams: 300}
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["TRACKGYM_ROOT"] = self.tmp.name
        (self.root / "foods").mkdir()
        (self.root / "foods" / "foods.json").write_text(json.dumps(FOODS))
        (self.root / "profile.yaml").write_text(PROFILE)
        (self.root / "recipes").mkdir()
        (self.root / "recipes" / "pasta_pollo.yaml").write_text(RECIPE)

    def tearDown(self):
        os.environ.pop("TRACKGYM_ROOT", None)
        self.tmp.cleanup()


class TestCompute(unittest.TestCase):
    def test_scaling_and_rounding(self):
        v = track.compute(FOODS["pasta_secca"]["per100g"], 100)
        self.assertEqual(v["kcal"], 359)
        self.assertEqual(v["protein"], 13.0)
        v = track.compute(FOODS["pasta_secca"]["per100g"], 85)
        self.assertEqual(v["kcal"], 305)        # 305.15
        self.assertEqual(v["carbs"], 60.4)      # 60.35
        self.assertEqual(v["fat"], 1.3)         # 1.275

    def test_missing_stays_none(self):
        v = track.compute(FOODS["pollo_petto"]["per100g"], 200)
        self.assertIsNone(v["sodium_mg"])
        self.assertEqual(v["protein"], 46.6)

    def test_zero_grams_rejected(self):
        with self.assertRaises(track.TrackError):
            track.compute(FOODS["pasta_secca"]["per100g"], 0)

    def test_total_flags_partial(self):
        a = {"values": track.compute(FOODS["pasta_secca"]["per100g"], 100)}
        b = {"values": track.compute(FOODS["pollo_petto"]["per100g"], 200)}
        t = track.total([a, b])
        self.assertEqual(t["kcal"], 559)
        self.assertEqual(t["protein"], 59.6)
        self.assertEqual(t["sodium_mg"], 3)
        self.assertIn("sodium_mg", t["_missing"])

    def test_remaining(self):
        t = {"kcal": 559, "protein": 59.6, "carbs": 71.0, "fat": 2.6}
        tg = {"kcal": 2000, "protein": 150, "carbs": None, "fat": 60}
        rem = track.remaining(t, tg)
        self.assertEqual(rem["kcal"], 1441)
        self.assertEqual(rem["protein"], 90.4)
        self.assertIsNone(rem["carbs"])

    def test_suggest_meal(self):
        self.assertEqual(track.suggest_meal(dt.time(8, 0)), "colazione")
        self.assertEqual(track.suggest_meal(dt.time(13, 0)), "pranzo")
        self.assertEqual(track.suggest_meal(dt.time(20, 30)), "cena")
        self.assertIsNone(track.suggest_meal(dt.time(16, 30)))


class TestLog(Base):
    def test_add_creates_file_with_snapshot(self):
        track.add_food(D, "pranzo", "pasta_secca", 100)
        p = self.root / "log" / "2026" / "01" / "2026-01-05.yaml"
        self.assertTrue(p.exists())
        day = track.load_day(D)
        e = day["meals"]["pranzo"][0]
        self.assertEqual(e["food_id"], "pasta_secca")
        self.assertEqual(e["grams"], 100)
        self.assertEqual(e["state"], "crudo")
        self.assertEqual(e["values"]["kcal"], 359)

    def test_catalog_change_does_not_alter_past(self):
        track.add_food(D, "pranzo", "pasta_secca", 100)
        foods = track.load_foods()
        foods["pasta_secca"]["per100g"]["kcal"] = 999
        track.save_foods(foods)
        self.assertEqual(track.load_day(D)["meals"]["pranzo"][0]["values"]["kcal"], 359)
        # metadata keys preserved
        self.assertIn("_meta", json.loads((self.root / "foods" / "foods.json").read_text()))

    def test_unknown_food_and_meal(self):
        with self.assertRaises(track.TrackError):
            track.add_food(D, "pranzo", "nutella", 20)
        with self.assertRaises(track.TrackError):
            track.add_food(D, "merenda", "pasta_secca", 20)
        self.assertFalse((self.root / "log").exists())

    def test_remove_and_empty_day_deleted(self):
        track.add_food(D, "pranzo", "pasta_secca", 100)
        track.add_food(D, "pranzo", "pollo_petto", 200)
        removed = track.remove_entry(D, "pranzo", 1)
        self.assertEqual(removed["food_id"], "pasta_secca")
        self.assertEqual(len(track.load_day(D)["meals"]["pranzo"]), 1)
        with self.assertRaises(track.TrackError):
            track.remove_entry(D, "pranzo", 5)
        track.remove_entry(D, "pranzo", 1)
        self.assertFalse(track.day_path(D).exists())

    def test_recipe_scaled_by_portions(self):
        track.add_recipe(D, "cena", "pasta_pollo", portions=1)
        items = track.load_day(D)["meals"]["cena"]
        self.assertEqual([e["grams"] for e in items], [100, 150])
        self.assertTrue(all(e["recipe"] == "pasta_pollo" for e in items))
        self.assertEqual(track.total(items)["kcal"], 359 + 150)

    def test_range_average_ignores_empty_days(self):
        track.add_food(D, "pranzo", "pasta_secca", 100)                       # 359
        track.add_food(D + dt.timedelta(days=2), "cena", "pollo_petto", 300)  # 300
        s = track.range_stats(D, D + dt.timedelta(days=6))
        self.assertEqual(len(s["days"]), 2)
        self.assertEqual(s["n_days"], 7)
        self.assertEqual(s["average"]["kcal"], 330)  # 329.5 → 330
        text = track.render_range(s, track.load_profile())
        self.assertIn("Giorni registrati: 2/7", text)

    def test_cli_add_and_show(self):
        rc = track.main(["add", "--date", "2026-01-05", "--meal", "pranzo",
                         "--food", "pasta_secca", "--grams", "100"])
        self.assertEqual(rc, 0)
        self.assertEqual(track.main(["add", "--date", "2026-01-05", "--meal", "pranzo",
                                     "--food", "boh", "--grams", "100"]), 1)

    def test_food_add_salt_conversion(self):
        rc = track.main(["food", "add", "--id", "x", "--name", "X", "--state", "n/a",
                         "--source", "label", "--kcal", "100", "--protein", "1",
                         "--carbs", "2", "--fat", "3", "--salt", "1.25"])
        self.assertEqual(rc, 0)
        self.assertEqual(track.load_foods()["x"]["per100g"]["sodium_mg"], 500)


class TestOff(unittest.TestCase):
    def test_map_full(self):
        per, w = off.map_nutriments({
            "energy-kcal_100g": 539, "proteins_100g": 6.3, "carbohydrates_100g": 57.5,
            "fat_100g": 30.9, "sugars_100g": 56.3, "sodium_100g": 0.0428})
        self.assertEqual(per["kcal"], 539)
        self.assertEqual(per["sodium_mg"], 43)
        self.assertIsNone(per["fiber"])
        self.assertEqual(w, [])

    def test_map_kj_fallback_and_missing(self):
        per, w = off.map_nutriments({"energy-kj_100g": 418.4, "salt_100g": 1.0})
        self.assertEqual(per["kcal"], 100)
        self.assertEqual(per["sodium_mg"], 400)
        self.assertTrue(any("kJ" in x for x in w))
        self.assertTrue(any("mancanti" in x for x in w))

    def test_slug(self):
        self.assertEqual(off.slug("Barilla_Spaghetti n°5"), "barilla_spaghetti_n_5")


if __name__ == "__main__":
    unittest.main()
