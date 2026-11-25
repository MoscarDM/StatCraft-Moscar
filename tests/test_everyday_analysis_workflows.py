"""End-to-end desktop workflow, secondary-dialog, recall, MPX, and R checks for Cycle D."""
from __future__ import annotations

import copy
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QTableWidgetItem

from statcraft import settings_scope
from statcraft.app import Presenter, format_entry
from statcraft.boxplot_dialogs import BoxplotDialog, BoxplotTypeDialog
from statcraft.capability_dialogs import (
    CapabilityDialog,
    CapabilityEstimateDialog,
    CapabilityOptionsDialog,
)
from statcraft.descriptive_dialog import DisplayDescriptiveDialog
from statcraft.histogram_dialogs import HistogramDialog, HistogramTypeDialog
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.oneway_dialogs import OneWayAnovaDialog
from statcraft.r_verification import build_script, supports as r_supports
from statcraft.regression_dialog import FitRegressionModelDialog
from statcraft.subgroup_control_dialogs import (
    ControlChartOptionsDialog,
    XbarRChartDialog,
    XbarSChartDialog,
)
from statcraft.two_sample_t_dialogs import (
    TwoSampleTDialog,
    TwoSampleTGraphsDialog,
    TwoSampleTOptionsDialog,
)
from statcraft.variable_dialogs import ScatterDialog, ScatterTypeDialog


_APP = QApplication.instance() or QApplication([])


def _everyday_worksheet() -> Worksheet:
    """24-row synthetic manufacturing dataset across 7 everyday columns."""
    length = [
        9.82, 9.95, 9.78, 9.91,   # L1 (Low, A/B)
        10.04, 10.12, 9.98, 10.09,  # L2 (Low, B/C)
        9.88, 9.94, 10.01, 9.85,   # L3 (Low, C/A)
        10.22, 10.35, 10.18, 10.29,  # L4 (High, A/B)
        10.41, 10.30, 10.48, 10.36,  # L5 (High, B/C)
        10.15, 10.26, 10.19, 10.33,  # L6 (High, C/A)
    ]
    width = [
        4.95, 5.10, 4.88, 5.02,
        5.12, 5.20, 5.04, 5.15,
        4.91, 5.08, 5.18, 4.97,
        5.25, 5.38, 5.19, 5.31,
        5.42, 5.28, 5.50, 5.35,
        5.16, 5.29, 5.21, 5.34,
    ]
    setting = ["Low"] * 12 + ["High"] * 12
    line = [
        "A", "B", "A", "B",
        "B", "C", "B", "C",
        "C", "A", "C", "A",
        "A", "B", "A", "B",
        "B", "C", "B", "C",
        "C", "A", "C", "A",
    ]
    lot = [f"L{i // 4 + 1}" for i in range(24)]
    defects = [
        1, 0, 2, 1,
        0, 1, 1, 2,
        2, 1, 0, 1,
        1, 3, 2, 1,
        2, 1, 3, 2,
        1, 0, 2, 1,
    ]
    inspected = [50] * 24
    return Worksheet(
        "Everyday24",
        [
            Column("Length", "number", length),
            Column("Width", "number", width),
            Column("Setting", "text", setting),
            Column("Line", "text", line),
            Column("Lot", "text", lot),
            Column("Defects", "number", defects),
            Column("Inspected", "number", inspected),
        ],
    )


def _find_rscript() -> str | None:
    env = os.environ.get("STATCRAFT_QA_RSCRIPT")
    if env and Path(env).exists():
        return env
    found = shutil.which("Rscript")
    if found:
        return found
    default_win = Path(r"C:\Program Files\R\R-4.6.1\bin\x64\Rscript.exe")
    return str(default_win) if default_win.exists() else None


class EverydayAnalysisWorkflowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._sandbox_patch = patch.object(
            settings_scope, "_sandbox_workspace", Path(self._tmp.name)
        )
        self._recent_patch = patch.object(ModernWindow, "_add_recent_file", lambda *a, **k: None)
        self._sandbox_patch.start()
        self._recent_patch.start()

    def tearDown(self):
        self._recent_patch.stop()
        self._sandbox_patch.stop()
        self._tmp.cleanup()

    def _new_window(self, ws: Worksheet | None = None) -> ModernWindow:
        p = Presenter()
        p.worksheet = ws or _everyday_worksheet()
        return ModernWindow(p)

    def _close_window(self, win: ModernWindow):
        win.presenter.dirty = False
        win.presenter._results_dirty = False
        win.close()
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _APP.processEvents()

    def _run_r(self, script: str) -> str:
        exe = _find_rscript()
        if not exe:
            self.skipTest("Rscript not available")
        with tempfile.TemporaryDirectory() as folder:
            script_path = Path(folder) / "check.R"
            script_path.write_text(script, encoding="utf-8")
            proc = subprocess.run(
                [exe, "--vanilla", str(script_path)],
                cwd=folder,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            return proc.stdout

    def test_01_display_descriptive_statistics_workflow_recall_and_mpx(self):
        win = self._new_window()
        try:
            dlg = DisplayDescriptiveDialog(win.presenter.worksheet, win)
            avail = [dlg.available.item(i).text() for i in range(dlg.available.count())]
            self.assertIn('C1: "Length"', avail)
            self.assertFalse(any("Setting" in x for x in avail))

            # Focus By variables shows text columns
            dlg.activate("by_indices")
            by_avail = [dlg.available.item(i).text() for i in range(dlg.available.count())]
            self.assertTrue(any("Setting" in x for x in by_avail))
            self.assertTrue(any("Line" in x for x in by_avail))

            # Blank submission keeps dialog open with inline error and preserves By entry
            dlg.controls["by_indices"].setText("Setting")
            self.assertFalse(dlg.validate())
            self.assertTrue(dlg.error.text())
            self.assertEqual(dlg.controls["by_indices"].text(), "Setting")

            # Child Statistics Cancel vs OK
            dlg.controls["indices"].setText("Length")
            def cancel_stats():
                child = _APP.activeModalWidget()
                child.checks["iqr"].setChecked(True)
                child.reject()
            QTimer.singleShot(0, cancel_stats)
            dlg._open_statistics()
            self.assertNotIn("iqr", dlg._selected_stats)

            def accept_stats():
                child = _APP.activeModalWidget()
                child.checks["iqr"].setChecked(True)
                child.checks["range"].setChecked(True)
                child.accept()
            QTimer.singleShot(0, accept_stats)
            dlg._open_statistics()
            self.assertIn("iqr", dlg._selected_stats)

            # Main Cancel leaves history untouched
            dlg.reject()
            self.assertEqual(len(win.presenter.history), 0)

            # Valid run -> Report first with Minitab descriptive columns
            dlg2 = DisplayDescriptiveDialog(win.presenter.worksheet, win)
            dlg2.controls["indices"].setText("Length")
            dlg2.controls["by_indices"].setText("Setting")
            def accept_stats2():
                child = _APP.activeModalWidget()
                child.checks["iqr"].setChecked(True)
                child.accept()
            QTimer.singleShot(0, accept_stats2)
            dlg2._open_statistics()
            dlg2.validate()
            self.assertEqual(dlg2.result(), QDialog.DialogCode.Accepted, dlg2.error.text())
            params = dlg2.get_parameters()
            entry = win.presenter.describe_columns(**params)
            win.show_result(entry)
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Report")
            report_text = format_entry(entry)
            self.assertIn("Descriptive Statistics", report_text)
            self.assertIn("Length", report_text)
            self.assertIn("Setting", report_text)
            self.assertIn("SE Mean", report_text)
            self.assertIn("Q1", report_text)
            self.assertIn("Median", report_text)
            self.assertIn("IQR", report_text)

            # Recall remembers previous settings and MPX roundtrip works
            dlg3 = DisplayDescriptiveDialog(win.presenter.worksheet, win)
            self.assertIn("Length", dlg3.controls["indices"].text())
            self.assertIn("Setting", dlg3.controls["by_indices"].text())
            self.assertIn("iqr", dlg3._selected_stats)
            dlg3.deleteLater()

            mpx = Path(self._tmp.name) / "desc.mpx"
            win.presenter.save(mpx)
            reopened = Presenter()
            reopened.load(mpx)
            self.assertTrue(any(e.get("recipe", {}).get("action") == "describe_columns" for e in reopened.history))
        finally:
            self._close_window(win)

    def test_02_two_sample_t_inline_error_report_first_and_r_agreement(self):
        win = self._new_window()
        try:
            dlg = TwoSampleTDialog(win.presenter.worksheet, win)
            # C#   Name formatting + numeric filtering in sample fields
            labels = [dlg.var_list.item(i).text() for i in range(dlg.var_list.count())]
            self.assertIn("C1   Length", labels)
            self.assertFalse(any("Setting" in x for x in labels))
            self.assertIn("Sample 1 mean", dlg.diff_cue.text())

            # Stacked mode: focusing Sample IDs includes text columns + updates difference cue
            dlg.combo_data.setCurrentIndex(0)
            self.assertIn("first group mean", dlg.diff_cue.text())
            QApplication.sendEvent(dlg.ids_edit, QFocusEvent(QEvent.Type.FocusIn))
            id_labels = [dlg.var_list.item(i).text() for i in range(dlg.var_list.count())]
            self.assertTrue(any("Setting" in x for x in id_labels))

            # Invalid same-column submission shows inline error without losing inputs
            dlg.samples_edit.setText("C1")
            dlg.ids_edit.setText("C1")
            dlg._on_ok()
            self.assertIsNone(dlg.result_payload)
            self.assertFalse(dlg.error.isHidden())
            self.assertIn("distinct", dlg.error.text().lower())
            self.assertEqual(dlg.samples_edit.text(), "C1")

            # Child Options Cancel vs OK
            dlg.ids_edit.setText("Setting")
            def cancel_opts():
                child = _APP.activeModalWidget()
                self.assertIsInstance(child, TwoSampleTOptionsDialog)
                child.pooled_cb.setChecked(True)
                child.reject()
            QTimer.singleShot(0, cancel_opts)
            dlg._open_options()
            self.assertFalse(dlg.settings["assume_equal_variances"])

            def accept_opts():
                child = _APP.activeModalWidget()
                child.conf_edit.setText("99")
                child.hyp_edit.setText("0.0")
                child.pooled_cb.setChecked(True)
                child._accept()
            QTimer.singleShot(0, accept_opts)
            dlg._open_options()
            self.assertTrue(dlg.settings["assume_equal_variances"])
            self.assertEqual(dlg.settings["confidence_level"], 99.0)

            def cancel_graphs():
                child = _APP.activeModalWidget()
                self.assertIsInstance(child, TwoSampleTGraphsDialog)
                child.box_cb.setChecked(False)
                child.reject()
            QTimer.singleShot(0, cancel_graphs)
            dlg._open_graphs()
            self.assertTrue(dlg.settings["graphs"]["boxplot"])

            # Main Cancel does not record anything
            state_snapshot = dlg.get_state()
            dlg.reject()
            self.assertEqual(len(win.presenter.history), 0)

            # Reopen, restore state, execute stacked pooled & verify Report-first + tabBar visible
            dlg2 = TwoSampleTDialog(win.presenter.worksheet, win)
            dlg2.set_state(state_snapshot)
            dlg2._on_ok()
            self.assertIsNotNone(dlg2.result_payload)
            entry = win.presenter.two_sample_t(settings=dlg2.result_payload)
            win.show_result(entry)
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Report")
            self.assertFalse(win.result_tabs.tabBar().isHidden())
            tab_names = [win.result_tabs.tabText(i) for i in range(win.result_tabs.count())]
            self.assertIn("Graph", tab_names)
            rep = format_entry(entry)
            self.assertIn("Equal variances are assumed", rep)

            # Default Welch run + independent R 4.6.1 agreement
            welch_entry = win.presenter.two_sample_t(
                settings={"data_format": 0, "samples_col": 0, "sample_ids_col": 2}
            )
            wr = welch_entry["result"]
            low_vals = [v for v, g in zip(win.presenter.worksheet.columns[0].values, win.presenter.worksheet.columns[2].values) if g == "Low"]
            high_vals = [v for v, g in zip(win.presenter.worksheet.columns[0].values, win.presenter.worksheet.columns[2].values) if g == "High"]
            r_out = self._run_r(f"""
x <- c({','.join(map(str, low_vals))})
y <- c({','.join(map(str, high_vals))})
tt <- t.test(x, y, var.equal = FALSE, conf.level = 0.95)
cat(sprintf("DIFF=%.10f\\nT=%.10f\\nDF=%.10f\\nP=%.10f\\nLO=%.10f\\nHI=%.10f\\n",
            mean(x) - mean(y), unname(tt$statistic), unname(tt$parameter),
            tt$p.value, tt$conf.int[1], tt$conf.int[2]))
""")
            vals = dict(line.split("=", 1) for line in r_out.strip().splitlines() if "=" in line)
            self.assertAlmostEqual(wr["difference"], float(vals["DIFF"]), places=6)
            self.assertAlmostEqual(wr["t_statistic"], float(vals["T"]), places=6)
            self.assertAlmostEqual(wr["df"], float(vals["DF"]), places=6)
            self.assertAlmostEqual(wr["p_value"], float(vals["P"]), places=6)
            self.assertAlmostEqual(wr["ci_lower"], float(vals["LO"]), places=6)
            self.assertAlmostEqual(wr["ci_upper"], float(vals["HI"]), places=6)
        finally:
            self._close_window(win)

    def test_03_oneway_anova_secondary_dialogs_storage_and_r_agreement(self):
        win = self._new_window()
        try:
            dlg = OneWayAnovaDialog(win)
            # Response focus hides text cols; Factor focus includes Line/Setting/Lot
            items_resp = [dlg.available_list.item(i).text() for i in range(dlg.available_list.count())]
            self.assertFalse(any("Line" in x for x in items_resp))
            QApplication.sendEvent(dlg.factor_edit, QFocusEvent(QEvent.Type.FocusIn))
            items_fac = [dlg.available_list.item(i).text() for i in range(dlg.available_list.count())]
            self.assertTrue(any("Line" in x for x in items_fac))

            # Blank / invalid keeps error inline and preserves Factor field
            dlg.factor_edit.setText("Line")
            dlg.validate()
            self.assertFalse(dlg.error.isHidden())
            self.assertTrue(bool(dlg.error.text()))
            self.assertEqual(dlg.factor_edit.text(), "Line")
            self.assertEqual(len(win.presenter.history), 0)

            # Configure child Comparisons (Tukey + Dunnett) and Storage (Fits + Residuals)
            dlg.response_edit.setText("Length")
            def accept_cmp():
                child = _APP.activeModalWidget()
                child.chk_tukey.setChecked(True)
                child.chk_dunnett.setChecked(True)
                child.validate()
            QTimer.singleShot(0, accept_cmp)
            dlg.configure_comparisons()

            def accept_st():
                child = _APP.activeModalWidget()
                child.chk_fits.setChecked(True)
                child.chk_res.setChecked(True)
                child.validate()
            QTimer.singleShot(0, accept_st)
            dlg.configure_storage()

            # Valid submit -> Report first, stored FITS1/RESI1, Tukey & Dunnett present
            dlg.validate()
            self.assertIsNotNone(dlg.entry)
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Report")
            col_names = [c.name for c in win.presenter.worksheet.columns]
            self.assertIn("FITS", col_names)
            self.assertIn("RESI", col_names)
            rep = format_entry(dlg.entry)
            self.assertIn("Analysis of Variance", rep)
            self.assertIn("Tukey Pairwise Comparisons", rep)

            # R 4.6.1 agreement on oneway F and p-value
            y_vals = win.presenter.worksheet.columns[0].values
            f_vals = win.presenter.worksheet.columns[3].values
            r_out = self._run_r(f"""
y <- c({','.join(map(str, y_vals))})
grp <- factor(c({','.join('"' + str(x) + '"' for x in f_vals)}))
sm <- summary(aov(y ~ grp))[[1]]
cat(sprintf("F=%.10f\\nP=%.10f\\n", sm[1, "F value"], sm[1, "Pr(>F)"]))
""")
            vals = dict(line.split("=", 1) for line in r_out.strip().splitlines() if "=" in line)
            aov = dlg.entry["result"]["anova_table"]
            self.assertAlmostEqual(aov["f_value"], float(vals["F"]), places=6)
            self.assertAlmostEqual(aov["p_value"], float(vals["P"]), places=6)

            # Dialog recall
            dlg2 = OneWayAnovaDialog(win)
            self.assertEqual(dlg2.response_edit.text(), "C1")
            self.assertEqual(dlg2.factor_edit.text(), "C4")
            dlg2.deleteLater()
        finally:
            self._close_window(win)

    def test_04_fit_regression_coding_gating_equations_and_r_agreement(self):
        win = self._new_window()
        try:
            dlg = FitRegressionModelDialog(win)
            # Both Model… and Coding… disabled when predictors empty
            self.assertFalse(dlg.btn_model.isEnabled())
            self.assertFalse(dlg.btn_coding.isEnabled())

            dlg.controls["response_index"].setText("Length")
            dlg.controls["predictor_indices"].setText("Width")
            self.assertTrue(dlg.btn_model.isEnabled())
            self.assertFalse(dlg.btn_coding.isEnabled())

            dlg.controls["categorical_indices"].setText("Line")
            self.assertTrue(dlg.btn_coding.isEnabled())

            # Open Coding… Cancel vs OK (switch to (-1, 0, +1) with reference 'B')
            def cancel_coding():
                child = _APP.activeModalWidget()
                idx = child.scheme_combo.findData("minus_one_plus_one")
                child.scheme_combo.setCurrentIndex(idx)
                child.reject()
            QTimer.singleShot(0, cancel_coding)
            dlg.open_coding()
            self.assertEqual(dlg.options["coding"]["scheme"], "1_0")

            def accept_coding():
                child = _APP.activeModalWidget()
                child.scheme_combo.setCurrentIndex(child.scheme_combo.findData("minus_one_plus_one"))
                cbo = child.ref_combos["Line"]
                cbo.setCurrentIndex(cbo.findData("B"))
                child.validate()
            QTimer.singleShot(0, accept_coding)
            dlg.open_coding()
            self.assertEqual(dlg.options["coding"]["scheme"], "minus_one_plus_one")
            self.assertEqual(dlg.options["coding"]["references"]["Line"], "B")

            # Add interaction Width * Line via Model…
            def accept_model():
                child = _APP.activeModalWidget()
                child.term_checks[(0, 1)].setChecked(True)
                child.accept()
            QTimer.singleShot(0, accept_model)
            dlg.open_model()
            self.assertEqual(dlg.higher_terms, [(0, 1)])

            # Run regression -> lands on Report tab, shows (-1, 0, +1) coding and 3 per-level equations
            dlg.validate()
            self.assertIsNotNone(dlg.entry, dlg.error.text())
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Report")
            rep = format_entry(dlg.entry)
            self.assertIn("Categorical Predictor Coding ((-1, 0, +1))", rep)
            self.assertIn("Ref: B", rep)
            self.assertIn("Line = A:", rep)
            self.assertIn("Line = B:", rep)
            self.assertIn("Line = C:", rep)

            # Verify identical R-sq & fitted values against R lm() and continuous R workbench check
            y = win.presenter.worksheet.columns[0].values
            x = win.presenter.worksheet.columns[1].values
            g = win.presenter.worksheet.columns[3].values
            r_out = self._run_r(f"""
y <- c({','.join(map(str, y))})
w <- c({','.join(map(str, x))})
line <- factor(c({','.join('"' + str(v) + '"' for v in g)}), levels = c("A", "C", "B"))
contrasts(line) <- contr.sum(3)
m <- lm(y ~ w * line)
sm <- summary(m)
cat(sprintf("R2=%.10f\\nADJ=%.10f\\nS=%.10f\\nF0=%.10f\\n",
            sm$r.squared, sm$adj.r.squared, sm$sigma, fitted(m)[1]))
""")
            vals = dict(line.split("=", 1) for line in r_out.strip().splitlines() if "=" in line)
            rr = dlg.entry["result"]
            self.assertAlmostEqual(rr["r_squared"], float(vals["R2"]), places=6)
            self.assertAlmostEqual(rr["adjusted_r_squared"], float(vals["ADJ"]), places=6)
            self.assertAlmostEqual(rr["residual_stdev"], float(vals["S"]), places=6)
            self.assertAlmostEqual(rr["fitted"][0], float(vals["F0"]), places=6)

            # Continuous regression also verifies in StatCraft's built-in R workbench
            cont_entry = win.presenter.multiple_regression(0, [1])
            self.assertTrue(r_supports(cont_entry))
            script = build_script(win.presenter, cont_entry)
            self.assertIn("Verification: PASS", self._run_r(script))
        finally:
            self._close_window(win)

    def test_05_variant_first_graphs_histogram_boxplot_and_scatter(self):
        win = self._new_window()
        try:
            ws = win.presenter.worksheet

            # Histogram (With Fit and Groups)
            ht = HistogramTypeDialog(win)
            ht.mode_buttons["fit_groups"].click()
            self.assertEqual(ht.mode, "fit_groups")
            ht.deleteLater()

            hd = HistogramDialog(win, ws, "fit_groups")
            self.assertFalse(hd.validate())
            self.assertTrue(hd.error.text())
            hd.variables.setText("C1")
            hd.group.setText("C3")
            def edit_hscale():
                child = _APP.activeModalWidget()
                child.bins.setValue(8)
                child.accept()
            QTimer.singleShot(0, edit_hscale)
            hd.edit_scale()
            self.assertTrue(hd.validate())
            h_entry = win.presenter.histogram_graphs(**hd.settings())
            win.show_result(h_entry)
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")
            self.assertTrue(win.result_tabs.tabBar().isHidden())

            # Boxplot (With Groups)
            bt = BoxplotTypeDialog(win)
            bt.mode_buttons["one_groups"].click()
            bt.deleteLater()

            bd = BoxplotDialog(win, ws, "one_groups")
            bd.variables.setText("C1")
            bd.group.setText("C4")
            def edit_bview():
                child = _APP.activeModalWidget()
                child.controls["mean_symbol"].setChecked(True)
                child.accept()
            QTimer.singleShot(0, edit_bview)
            bd.edit_data_view()
            self.assertTrue(bd.validate())
            b_entry = win.presenter.boxplot_graphs(**bd.settings())
            win.show_result(b_entry)
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")
            self.assertTrue(win.result_tabs.tabBar().isHidden())

            # Scatterplot (With Groups)
            st = ScatterTypeDialog(win)
            st.mode_buttons["groups"].click()
            self.assertEqual(st.mode, "groups")
            st.deleteLater()

            sd = ScatterDialog(win, ws, "groups")
            sd.activate("group")
            s_group_items = [sd.available.item(i).text() for i in range(sd.available.count())]
            self.assertTrue(any("Setting" in x for x in s_group_items))
            sd.activate((0, 0))
            s_num_items = [sd.available.item(i).text() for i in range(sd.available.count())]
            self.assertFalse(any("Setting" in x for x in s_num_items))
            sd.validate()
            self.assertTrue(sd.error.text())
            sd.roles.setItem(0, 0, QTableWidgetItem("C1"))
            sd.roles.setItem(0, 1, QTableWidgetItem("C2"))
            sd.group_entry.setText("C3")
            sd.validate()
            self.assertTrue(sd.pairs)
            s_entry = win.presenter.scatter_plot(sd.pairs[0][1], sd.pairs[0][0], **sd.settings)
            win.show_result(s_entry)
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")
            self.assertTrue(win.result_tabs.tabBar().isHidden())
        finally:
            self._close_window(win)

    def test_06_subgroup_control_charts_inline_error_mpx_and_r_verification(self):
        win = self._new_window()
        try:
            dlg = XbarRChartDialog(win)
            # Active-field filtering: Measurements hides Lot; Subgroup size or ID shows Lot
            col_items = [dlg.col_list.item(i).text() for i in range(dlg.col_list.count())]
            self.assertFalse(any("Lot" in x for x in col_items))
            QApplication.sendEvent(dlg.sub_size_edit, QFocusEvent(QEvent.Type.FocusIn))
            id_items = [dlg.col_list.item(i).text() for i in range(dlg.col_list.count())]
            self.assertTrue(any("Lot" in x for x in id_items))

            # Invalid subgroup size shows inline error preserving entered measurement field
            dlg.resp_edit.setText("C1")
            dlg.sub_size_edit.setText("0")
            dlg.run_analysis()
            self.assertIsNone(dlg.entry)
            self.assertFalse(dlg.error.isHidden())
            self.assertTrue(bool(dlg.error.text()))
            self.assertEqual(dlg.resp_edit.text(), "C1")

            # Child Options Cancel vs OK
            def cancel_cc():
                child = _APP.activeModalWidget()
                child.ksigma_edit.setText("2.5")
                child.reject()
            QTimer.singleShot(0, cancel_cc)
            dlg._open_options()
            self.assertEqual(dlg.options["k_sigma"], 3.0)

            def accept_cc():
                child = _APP.activeModalWidget()
                child.ksigma_edit.setText("2.5")
                child.chk_perform_all.setChecked(True)
                child.validate()
            QTimer.singleShot(0, accept_cc)
            dlg._open_options()
            self.assertEqual(dlg.options["k_sigma"], 2.5)

            # Main Cancel safety
            hist_before = len(win.presenter.history)
            dlg.reject()
            self.assertEqual(len(win.presenter.history), hist_before)

            # Valid Xbar-R and Xbar-S runs + R 4.6.1 check + MPX roundtrip
            dlg2 = XbarRChartDialog(win)
            dlg2.resp_edit.setText("C1")
            dlg2.sub_size_edit.setText("C5")
            dlg2.run_analysis()
            self.assertIsNotNone(dlg2.entry)
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")
            self.assertFalse(win.result_tabs.tabBar().isHidden())
            self.assertTrue(r_supports(dlg2.entry))
            self.assertIn("Verification: PASS", self._run_r(build_script(win.presenter, dlg2.entry)))

            xs_dlg = XbarSChartDialog(win)
            xs_dlg.resp_edit.setText("C1")
            xs_dlg.sub_size_edit.setText("C5")
            xs_dlg.run_analysis()
            self.assertIsNotNone(xs_dlg.entry)
            self.assertTrue(r_supports(xs_dlg.entry))
            self.assertIn("Verification: PASS", self._run_r(build_script(win.presenter, xs_dlg.entry)))

            mpx = Path(self._tmp.name) / "subgroup.mpx"
            win.presenter.save(mpx)
            reopened = Presenter()
            reopened.load(mpx)
            self.assertEqual(len(reopened.history), 2)
        finally:
            self._close_window(win)

    def test_07_normal_capability_inline_validation_subdialogs_mpx_and_r_verification(self):
        win = self._new_window()
        try:
            dlg = CapabilityDialog(win.presenter.worksheet, win, analysis_mode="normal")
            items_num = [dlg.col_list.item(i).text() for i in range(dlg.col_list.count())]
            self.assertIn("C1   Length", items_num)
            self.assertFalse(any("Lot" in x for x in items_num))

            QApplication.sendEvent(dlg.edit_sub_size, QFocusEvent(QEvent.Type.FocusIn))
            items_sub = [dlg.col_list.item(i).text() for i in range(dlg.col_list.count())]
            self.assertTrue(any("Lot" in x for x in items_sub))
            self.assertTrue(dlg.chk_lsl_bound.toolTip())

            # Inline validation preserves entered values without modal popup
            dlg.edit_single_col.setText("Length")
            dlg.edit_sub_size.setText("Lot")
            dlg.edit_lsl.setText("11.0")
            dlg.edit_usl.setText("10.0")
            dlg._accept()
            self.assertIsNone(dlg.selected_params)
            self.assertFalse(dlg.error.isHidden())
            self.assertTrue(bool(dlg.error.text()))
            self.assertEqual(dlg.edit_single_col.text(), "Length")
            self.assertEqual(dlg.edit_sub_size.text(), "Lot")

            # Child Estimate… and Options… Cancel vs OK
            def cancel_est():
                child = _APP.activeModalWidget()
                self.assertIsInstance(child, CapabilityEstimateDialog)
                child.rb_rbar.setChecked(True)
                child.reject()
            QTimer.singleShot(0, cancel_est)
            dlg._open_estimate()
            self.assertEqual(dlg.options["estimate_method_gt1"], "pooled")

            def accept_est():
                child = _APP.activeModalWidget()
                child.rb_rbar.setChecked(True)
                child._accept()
            QTimer.singleShot(0, accept_est)
            dlg._open_estimate()
            self.assertEqual(dlg.options["estimate_method_gt1"], "rbar")

            def accept_opts():
                child = _APP.activeModalWidget()
                self.assertIsInstance(child, CapabilityOptionsDialog)
                child.edit_target.setText("10.1")
                child.chk_include_ci.setChecked(True)
                child._accept()
            QTimer.singleShot(0, accept_opts)
            dlg._open_options()
            self.assertEqual(dlg.options["target"], 10.1)
            self.assertTrue(dlg.options["include_ci"])

            # Main Cancel leaves history untouched
            dlg.reject()
            self.assertEqual(len(win.presenter.history), 0)

            # Valid capability execution + tabBar visible + R 4.6.1 check + MPX roundtrip
            dlg2 = CapabilityDialog(win.presenter.worksheet, win, analysis_mode="normal")
            dlg2.edit_single_col.setText("C1")
            dlg2.edit_sub_size.setText("C5")
            dlg2.edit_lsl.setText("9.2")
            dlg2.edit_usl.setText("11.0")
            def accept_opts2():
                child = _APP.activeModalWidget()
                child.edit_target.setText("10.1")
                child.chk_include_ci.setChecked(True)
                child._accept()
            QTimer.singleShot(0, accept_opts2)
            dlg2._open_options()
            dlg2._accept()
            self.assertIsNotNone(dlg2.selected_params)

            entry = win.presenter.normal_capability(settings=dlg2.selected_params)
            win.show_result(entry)
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")
            self.assertFalse(win.result_tabs.tabBar().isHidden())
            tab_names = [win.result_tabs.tabText(i) for i in range(win.result_tabs.count())]
            self.assertIn("Report", tab_names)
            rep = format_entry(entry)
            self.assertIn("StDev(Within)", rep)
            self.assertIn("Cpk", rep)
            self.assertIn("Ppk", rep)

            self.assertTrue(r_supports(entry))
            self.assertIn("Verification: PASS", self._run_r(build_script(win.presenter, entry)))

            mpx = Path(self._tmp.name) / "cap.mpx"
            win.presenter.save(mpx)
            reopened = Presenter()
            reopened.load(mpx)
            self.assertTrue(any(e.get("recipe", {}).get("action") == "normal_capability" for e in reopened.history))
        finally:
            self._close_window(win)


if __name__ == "__main__":
    unittest.main()
