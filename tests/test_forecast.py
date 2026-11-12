import json
import unittest

from main import build_forecast, read_history


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.task = {
            "places": 2,
            "chart_size": 10,
            "size": {"edges": [2.0, 3.0, 4.0]},
        }
        self.marks = [
            {"ok": True, "rows": [
                {"rank": 1, "mint": "A", "market_cap_lamports": "1000000000000"},
                {"rank": 2, "mint": "B", "market_cap_lamports": "500000000000"},
                {"rank": 3, "mint": "C", "market_cap_lamports": "200000000000"},
            ]},
            {"ok": True, "rows": [
                {"rank": 1, "mint": "B", "market_cap_lamports": "900000000000"},
                {"rank": 2, "mint": "A", "market_cap_lamports": "800000000000"},
                {"rank": 3, "mint": "C", "market_cap_lamports": "250000000000"},
            ]},
        ]

    def test_forecast_schema_and_probability_bounds(self):
        forecast = build_forecast(self.task, self.marks)
        self.assertEqual(set(forecast), {"probabilities", "top5", "sizes"})
        self.assertEqual(len(forecast["top5"]), 2)
        self.assertEqual(len(set(forecast["top5"])), 2)
        for rows in (forecast["probabilities"], forecast["sizes"]):
            self.assertTrue(all(0.0 < row["p"] <= 1.0 for row in rows))
        for place in (1, 2):
            named_mass = sum(r["p"] for r in forecast["probabilities"] if r["place"] == place)
            size_mass = sum(r["p"] for r in forecast["sizes"] if r["place"] == place)
            self.assertLessEqual(named_mass, 1.0)
            self.assertAlmostEqual(size_mass, 1.0, places=4)

    def test_same_history_produces_identical_forecast(self):
        self.assertEqual(build_forecast(self.task, self.marks), build_forecast(self.task, self.marks))

    def test_reader_skips_failed_marks(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.ndjson"
            path.write_text(
                json.dumps({"ok": True, "rows": [{"rank": 1, "mint": "A", "market_cap_lamports": "1000000000000"}]})
                + "\n"
                + json.dumps({"ok": False, "rows": None})
                + "\n",
                encoding="utf-8",
            )
            marks = read_history(path)
            self.assertEqual(len(marks), 1)
            self.assertEqual(marks[0]["rows"][0]["mint"], "A")


if __name__ == "__main__":
    unittest.main()
