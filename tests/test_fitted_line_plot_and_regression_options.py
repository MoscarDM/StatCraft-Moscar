import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit

_app = QApplication.instance() or QApplication(sys.argv)


def _tab_titles(tab_widget):
    return [tab_widget.tabText(i) for i in range(tab_widget.count())]


class TestFittedLinePlotAndRegressionOptions(unittest.TestCase):
    def setUp(self):
        from statcraft.modern_app import ModernWindow

        self.win = ModernWindow()
        ws = self.win.presenter.worksheet
        ws.columns[0].name = "X"
        ws.columns[0].kind = "number"
        ws.columns[0].values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        ws.columns[1].name = "Y"
        ws.columns[1].kind = "number"
        ws.columns[1].values = [2.1, 4.3, 5.8, 8.2, 10.1, 11.7, 14.2, 19.5]
        self.win.refresh()

    def tearDown(self):
        self.win.presenter.dirty = False
        self.win.presenter._results_dirty = False
        self.win.close()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(self.win, QEvent.Type.DeferredDelete)

    def test_fitted_line_plot_residual_graphs_and_coefficients_storage(self):
        from statcraft.fitted_line_plot_dialog import FittedLinePlotDialog

        dlg = FittedLinePlotDialog(self.win)
        dlg.controls["response_index"].setText("Y")
        dlg.controls["predictor_index"].setText("X")
        dlg.options["graphs"] = "four"
        dlg.options["residuals_type"] = "standardized"
        dlg.options["storage"]["coefficients"] = True
        dlg.validate()
        self.assertIsNotNone(dlg.entry)
        self.win.show_result(dlg.entry)

        titles = _tab_titles(self.win.result_tabs)
        self.assertIn("Graph", titles)
        self.assertIn("Residual Plots", titles)

        # Coefficients (intercept + slope) stored in COEF1
        col_names = [c.name for c in self.win.presenter.worksheet.columns]
        self.assertIn("COEF1", col_names)
        coef_col = next(c for c in self.win.presenter.worksheet.columns if c.name == "COEF1")
        self.assertEqual(len(coef_col.values), 2)

        # None graph option must omit Residual Plots tab
        dlg_none = FittedLinePlotDialog(self.win)
        dlg_none.controls["response_index"].setText("Y")
        dlg_none.controls["predictor_index"].setText("X")
        dlg_none.options["graphs"] = "none"
        dlg_none.validate()
        self.win.show_result(dlg_none.entry)
        titles_none = _tab_titles(self.win.result_tabs)
        self.assertIn("Graph", titles_none)
        self.assertNotIn("Residual Plots", titles_none)

    def test_regression_residual_chart_supports_fits_and_residuals_type(self):
        from statcraft.regression_residual_chart import RegressionResidualChartWidget

        entry = self.win.presenter.fitted_line_plot(
            response_index=1,
            predictor_index=0,
            model_type="linear",
            options={"graphs": "fits", "residuals_type": "deleted"},
        )
        chart = RegressionResidualChartWidget(entry)
        self.assertEqual(len(chart.fitted), 8)
        self.assertEqual(len(chart.std_resids), 8)
        self.assertEqual(chart.std_resids, entry["result"]["del_residuals"])

    def test_fit_regression_model_results_options_filter_output(self):
        from statcraft.regression_dialog import FitRegressionModelDialog
        from statcraft.app import format_entry

        dlg = FitRegressionModelDialog(self.win)
        dlg.controls["response_index"].setText("Y")
        dlg.controls["predictor_indices"].setText("X")
        dlg.options["results"] = {
            "equation": False,
            "summary": False,
            "anova": True,
            "unusual": False,
        }
        dlg.validate()
        self.assertIsNotNone(dlg.entry)

        text = format_entry(dlg.entry)
        self.assertNotIn("Regression Equation", text)
        self.assertNotIn("Model Summary", text)
        self.assertIn("Analysis of Variance", text)
        self.assertNotIn("Fits and Diagnostics for Unusual Observations", text)

        # Also check report card content respects the options
        self.win.show_result(dlg.entry)
        report_widget = self.win.result_tabs.widget(0)
        texts = [w.text() for w in report_widget.findChildren(QLabel)] + [
            w.toPlainText() for w in report_widget.findChildren(QPlainTextEdit)
        ]
        joined = "\n".join(texts)
        self.assertNotIn("Regression Equation", joined)
        self.assertNotIn("Summary", joined)

    def test_rerun_keeps_saved_report_and_graph_options(self):
        from statcraft.app import Presenter
        from statcraft.regression_dialog import FitRegressionModelDialog

        dialog = FitRegressionModelDialog(self.win)
        dialog.controls["response_index"].setText("Y")
        dialog.controls["predictor_indices"].setText("X")
        dialog.options["graphs"] = "order"
        dialog.options["results"]["equation"] = False
        dialog.validate()
        entry = dialog.entry
        self.assertIsNotNone(entry, dialog.error.text())

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "regression.mpx"
            self.win.presenter.save(path)
            restored = Presenter()
            restored.load(path)
            saved = restored.history[-1]
            rerun = restored.rerun_result(saved)

        self.assertEqual(rerun["result"], saved["result"])
        self.assertIsNot(rerun["result"]["options"], saved["result"]["options"])

    def test_fitted_line_rejects_unestimable_polynomial(self):
        from statcraft.fitted_line_plot import fit_fitted_line_plot

        with self.assertRaisesRegex(ValueError, "rank-deficient"):
            fit_fitted_line_plot([1, 2, 1, 2, 1, 2], [1, 4, 2, 5, 3, 6], "quadratic")

    def test_fitted_line_residual_order_uses_original_rows(self):
        from statcraft.regression_residual_chart import RegressionResidualChartWidget

        self.win.presenter.worksheet.columns[1].values[2] = None
        entry = self.win.presenter.fitted_line_plot(1, 0)
        self.assertEqual(RegressionResidualChartWidget(entry).observation_order, [1, 2, 4, 5, 6, 7, 8])

    def test_fitted_line_residual_title_names_response(self):
        from statcraft.regression_residual_chart import RegressionResidualChartWidget

        self.win.presenter.worksheet.columns[1].name = "Reading"
        entry = self.win.presenter.fitted_line_plot(1, 0)
        self.assertEqual(RegressionResidualChartWidget(entry).response_name, "Reading")

    def test_fitted_line_and_intervals_are_stable_after_predictor_shift(self):
        import numpy as np

        from statcraft.fitted_line_plot import fit_fitted_line_plot

        x = list(range(8))
        y = [8, 8, 10, 14, 16, 16, 18, 22]
        raw = fit_fitted_line_plot(x, y)
        shifted = fit_fitted_line_plot([value + 10_000 for value in x], y)
        self.assertAlmostEqual(shifted["coefficients"][0]["coef"], -19_993)
        self.assertAlmostEqual(shifted["coefficients"][1]["coef"], 2)
        self.assertAlmostEqual(shifted["anova"]["error"]["ss"], 8)
        np.testing.assert_allclose(shifted["fits"], raw["fits"], atol=1e-8, rtol=0)
        for key in ("fit", "ci_low", "ci_high", "pi_low", "pi_high"):
            np.testing.assert_allclose(shifted["curve"][key], raw["curve"][key], atol=1e-8, rtol=0)


if __name__ == "__main__":
    unittest.main()
