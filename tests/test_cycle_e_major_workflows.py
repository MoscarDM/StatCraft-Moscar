"""End-to-end regression, visual-fix, workflow, and R 4.6.1 verification suite for v121.2.28 (Cycle E)."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

import openpyxl
from PySide6.QtCore import QCoreApplication, QEvent, QRect, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from statcraft import settings_scope
from statcraft.app import Presenter, format_entry
from statcraft.attribute_control_dialogs import AttributeChartDialog, AttributeOptionsDialog
from statcraft.boxplot_dialogs import BoxplotDialog
from statcraft.capability_nonnormal_dialogs import CapabilityNonnormalDialog
from statcraft.descriptive_dialog import _DescriptiveGraphsSubDialog, _DescriptiveStatisticsSubDialog
from statcraft.doe import create_factorial
from statcraft.doe_dialogs import AnalyzeFactorialDialog
from statcraft.doe_terms_dialog import FactorialTermsDialog
from statcraft.fitted_line_plot_dialog import (
    FittedLinePlotDialog,
    FittedLinePlotGraphsDialog,
    FittedLinePlotOptionsDialog,
    FittedLinePlotStorageDialog,
    default_fitted_line_plot_options,
)
from statcraft.gage_rr import settings as gage_settings
from statcraft.gage_rr_dialogs import GageRROptionsDialog
from statcraft.glm import settings as glm_settings
from statcraft.glm_dialogs import GeneralLinearModelDialog, ModelSettingsDialog, ModelTermsDialog
from statcraft.histogram_dialogs import HistogramDialog
from statcraft.imr_dialogs import IMRChartDialog, IMROptionsDialog
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.one_sample_t_dialogs import (
    OneSampleTDialog,
    OneSampleTGraphsDialog,
    OneSampleTOptionsDialog,
)
from statcraft.one_sample_t_engine import one_sample_t_settings
from statcraft.oneway import oneway_settings
from statcraft.oneway_dialogs import OneWayComparisonsDialog, OneWayOptionsDialog
from statcraft.paired_t_dialogs import (
    PairedTDialog,
    PairedTGraphsDialog,
    PairedTOptionsDialog,
)
from statcraft.paired_t_engine import paired_t_settings
from statcraft.sixpack_dialogs import (
    CapabilitySixpackDialog,
    CapabilitySixpackNonnormalDialog,
    SixpackTestsDialog,
)
from statcraft.xlsx_import import inspect_xlsx
from statcraft.xlsx_import_dialog import ExcelImportPreviewDialog


_APP = QApplication.instance() or QApplication([])


class _FakeScreen:
    def __init__(self, width: int = 1280, height: int = 672):
        self._rect = QRect(0, 0, width, height)

    def availableGeometry(self) -> QRect:
        return self._rect


def _find_rscript() -> str | None:
    env = os.environ.get("STATCRAFT_QA_RSCRIPT")
    if env and Path(env).exists():
        return env
    found = shutil.which("Rscript")
    if found:
        return found
    default_win = Path(r"C:\Program Files\R\R-4.6.1\bin\x64\Rscript.exe")
    return str(default_win) if default_win.exists() else None


def _cycle_e_worksheet() -> Worksheet:
    length = [
        9.82, 9.95, 9.78, 9.91,
        10.04, 10.12, 9.98, 10.09,
        9.88, 9.94, 10.01, 9.85,
        10.22, 10.35, 10.18, 10.29,
        10.41, 10.30, 10.48, 10.36,
        10.15, 10.26, 10.19, 10.33,
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
        "CycleE24",
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


class CycleEMajorWorkflowTests(unittest.TestCase):
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
        p.worksheet = ws or _cycle_e_worksheet()
        return ModernWindow(p)

    def _close_window(self, win: ModernWindow):
        win.presenter.dirty = False
        win.presenter._results_dirty = False
        win.close()
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _APP.processEvents()

    def _make_synthetic_xlsx(self) -> Path:
        xlsx_path = Path(self._tmp.name) / "synthetic_3sheet_8col.xlsx"
        wb = openpyxl.Workbook()
        ws1 = wb.active
        ws1.title = "Verification"
        ws1.append(["Check", "Status", "Notes", "C4", "C5", "C6", "C7", "C8"])
        ws1.append(["Mean", "PASS", "Within bounds", 1, 2, 3, 4, 5])
        ws2 = wb.create_sheet("Inputs")
        ws2.append(["Lot", "Diam", "Line", "C4", "C5", "C6", "C7", "C8"])
        ws2.append(["L1", 10.1, "A", 1, 2, 3, 4, 5])
        ws3 = wb.create_sheet("Calculations")
        ws3.append(["Stat", "Value", "Ref", "C4", "C5", "C6", "C7", "C8"])
        ws3.append(["Xbar", 10.1, 10.1, 1, 2, 3, 4, 5])
        wb.save(xlsx_path)
        return xlsx_path

    def test_01_excel_import_preview_strict_frame_clamp_real_fixture(self):
        fixture = Path("artifacts/visual_qa/121.2.21-native/verify_xbar_s.xlsx")
        xlsx_path = fixture if fixture.is_file() else self._make_synthetic_xlsx()
        info = inspect_xlsx(xlsx_path)

        win = self._new_window()
        try:
            for sw, sh in ((1280, 672), (913, 665)):
                fake_screen = _FakeScreen(sw, sh)
                with patch.object(QGuiApplication, "primaryScreen", return_value=fake_screen), patch.object(
                    win, "screen", return_value=fake_screen
                ):
                    dlg = ExcelImportPreviewDialog(info, win)
                    self.assertLessEqual(dlg.minimumSizeHint().width(), 620)
                    dlg.show()
                    _APP.processEvents()
                    try:
                        avail = fake_screen.availableGeometry()
                        self.assertLessEqual(dlg.height(), 540)
                        self.assertLessEqual(dlg.buttons.geometry().bottom(), dlg.height())
                        self.assertLessEqual(dlg.frameGeometry().bottom(), avail.bottom())
                        self.assertTrue(dlg.error_label.isHidden())
                    finally:
                        dlg.reject()
                        dlg.deleteLater()
        finally:
            self._close_window(win)

    def test_02_compact_report_no_horizontal_scrollbar_at_913px(self):
        mpx_path = Path("artifacts/visual_qa/121.2.21-native/Visual-QA-Checked.mpx")
        before_sha = hashlib.sha256(mpx_path.read_bytes()).hexdigest() if mpx_path.is_file() else None

        win = self._new_window()
        try:
            win.resize(913, 665)
            win.show()
            _APP.processEvents()

            if mpx_path.is_file():
                win.presenter.load(mpx_path)
                win.refresh()
                gage_entry = next(
                    e for e in win.presenter.history if "Gage" in e.get("title", "")
                )
                win.show_result(gage_entry, target_tab="Report")
                _APP.processEvents()
                view = win.result_tabs.widget(0)
                self.assertEqual(view.horizontalScrollBar().maximum(), 0)
                self.assertFalse(view.horizontalScrollBar().isVisible())
                self.assertTrue(view.verticalScrollBar().isVisible())
                self.assertEqual(before_sha, hashlib.sha256(mpx_path.read_bytes()).hexdigest())

            # Also verify Two-Sample t compact report on fresh worksheet
            win.presenter.new()
            win.presenter.worksheet = _cycle_e_worksheet()
            win.refresh()
            ts_entry = win.presenter.two_sample_t(
                settings={"data_format": 0, "samples_col": 0, "sample_ids_col": 2}
            )
            win.show_result(ts_entry, target_tab="Report")
            _APP.processEvents()
            ts_view = win.result_tabs.widget(0)
            self.assertEqual(ts_view.horizontalScrollBar().maximum(), 0)
            self.assertFalse(ts_view.horizontalScrollBar().isVisible())
        finally:
            self._close_window(win)

    def test_03_oneway_comparisons_and_appwide_auto_error_labels(self):
        win = self._new_window()
        try:
            comp = OneWayComparisonsDialog(win, oneway_settings(), ["Low", "High"])
            comp.show()
            _APP.processEvents()
            try:
                self.assertTrue(comp.error.isHidden())
                self.assertFalse(comp.cbo_control.isEnabled())
                self.assertFalse(comp.cbo_best.isEnabled())
                self.assertLess(comp.cbo_control.geometry().bottom(), comp.cbo_best.geometry().top())

                comp.chk_dunnett.setChecked(True)
                comp.chk_hsu.setChecked(True)
                self.assertTrue(comp.cbo_control.isEnabled())
                self.assertTrue(comp.cbo_best.isEnabled())

                comp.rate_edit.setText("99")
                comp.validate()
                self.assertFalse(comp.error.isHidden())
                self.assertIn("0.1%", comp.error.text())
                comp.error.clear()
                self.assertTrue(comp.error.isHidden())
            finally:
                comp.deleteLater()

            opt_ow = OneWayOptionsDialog(win, oneway_settings())
            try:
                self.assertTrue(opt_ow.error.isHidden())
                opt_ow.conf_edit.setText("200")
                opt_ow.validate()
                self.assertFalse(opt_ow.error.isHidden())
                opt_ow.error.clear()
                self.assertTrue(opt_ow.error.isHidden())
            finally:
                opt_ow.deleteLater()

            ws = win.presenter.worksheet
            dialogs = [
                FactorialTermsDialog(win, ws, [0, 1]),
                ModelTermsDialog(win, ["Length", "Width"], [[0], [1]]),
                IMRChartDialog(ws, win),
                IMROptionsDialog(win, {}),
                AttributeChartDialog(ws, chart_type="P", parent=win),
                AttributeOptionsDialog("P", {}, win),
                OneSampleTDialog(ws, win),
                OneSampleTOptionsDialog(one_sample_t_settings(), win),
                PairedTDialog(ws, win),
                PairedTOptionsDialog(paired_t_settings(), win),
                CapabilitySixpackDialog(ws, win),
                CapabilitySixpackNonnormalDialog(ws, win),
                CapabilityNonnormalDialog(ws, win),
            ]
            for d in dialogs:
                try:
                    errs = [l for l in d.findChildren(QLabel) if l.objectName() == "error"]
                    self.assertTrue(errs, f"Missing AutoErrorLabel in {type(d).__name__}")
                    for err in errs:
                        self.assertTrue(err.isHidden(), f"Visible error on init in {type(d).__name__}")
                finally:
                    d.deleteLater()
        finally:
            self._close_window(win)

    def test_04_one_sample_t_and_paired_t_workflows_and_r_verification(self):
        win = self._new_window()
        win.show()
        _APP.processEvents()
        rscript = _find_rscript()
        try:
            # 1. One-Sample t options dropdown width & main dialog workflow
            opt1 = OneSampleTOptionsDialog(one_sample_t_settings(), win)
            opt1.show()
            _APP.processEvents()
            try:
                tw1 = opt1.alt_combo.fontMetrics().horizontalAdvance("Mean ≠ hypothesized mean")
                self.assertGreaterEqual(opt1.alt_combo.width(), tw1 + 20)
                opt1.conf_edit.setText("150")
                opt1._accept()
                self.assertFalse(opt1.error.isHidden())
                self.assertEqual(opt1.conf_edit.text(), "150")
            finally:
                opt1.deleteLater()

            dlg1 = OneSampleTDialog(win.presenter.worksheet, win)
            try:
                self.assertEqual(dlg1.var_list.count(), 4)
                dlg1.var_filter.setText("wid")
                self.assertEqual([dlg1.var_list.item(i).text() for i in range(dlg1.var_list.count())], ["C2   Width"])
                dlg1.var_filter.clear()
                self.assertEqual(dlg1.var_list.count(), 4)

                # Invalid submission preserves entered hyp_edit and shows inline error
                dlg1.hyp_edit.setText("10.0")
                dlg1._on_ok()
                self.assertFalse(dlg1.error.isHidden())
                self.assertEqual(dlg1.hyp_edit.text(), "10.0")

                # Summarized mode disables picker & Graphs...
                dlg1.combo_data.setCurrentIndex(1)
                self.assertFalse(dlg1.var_filter.isEnabled())
                self.assertFalse(dlg1.var_list.isEnabled())
                self.assertFalse(dlg1.select_btn.isEnabled())
                self.assertFalse(dlg1.graphs_btn.isEnabled())

                # Switch back to raw columns and run
                dlg1.combo_data.setCurrentIndex(0)
                self.assertTrue(dlg1.var_filter.isEnabled())
                self.assertTrue(dlg1.graphs_btn.isEnabled())
                dlg1.sample_cols_edit.setText("C1")
                dlg1.hyp_edit.setText("10.0")
                dlg1._on_ok()
                self.assertEqual(dlg1.result(), QDialog.DialogCode.Accepted)
                entry1 = win.presenter.one_sample_t(settings=dlg1.result_payload)
                win.show_result(entry1)
                _APP.processEvents()
                self.assertTrue(win.result_tabs.tabBar().isVisible())
                self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Report")
                self.assertEqual(
                    [win.result_tabs.tabText(i) for i in range(win.result_tabs.count())],
                    ["Report", "Graph", "Text export"],
                )
            finally:
                dlg1.deleteLater()

            # 2. Paired t options dropdown width & main dialog workflow
            opt2 = PairedTOptionsDialog(paired_t_settings(), win)
            opt2.show()
            _APP.processEvents()
            try:
                tw2 = opt2.alt_combo.fontMetrics().horizontalAdvance("Difference ≠ hypothesized difference")
                self.assertGreaterEqual(opt2.alt_combo.width(), tw2 + 20)
                opt2.hyp_edit.setText("abc")
                opt2._accept()
                self.assertFalse(opt2.error.isHidden())
            finally:
                opt2.deleteLater()

            dlg2 = PairedTDialog(win.presenter.worksheet, win)
            try:
                dlg2.var_filter.setText("len")
                self.assertEqual([dlg2.var_list.item(i).text() for i in range(dlg2.var_list.count())], ["C1   Length"])
                dlg2.var_filter.clear()

                # Duplicate columns error preserves inputs
                dlg2.sample1_edit.setText("C1")
                dlg2.sample2_edit.setText("C1")
                dlg2._on_ok()
                self.assertFalse(dlg2.error.isHidden())
                self.assertEqual(dlg2.sample1_edit.text(), "C1")

                dlg2.sample2_edit.setText("C2")
                dlg2._on_ok()
                self.assertEqual(dlg2.result(), QDialog.DialogCode.Accepted)
                entry2 = win.presenter.paired_t(settings=dlg2.result_payload)
                win.show_result(entry2)
                _APP.processEvents()
                self.assertTrue(win.result_tabs.tabBar().isVisible())
                self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Report")
            finally:
                dlg2.deleteLater()

            # MPX roundtrip preserves both entries
            mpx_file = Path(self._tmp.name) / "t_tests.mpx"
            win.presenter.save(mpx_file)
            reopened = Presenter()
            reopened.load(mpx_file)
            actions = [e.get("recipe", {}).get("action") for e in reopened.history]
            self.assertIn("one_sample_t", actions)
            self.assertIn("paired_t", actions)

            # Independent R 4.6.1 parity check
            if rscript:
                ws = win.presenter.worksheet
                x1 = ",".join(str(v) for v in ws.columns[0].values)
                x2 = ",".join(str(v) for v in ws.columns[1].values)
                r_code = (
                    f"x1 <- c({x1})\n"
                    f"x2 <- c({x2})\n"
                    "t1 <- t.test(x1, mu = 10.0)\n"
                    "t2 <- t.test(x1, x2, paired = TRUE)\n"
                    "cat(sprintf('ONE:%.10f,%.6f,%.10f,%.10f,%.10f\\n', t1$statistic, t1$parameter, t1$p.value, t1$conf.int[1], t1$conf.int[2]))\n"
                    "cat(sprintf('PAIRED:%.10f,%.6f,%.10f,%.10f,%.10f\\n', t2$statistic, t2$parameter, t2$p.value, t2$conf.int[1], t2$conf.int[2]))\n"
                )
                proc = subprocess.run([rscript, "--vanilla", "-e", r_code], capture_output=True, text=True, check=True)
                vals = {}
                for line in proc.stdout.strip().splitlines():
                    tag, rest = line.split(":", 1)
                    vals[tag] = [float(v) for v in rest.split(",")]
                s1 = entry1["result"]["samples"][0]
                self.assertAlmostEqual(s1["t_statistic"], vals["ONE"][0], places=6)
                self.assertAlmostEqual(s1["df"], vals["ONE"][1], places=6)
                self.assertAlmostEqual(s1["p_value"], vals["ONE"][2], places=6)
                self.assertAlmostEqual(s1["ci_lower"], vals["ONE"][3], places=6)
                self.assertAlmostEqual(s1["ci_upper"], vals["ONE"][4], places=6)

                p_res = entry2["result"]
                self.assertAlmostEqual(p_res["t_statistic"], vals["PAIRED"][0], places=6)
                self.assertAlmostEqual(p_res["df"], vals["PAIRED"][1], places=6)
                self.assertAlmostEqual(p_res["p_value"], vals["PAIRED"][2], places=6)
                self.assertAlmostEqual(p_res["differences"]["ci_lower"], vals["PAIRED"][3], places=6)
                self.assertAlmostEqual(p_res["differences"]["ci_upper"], vals["PAIRED"][4], places=6)
        finally:
            self._close_window(win)

    def test_05_correlation_normality_fitted_line_glm_and_probability_plot(self):
        win = self._new_window()
        win.show()
        _APP.processEvents()
        rscript = _find_rscript()
        try:
            # Correlation: Report-first
            corr_entry = win.presenter.correlation([0, 1], method="Pearson")
            win.show_result(corr_entry)
            _APP.processEvents()
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Report")

            # Normality Test: tab bar stays visible
            norm_entry = win.presenter.normality(0, method="Anderson-Darling")
            win.show_result(norm_entry)
            _APP.processEvents()
            self.assertTrue(win.result_tabs.tabBar().isVisible())
            self.assertEqual(norm_entry["result"]["statistic_name"], "AD")

            # Fitted Line Plot: styled subdialogs + Graph + Residual Plots + Report + Text export visible
            fl_opts = FittedLinePlotOptionsDialog(win, default_fitted_line_plot_options())
            fl_grp = FittedLinePlotGraphsDialog(win, default_fitted_line_plot_options())
            fl_sto = FittedLinePlotStorageDialog(win, default_fitted_line_plot_options())
            for sd in (fl_opts, fl_grp, fl_sto):
                self.assertIn("QDialog", sd.styleSheet())
                sd.deleteLater()

            fl_dlg = FittedLinePlotDialog(win)
            fl_dlg.controls["response_index"].setText("C1")
            fl_dlg.controls["predictor_index"].setText("C2")
            fl_dlg.validate()
            fl_entry = fl_dlg.entry
            fl_dlg.deleteLater()
            win.show_result(fl_entry)
            _APP.processEvents()
            self.assertEqual(fl_entry["result"]["analysis"], "fitted_line_plot")
            self.assertTrue(win.result_tabs.tabBar().isVisible())
            fl_tabs = [win.result_tabs.tabText(i) for i in range(win.result_tabs.count())]
            self.assertEqual(fl_tabs, ["Report", "Graph", "Residual Plots", "Text export"])
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")

            # GLM: Report-first even with graphs='four', ModelTermsDialog AutoErrorLabel, Cancel preservation
            glm_dlg = GeneralLinearModelDialog(win)
            try:
                glm_dlg.controls["response_index"].setText("C1")
                glm_dlg.controls["factor_indices"].setText("C3 C4")
                glm_dlg.controls["covariate_indices"].setText("C2")
                orig_opts = dict(glm_dlg.options)

                def cancel_settings():
                    child = _APP.activeModalWidget()
                    self.assertIsInstance(child, ModelSettingsDialog)
                    child.controls["confidence"].setValue(80.0)
                    child.reject()

                QTimer.singleShot(0, cancel_settings)
                glm_dlg.option_buttons["Options"].click()
                self.assertEqual(glm_dlg.options["confidence"], orig_opts["confidence"])

                glm_dlg.options = dict(glm_settings(), graphs="four")
                glm_dlg.validate()
                self.assertEqual(glm_dlg.result(), QDialog.DialogCode.Accepted, glm_dlg.error.text())
                glm_entry = glm_dlg.entry
                self.assertTrue(win.result_tabs.tabBar().isVisible())
                self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Report")
            finally:
                glm_dlg.deleteLater()

            # HistogramDialog & BoxplotDialog live var_filter
            hdlg = HistogramDialog(win, win.presenter.worksheet, "fit_groups")
            try:
                hdlg.var_filter.setText("wid")
                self.assertEqual(hdlg.available.count(), 1)
                self.assertIn("Width", hdlg.available.item(0).text())
            finally:
                hdlg.deleteLater()

            bdlg = BoxplotDialog(win, win.presenter.worksheet, "one_groups")
            try:
                bdlg.var_filter.setText("len")
                self.assertEqual(bdlg.available.count(), 1)
                self.assertIn("Length", bdlg.available.item(0).text())
            finally:
                bdlg.deleteLater()

            # Probability Plot: Graph-first pure graph (tabBar hidden)
            prob_entry = win.presenter.expanded_graph("probability_plot", [0], None)
            win.show_result(prob_entry)
            _APP.processEvents()
            self.assertFalse(win.result_tabs.tabBar().isVisible())

            # R 4.6.1 correlation + GLM R-squared cross-check
            if rscript:
                ws = win.presenter.worksheet
                x1 = ",".join(str(v) for v in ws.columns[0].values)
                x2 = ",".join(str(v) for v in ws.columns[1].values)
                s_vals = ",".join(f"'{v}'" for v in ws.columns[2].values)
                l_vals = ",".join(f"'{v}'" for v in ws.columns[3].values)
                r_code = (
                    f"y <- c({x1}); w <- c({x2}); s <- factor(c({s_vals})); l <- factor(c({l_vals}))\n"
                    "ct <- cor.test(y, w)\n"
                    "fit <- lm(y ~ s + l + w)\n"
                    "cat(sprintf('CORR:%.10f,%.10f,%.10f,%.10f\\n', ct$estimate, ct$p.value, ct$conf.int[1], ct$conf.int[2]))\n"
                    "cat(sprintf('GLM:%.10f,%.10f\\n', summary(fit)$r.squared, summary(fit)$sigma))\n"
                )
                proc = subprocess.run([rscript, "--vanilla", "-e", r_code], capture_output=True, text=True, check=True)
                parsed = {}
                for line in proc.stdout.strip().splitlines():
                    k, v = line.split(":", 1)
                    parsed[k] = [float(item) for item in v.split(",")]
                c_rec = corr_entry["result"]["correlations"][0]
                self.assertAlmostEqual(c_rec["correlation"], parsed["CORR"][0], places=6)
                self.assertAlmostEqual(c_rec["p_value"], parsed["CORR"][1], places=6)
                self.assertAlmostEqual(c_rec["ci_low"], parsed["CORR"][2], places=6)
                self.assertAlmostEqual(c_rec["ci_high"], parsed["CORR"][3], places=6)
                self.assertAlmostEqual(glm_entry["result"]["r_squared"], parsed["GLM"][0], places=6)
                self.assertAlmostEqual(glm_entry["result"]["residual_stdev"], parsed["GLM"][1], places=6)
        finally:
            self._close_window(win)

    def test_06_imr_attribute_sixpack_nonnormal_gage_rr_and_analyze_factorial(self):
        win = self._new_window()
        win.show()
        _APP.processEvents()
        try:
            ws = win.presenter.worksheet

            # 1. IMRChartDialog & IMROptionsDialog
            imr_dlg = IMRChartDialog(ws, win)
            try:
                self.assertFalse(imr_dlg.btn_scale.isEnabled())
                self.assertFalse(imr_dlg.btn_labels.isEnabled())
                imr_dlg.var_filter.setText("wid")
                self.assertEqual(imr_dlg.var_list.count(), 1)
                imr_dlg.var_filter.clear()
                imr_dlg._on_ok()
                self.assertFalse(imr_dlg.error.isHidden())
                imr_dlg.edit_vars.setText("C1")
                imr_dlg._on_ok()
                self.assertEqual(imr_dlg.result(), QDialog.DialogCode.Accepted)
                imr_params = imr_dlg.selected_params
            finally:
                imr_dlg.deleteLater()

            imr_opt = IMROptionsDialog(win, {})
            try:
                imr_opt.sigma_edit.setText("-2")
                imr_opt._save_and_accept()
                self.assertFalse(imr_opt.error.isHidden())
            finally:
                imr_opt.deleteLater()

            imr_entry = win.presenter.imr_chart(settings=imr_params)
            win.show_result(imr_entry)
            _APP.processEvents()
            self.assertTrue(win.result_tabs.tabBar().isVisible())
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")

            # 2. AttributeChartDialog (P, U, Laney P') & AttributeOptionsDialog
            attr_params = None
            for ctype in ("P", "U", "P'"):
                adlg = AttributeChartDialog(ws, chart_type=ctype, parent=win)
                try:
                    adlg.var_filter.setText("def")
                    self.assertEqual(adlg.var_list.count(), 1)
                    adlg.var_filter.clear()
                    adlg.edit_vars.setText("C6")
                    if adlg.edit_subgroup is not None:
                        adlg.edit_subgroup.setText("C7")
                    adlg._validate_and_accept()
                    self.assertEqual(adlg.result(), QDialog.DialogCode.Accepted, adlg.error.text())
                    if ctype == "P":
                        attr_params = adlg.selected_params
                finally:
                    adlg.deleteLater()

            aopt = AttributeOptionsDialog("P", {}, win)
            try:
                aopt.prop_edit.setText("1.5")
                aopt._accept()
                self.assertFalse(aopt.error.isHidden())
            finally:
                aopt.deleteLater()

            attr_entry = win.presenter.attribute_control_chart(settings=attr_params)
            win.show_result(attr_entry)
            _APP.processEvents()
            self.assertTrue(win.result_tabs.tabBar().isVisible())
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")

            # 3. CapabilitySixpackDialog, CapabilitySixpackNonnormalDialog, CapabilityNonnormalDialog
            sxp = CapabilitySixpackDialog(ws, win)
            try:
                sxp.var_filter.setText("len")
                self.assertEqual(sxp.col_list.count(), 1)
                sxp.var_filter.clear()
                sxp.edit_single_col.setText("C1   Length")
                sxp.edit_sub_size.setText("4")
                sxp.edit_lsl.setText("11.0")
                sxp.edit_usl.setText("9.5")
                sxp._accept()
                self.assertFalse(sxp.error.isHidden())

                sxp.edit_lsl.setText("9.5")
                sxp.edit_usl.setText("11.0")
                sxp._accept()
                self.assertEqual(sxp.result(), QDialog.DialogCode.Accepted, sxp.error.text())
                self.assertEqual(sxp.selected_params["column_name"], "Length")
                state = sxp.get_state()
                sxp2 = CapabilitySixpackDialog(ws, win)
                sxp2.set_state(state)
                self.assertEqual(sxp2.edit_lsl.text(), "9.5")
                sxp2.deleteLater()
            finally:
                sxp.deleteLater()

            sxp_entry = win.presenter.normal_sixpack(settings=sxp.selected_params)
            win.show_result(sxp_entry)
            _APP.processEvents()
            self.assertTrue(win.result_tabs.tabBar().isVisible())
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")

            sxp_nn = CapabilitySixpackNonnormalDialog(ws, win)
            try:
                sxp_nn.var_filter.setText("len")
                self.assertEqual(sxp_nn.col_list.count(), 1)
                sxp_nn.edit_col.setText("C1   Length")
                sxp_nn.edit_lsl.setText("9.5")
                sxp_nn.edit_usl.setText("11.0")
                sxp_nn._accept()
                self.assertEqual(sxp_nn.result(), QDialog.DialogCode.Accepted, sxp_nn.error.text())
            finally:
                sxp_nn.deleteLater()

            cap_nn = CapabilityNonnormalDialog(ws, win)
            try:
                cap_nn.var_filter.setText("len")
                self.assertEqual(cap_nn.col_list.count(), 1)
                cap_nn.edit_single_col.setText("C1   Length")
                cap_nn.edit_lsl.setText("9.5")
                cap_nn.edit_usl.setText("11.0")
                cap_nn.edit_target.setText("not_a_number")
                cap_nn._on_ok()
                self.assertFalse(cap_nn.error.isHidden())
                cap_nn.edit_target.setText("10.1")
                cap_nn._on_ok()
                self.assertEqual(cap_nn.result(), QDialog.DialogCode.Accepted, cap_nn.error.text())
            finally:
                cap_nn.deleteLater()

            cap_nn_entry = win.presenter.capability_nonnormal(settings=cap_nn.selected_params)
            win.show_result(cap_nn_entry)
            _APP.processEvents()
            self.assertTrue(win.result_tabs.tabBar().isVisible())
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")

            # MPX roundtrip for Sixpack & Nonnormal Capability
            mpx_file = Path(self._tmp.name) / "cycle_e_quality.mpx"
            win.presenter.save(mpx_file)
            reopened = Presenter()
            reopened.load(mpx_file)
            self.assertIn("normal_sixpack", [e.get("recipe", {}).get("action") for e in reopened.history])
            self.assertIn("capability_nonnormal", [e.get("recipe", {}).get("action") for e in reopened.history])

            # 4. GageRROptionsDialog styled inline validation
            gopt = GageRROptionsDialog(win, gage_settings())
            try:
                self.assertIn("QDialog", gopt.styleSheet())
                gopt.controls["study_multiplier"].setText("-1")
                gopt.validate()
                self.assertFalse(gopt.error.isHidden())
            finally:
                gopt.deleteLater()

            # 5. AnalyzeFactorialDialog var_filter + FactorialTermsDialog hidden AutoErrorLabel + Effects Pareto landing
            doe_ws = create_factorial(
                [{"name": "A", "low": -1, "high": 1}, {"name": "B", "low": -1, "high": 1}],
                replicates=2,
                centers=0,
                randomize=False,
            )
            doe_ws.columns.append(
                Column("Yield", "number", [10.0, 12.0, 14.0, 18.0, 10.8, 11.7, 14.6, 17.9])
            )
            win.presenter.new()
            win.presenter.worksheet = doe_ws
            win.refresh()
            af_dlg = AnalyzeFactorialDialog(win, doe_ws)
            try:
                af_dlg.var_filter.setText("yie")
                self.assertEqual(af_dlg.available.count(), 1)
                self.assertIn("Yield", af_dlg.available.item(0).text())
                af_dlg.var_filter.clear()
                af_dlg.response.setText("C7")
                af_dlg.validate()
                self.assertEqual(af_dlg.result(), QDialog.DialogCode.Accepted, af_dlg.error.text())
                doe_entry = win.presenter.analyze_factorial(**af_dlg.parameters)
                win.show_result(doe_entry)
                _APP.processEvents()
                doe_tabs = [win.result_tabs.tabText(i) for i in range(win.result_tabs.count())]
                self.assertIn("Effects Pareto", doe_tabs)
                self.assertIn("Residual Plots", doe_tabs)
                self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")
                win.show_result(doe_entry, target_tab="Effects Pareto")
                _APP.processEvents()
                self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Effects Pareto")
            finally:
                af_dlg.deleteLater()
        finally:
            self._close_window(win)


if __name__ == "__main__":
    unittest.main()
