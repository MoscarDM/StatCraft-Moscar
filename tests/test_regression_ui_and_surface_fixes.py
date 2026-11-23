"""Regression tests for Normal Probability Plot clipping, empty column filtering, and curved regression surfaces."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from statcraft.app import Presenter
from statcraft.model import Column, Worksheet
from statcraft.model_plots import model_contour_plot, model_surface_plot
from statcraft.regression_residual_chart import RegressionResidualChartWidget
from statcraft.variable_dialogs import ProcedureDialog


class RegressionUiAndSurfaceFixesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_normal_probability_plot_clips_reference_line_inside_panel(self):
        # Skewed residuals with an extreme outlier so the red reference line would overshoot top/bottom without clipping
        resids = [-0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 4.5]
        fits = [10.0 + i for i in range(len(resids))]
        chart = RegressionResidualChartWidget(
            {"result": {"standardized_residuals": resids, "fitted": fits, "response_name": "Weight Loss", "options": {"graphs": "normal"}}}
        )
        chart.resize(480, 320)
        img = QImage(chart.size(), QImage.Format.Format_ARGB32)
        chart.render(img)
        # Header title strip (y in 0..34) must have zero red line pixels (#dc2626 -> R>200, G<60, B<60)
        red_in_header = 0
        for y in range(0, 34):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.red() > 180 and c.green() < 80 and c.blue() < 80:
                    red_in_header += 1
        self.assertEqual(red_in_header, 0)
        chart.deleteLater()

    def test_empty_padding_columns_hidden_when_sheet_has_data(self):
        ws = Worksheet(
            name="Study",
            columns=[
                Column("Time", "number", [1.0, 2.0, 3.0]),
                Column("Temp", "number", [100.0, 110.0, 120.0]),
                Column("Weight Loss", "number", [5.0, 9.0, 14.0]),
                Column("C4", "number", []),
                Column("C5", "number", [None, None]),
                Column("C6", "text", ["", ""]),
            ],
        )
        dlg = ProcedureDialog(
            None,
            "Test",
            ws,
            selectors=[{"key": "y", "label": "Response:", "kinds": ("number",)}],
        )
        items = [dlg.available.item(i).text() for i in range(dlg.available.count())]
        self.assertEqual(len(items), 3)
        self.assertTrue(all("C4" not in it and "C5" not in it and "C6" not in it for it in items))
        dlg.deleteLater()

    def test_multiple_regression_quadratic_terms_produce_curved_surface_and_contour(self):
        # True quadratic surface: y = 10 + 2*x1 + 3*x2 - 1.5*x1^2 + 0.8*x2^2 + 0.5*x1*x2
        rows_x1, rows_x2, rows_y = [], [], []
        for x1 in (-2.0, -1.0, 0.0, 1.0, 2.0):
            for x2 in (-2.0, -1.0, 0.0, 1.0, 2.0):
                rows_x1.append(x1)
                rows_x2.append(x2)
                rows_y.append(10.0 + 2.0 * x1 + 3.0 * x2 - 1.5 * x1 * x1 + 0.8 * x2 * x2 + 0.5 * x1 * x2)
        ws = Worksheet(
            name="Curved",
            columns=[
                Column("Time", "number", rows_x1),
                Column("Temp", "number", rows_x2),
                Column("Weight Loss", "number", rows_y),
            ],
        )
        presenter = Presenter()
        presenter.worksheet = ws
        # model_terms: linear (0,), (1,), quadratic (0, 0), (1, 1), interaction (0, 1)
        entry = presenter.multiple_regression(
            2,
            predictor_indices=[0, 1],
            model_terms=[(0,), (1,), (0, 0), (1, 1), (0, 1)],
        )
        recipe = entry["recipe"]
        surf = model_surface_plot(ws, recipe)
        panel = surf["panels"][0]
        z_grid = panel["z_grid"]
        # Along row 0 (fixed y = -2), x varies from -2 to +2: quadratic term -1.5*x1^2 means curvature != 0
        z_mid = z_grid[0][len(z_grid[0]) // 2]
        z_left = z_grid[0][0]
        z_right = z_grid[0][-1]
        curvature = z_mid - 0.5 * (z_left + z_right)
        self.assertGreater(abs(curvature), 1.0, f"Expected curved surface, got flat plane (curvature={curvature})")

        # Exact value check at (x1=0, x2=0): center of grid should equal ~10.0
        c_idx = len(z_grid) // 2
        self.assertAlmostEqual(z_grid[c_idx][c_idx], 10.0, places=5)

        cont = model_contour_plot(ws, recipe)
        c_panel = cont["panels"][0]
        self.assertAlmostEqual(c_panel["z_grid"][len(c_panel["z_grid"]) // 2][len(c_panel["z_grid"]) // 2], 10.0, places=5)


if __name__ == "__main__":
    unittest.main()
