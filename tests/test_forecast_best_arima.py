import unittest
import numpy as np

from statcraft.arima import forecast_best_arima
from statcraft.app import Presenter, format_entry
from statcraft.model import Column, Worksheet


class ForecastBestArimaTests(unittest.TestCase):
    @staticmethod
    def series(seasonal=False):
        rng = np.random.default_rng(7)
        data = rng.normal(size=100)
        lag = 4 if seasonal else 1
        for i in range(lag, len(data)):
            data[i] += .8 * data[i - lag]
        return data.tolist()

    def test_bic_ranking_and_forecasts(self):
        result = forecast_best_arima(self.series(), max_p=2, max_q=0,
                                     criterion="BIC", forecasts=3)
        self.assertEqual(result["p"], 1)
        self.assertEqual(result["model_selection"][0]["p"], 1)
        self.assertLess(result["model_selection"][0]["BIC"], result["model_selection"][1]["BIC"])
        self.assertEqual(len(result["forecasts"]), 3)
        self.assertTrue(result["residual_diagnostics"])
        self.assertTrue(all(f["lower"] < f["forecast"] < f["upper"] for f in result["forecasts"]))

    def test_seasonal_search_and_presenter_rerun(self):
        presenter = Presenter()
        presenter.worksheet = Worksheet("Seasonal", [Column("Response", values=self.series(True))])
        entry = presenter.arima(settings={"series_index": 0, "search": True, "max_p": 1,
                                          "max_q": 0, "max_P": 1, "S": 4, "forecasts": 3})
        self.assertEqual(entry["result"]["P"], 1)
        self.assertIn("Model Selection", format_entry(entry))
        self.assertEqual(presenter.rerun_result(entry)["result"]["P"], 1)

    def test_interior_gap_is_rejected(self):
        values = self.series()
        values[10] = None
        with self.assertRaisesRegex(ValueError, "missing"):
            forecast_best_arima(values)
