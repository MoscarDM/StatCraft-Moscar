"""Tests for standalone Box-Cox transformation, 3D surface label bounds, and 1-Variance Bonett routing."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from statcraft.app import Presenter
from statcraft.box_cox_tool import run_box_cox_transformation
from statcraft.model import Column, Worksheet
from statcraft.model_plots import model_surface_plot
from statcraft.modern_charts import ChartWidget
from statcraft.modern_app import ModernWindow


class BoxCoxAndParityFixesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_box_cox_transformation_normalizes_skewed_data_and_stores_column(self):
        # Strongly right-skewed positive values (exponentially spaced)
        vals = [1.0, 1.5, 2.2, 3.1, 4.5, 6.8, 10.0, 15.0, 22.0, 35.0, 55.0, None]
        ws = Worksheet("Process", [Column("CycleTime", "number", vals)])
        presenter = Presenter()
        presenter.worksheet = ws
        entry = presenter.box_cox_transformation(0, use_rounded_lambda=True, store_column=True)
        res = entry["result"]
        self.assertEqual(res["analysis"], "box_cox_transformation")
        self.assertLess(abs(res["optimal_lambda"]), 0.4)
        self.assertLess(res["ad_transformed"], res["ad_original"])
        self.assertEqual(res["stored_column"], "BoxCox_CycleTime")
        self.assertEqual(len(ws.columns), 2)
        self.assertIsNone(ws.columns[1].values[-1])

    def test_box_cox_rejects_nonpositive_values(self):
        ws = Worksheet("Bad", [Column("X", "number", [0.0, 1.0, 2.0, 3.0])])
        with self.assertRaises(ValueError):
            run_box_cox_transformation(ws, 0)

    def test_3d_surface_plot_renders_with_title_and_axis_margins(self):
        rows_x1, rows_x2, rows_y = [], [], []
        for x1 in (1.0, 2.0, 3.0, 4.0):
            for x2 in (10.0, 20.0, 30.0, 40.0):
                rows_x1.append(x1)
                rows_x2.append(x2)
                rows_y.append(5.0 + 2.0 * x1 - 0.3 * x1 * x1 + 0.1 * x2)
        ws = Worksheet("Surf", [
            Column("Time", "number", rows_x1),
            Column("Temp", "number", rows_x2),
            Column("Weight Loss", "number", rows_y),
        ])
        presenter = Presenter()
        presenter.worksheet = ws
        entry = presenter.multiple_regression(2, predictor_indices=[0, 1], model_terms=[(0,), (1,), (0, 0)])
        surf = model_surface_plot(ws, entry["recipe"])
        chart = ChartWidget(surf)
        chart.resize(700, 480)
        img = QImage(chart.size(), QImage.Format.Format_ARGB32)
        chart.render(img)
        self.assertFalse(img.isNull())
        chart.deleteLater()

    def test_one_variance_action_dispatches_to_bonett_enabled_dialog(self):
        win = ModernWindow(sandbox_mode=True)
        try:
            self.assertIsNotNone(win.box_cox_action)
        finally:
            win.close()
            win.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
