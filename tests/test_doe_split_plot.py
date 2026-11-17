import unittest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from statcraft.doe_split_plot import create_split_plot_design, analyze_split_plot
from statcraft.doe_dialogs import CreateFactorialDialog
from statcraft.doe_analysis_dialogs import BuildAnalyzeSplitPlotDialog
from statcraft.app import Presenter
from statcraft.model import Column


class SplitPlotDesignTests(unittest.TestCase):
    def test_create_split_plot_design_structure_and_wp_grouping(self):
        ws = create_split_plot_design(
            hard_factors=[{"name": "Temp", "levels": [100, 150]}],
            easy_factors=[{"name": "Time", "levels": [10, 20]}],
            replicates=2,
            seed=42,
        )
        headers = [c.name for c in ws.columns]
        self.assertIn("WP", headers)
        self.assertIn("StdOrder", headers)
        self.assertIn("RunOrder", headers)
        self.assertIn("PtType", headers)
        self.assertEqual(headers[-1], "Y")
        self.assertEqual(ws.row_count, 8)
        self.assertEqual(ws.columns[-1].values, [None] * 8)

        # Hard factor must be constant within every WP block
        wp_idx = headers.index("WP")
        temp_idx = headers.index("Temp")
        by_wp = {}
        for r in range(ws.row_count):
            row = ws.row(r)
            by_wp.setdefault(row[wp_idx], set()).add(row[temp_idx])
        self.assertEqual(len(by_wp), 4)
        for wp, temps in by_wp.items():
            self.assertEqual(len(temps), 1, f"WP {wp} has varying hard factor levels: {temps}")

    def test_create_split_plot_supports_low_high_and_validation(self):
        ws = create_split_plot_design(
            hard_factors=[{"name": "A", "low": -1, "high": 1}],
            easy_factors=[{"name": "B", "low": 10, "high": 20}, {"name": "C", "levels": ["L", "H"]}],
            replicates=2,
            seed=7,
        )
        self.assertEqual(ws.row_count, 16)
        with self.assertRaises(ValueError):
            create_split_plot_design([], [{"name": "B", "levels": [1, 2]}])
        with self.assertRaises(ValueError):
            create_split_plot_design([{"name": "A", "levels": [1, 2]}], [])
        with self.assertRaises(ValueError):
            create_split_plot_design([{"name": "A", "levels": [1, 2]}], [{"name": "A", "levels": [3, 4]}])
        with self.assertRaises(ValueError):
            create_split_plot_design([{"name": "A", "levels": [1, 2]}], [{"name": "B", "levels": [3, 4]}], replicates=0)


class SplitPlotAnalysisTests(unittest.TestCase):
    def _balanced_sheet(self):
        # 2x2 split-plot with 2 replicates (4 whole plots, 8 runs)
        ws = create_split_plot_design(
            hard_factors=[{"name": "Temp", "levels": [100, 150]}],
            easy_factors=[{"name": "Time", "levels": [10, 20]}],
            replicates=2,
            seed=1,
        )
        # Assign deterministic response based on Temp, Time, and WP-level noise
        headers = [c.name for c in ws.columns]
        wp_col = ws.columns[headers.index("WP")].values
        temp_col = ws.columns[headers.index("Temp")].values
        time_col = ws.columns[headers.index("Time")].values

        # Whole-plot noise: +2 for first WP of each Temp, -2 for second WP of each Temp
        seen_by_temp = {}
        wp_noise = {}
        for wp, temp in zip(wp_col, temp_col):
            if wp not in wp_noise:
                idx = seen_by_temp.get(temp, 0)
                seen_by_temp[temp] = idx + 1
                wp_noise[wp] = 2.0 if idx == 0 else -2.0

        y = []
        for i in range(ws.row_count):
            t_code = 1.0 if temp_col[i] == 150 else -1.0
            m_code = 1.0 if time_col[i] == 20 else -1.0
            # Subplot noise: +/- 0.5
            sp_noise = 0.5 if (wp_noise[wp_col[i]] > 0) == (m_code > 0) else -0.5
            y.append(20.0 + 4.0 * t_code + 2.0 * m_code + 1.0 * t_code * m_code + wp_noise[wp_col[i]] + sp_noise)
        ws.columns[-1].values = y
        return ws

    def test_balanced_two_stratum_anova(self):
        ws = self._balanced_sheet()
        res = analyze_split_plot(ws, response=ws.columns[-1].name, whole_plot_col="WP", terms=["Temp", "Time", "Temp*Time"])
        self.assertEqual(res["whole_plot_df"], 2)
        self.assertEqual(res["subplot_df"], 2)
        self.assertTrue(res["balanced"])
        # Whole-plot error MS = 2 * (4 + 4 + 4 + 4) / 2 = 16.0
        self.assertAlmostEqual(res["whole_plot_ms"], 16.0, places=10)
        # Subplot error MS = 8 * 0.25 / 2 = 1.0
        self.assertAlmostEqual(res["subplot_ms"], 1.0, places=10)
        # Temp SS = 8 * 16 = 128, F = 128 / 16 = 8.0
        self.assertAlmostEqual(res["term_results"]["Temp"]["ss"], 128.0, places=10)
        self.assertAlmostEqual(res["term_results"]["Temp"]["f"], 8.0, places=10)
        # Time SS = 8 * 4 = 32, F = 32 / 1 = 32.0
        self.assertAlmostEqual(res["term_results"]["Time"]["ss"], 32.0, places=10)
        self.assertAlmostEqual(res["term_results"]["Time"]["f"], 32.0, places=10)

    def test_unbalanced_missing_cell_does_not_collapse_whole_plot_error(self):
        ws = self._balanced_sheet()
        # Drop one subplot observation (missing cell)
        ws.columns[-1].values[0] = None
        res = analyze_split_plot(ws, response="Y", whole_plot_col="WP", terms=["Temp", "Time", "Temp*Time"])
        self.assertFalse(res["balanced"])
        self.assertEqual(res["count"], 7)
        self.assertEqual(res["missing"], 1)
        # Whole-plot error df must remain 2 (4 whole plots - 2 whole-plot model params),
        # while subplot residual df drops from 2 to 1.
        self.assertEqual(res["whole_plot_df"], 2)
        self.assertEqual(res["subplot_df"], 1)
        self.assertGreater(res["whole_plot_ms"], res["subplot_ms"])

    def test_insufficient_whole_plots_or_df_raises_value_error(self):
        ws = create_split_plot_design(
            hard_factors=[{"name": "Temp", "levels": [100, 150]}],
            easy_factors=[{"name": "Time", "levels": [10, 20]}],
            replicates=1,
            seed=1,
        )
        ws.columns[-1].values = [10.0, 12.0, 14.0, 16.0]
        with self.assertRaisesRegex(ValueError, "whole-plot"):
            analyze_split_plot(ws, response="Y", whole_plot_col="WP", terms=["Temp", "Time", "Temp*Time"])


class SplitPlotDialogAndPresenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from statcraft.verification_fonts import load_verification_fonts
        load_verification_fonts(cls.app)

    def setUp(self):
        self.dialogs = []

    def tearDown(self):
        for dlg in self.dialogs:
            dlg.close()
        self.app.processEvents()

    def test_presenter_create_and_analyze_split_plot(self):
        p = Presenter()
        entry = p.create_split_plot_design(
            hard_factors=[{"name": "Temp", "levels": [100, 150]}],
            easy_factors=[{"name": "Time", "levels": [10, 20]}],
            replicates=2,
            seed=11,
        )
        self.assertEqual(entry["result"]["whole_plots"], 4)
        self.assertEqual(p.worksheet.row_count, 8)
        p.worksheet.columns[-1].values = [12.1, 14.3, 18.0, 20.2, 11.9, 14.1, 17.8, 20.4]
        fit = p.analyze_split_plot(response="Y", whole_plot_col="WP", terms=["Temp", "Time", "Temp*Time"])
        self.assertEqual(fit["result"]["whole_plot_df"], 2)
        self.assertEqual(fit["result"]["subplot_df"], 2)

    def test_create_factorial_dialog_split_plot_option_enabled_and_validates(self):
        dlg = CreateFactorialDialog(None)
        self.dialogs.append(dlg)
        dlg.show()
        self.app.processEvents()
        split_radio = dlg.design_types[2]
        self.assertTrue(split_radio.isEnabled())
        split_radio.setChecked(True)
        self.app.processEvents()
        ok_btn = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
        QTest.mouseClick(ok_btn, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertTrue(dlg.is_split_plot())
        self.assertIn("hard_factors", dlg.parameters)
        self.assertIn("easy_factors", dlg.parameters)

    def test_build_analyze_split_plot_dialog_autofills_and_validates(self):
        ws = create_split_plot_design(
            hard_factors=[{"name": "Temp", "levels": [100, 150]}],
            easy_factors=[{"name": "Time", "levels": [10, 20]}],
            replicates=2,
            seed=5,
        )
        ws.columns[-1].values = [12.1, 14.3, 18.0, 20.2, 11.9, 14.1, 17.8, 20.4]
        dlg = BuildAnalyzeSplitPlotDialog(ws)
        self.dialogs.append(dlg)
        dlg.show()
        self.app.processEvents()
        self.assertIn("WP", dlg.controls["whole_plot_index"].text())
        dlg.controls["response_index"].setText("Y")
        ok_btn = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
        QTest.mouseClick(ok_btn, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dlg.parameters["whole_plot_col"], "WP")
        self.assertEqual(dlg.parameters["response"], "Y")
