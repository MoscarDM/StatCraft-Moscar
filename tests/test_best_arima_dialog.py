import unittest
from types import SimpleNamespace

from statcraft.modern_app import ModernWindow


class BestArimaDialogTests(unittest.TestCase):
    def test_best_arima_dialog_exposes_minitab_storage_choices(self):
        captured = {}
        presenter = SimpleNamespace(arima=lambda **kwargs: kwargs)
        owner = SimpleNamespace(
            presenter=presenter,
            _dialog=lambda title, selectors, fields, callback, note: captured.update(
                title=title, selectors=selectors, fields=fields, callback=callback, note=note
            ),
        )

        ModernWindow.best_arima_dialog(owner)

        field_keys = {field["key"] for field in captured["fields"]}
        self.assertTrue({"store_fits", "store_residuals", "store_forecasts"} <= field_keys)
        result = captured["callback"]({"series_index": 0, "store_fits": True,
                                        "store_residuals": True, "store_forecasts": True})
        self.assertEqual(result["settings"]["search"], True)
        self.assertTrue(result["settings"]["store_fits"])
        self.assertTrue(result["settings"]["store_residuals"])
        self.assertTrue(result["settings"]["store_forecasts"])


if __name__ == "__main__":
    unittest.main()
