"""Regression tests for StatCraft v121.2.27 live Windows / Minitab 22 / Excel QA fixes."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

import openpyxl
from PySide6.QtCore import QCoreApplication, QEvent, QRect, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton, QRadioButton

from statcraft import settings_scope
from statcraft.app import Presenter, format_entry
from statcraft.capability_dialogs import CapabilityDialog
from statcraft.connect_hub import FlowLayout, StatCraftAnalysisBar
from statcraft.doe_custom_dialog import DefineCustomFactorialDialog
from statcraft.doe_dialogs import AnalyzeFactorialDialog, CreateFactorialDialog
from statcraft.histogram_dialogs import HistogramDialog
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.oneway_dialogs import OneWayAnovaDialog
from statcraft.subgroup_control_dialogs import XbarRChartDialog
from statcraft.two_sample_t_dialogs import TwoSampleTDialog, TwoSampleTOptionsDialog
from statcraft.two_sample_t_engine import two_sample_t_settings
from statcraft.xlsx_import import inspect_xlsx
from statcraft.xlsx_import_dialog import ExcelImportPreviewDialog
from statcraft.xlsx_verification import supports as xlsx_supports, write_verification


_APP = QApplication.instance() or QApplication([])


class _FakeScreen:
    def __init__(self, width: int = 1280, height: int = 672):
        self._rect = QRect(0, 0, width, height)

    def availableGeometry(self) -> QRect:
        return self._rect


def _sample_worksheet() -> Worksheet:
    return Worksheet(
        "Sample24",
        [
            Column("Length", "number", [10.0 + (i % 5) * 0.12 for i in range(24)]),
            Column("Width", "number", [5.0 + (i % 3) * 0.08 for i in range(24)]),
            Column("Line", "text", ["A" if i % 2 == 0 else "B" for i in range(24)]),
            Column("Lot", "text", [f"L{i // 4 + 1}" for i in range(24)]),
        ],
    )


class LiveQaFixesV121227Tests(unittest.TestCase):
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
        p.worksheet = ws or _sample_worksheet()
        return ModernWindow(p)

    def _close_window(self, win: ModernWindow):
        win.presenter.dirty = False
        win.presenter._results_dirty = False
        win.close()
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _APP.processEvents()

    def test_01_excel_import_preview_height_clamped_and_import_notice_fixed(self):
        xlsx_path = Path(self._tmp.name) / "verify_xbar_s.xlsx"
        wb = openpyxl.Workbook()
        ws1 = wb.active
        ws1.title = "Verification"
        ws1.append(["Metric", "Status"])
        ws1.append(["Xbar", "PASS"])
        ws2 = wb.create_sheet("Inputs")
        ws2.append(["Subgroup", "Diam"])
        ws2.append(["L1", 10.1])
        ws2.append(["L1", 10.2])
        ws3 = wb.create_sheet("Calculations")
        ws3.append(["Mean", "Range"])
        ws3.append([10.15, 0.1])
        wb.save(xlsx_path)

        win = self._new_window()
        try:
            fake_screen = _FakeScreen(1280, 672)
            with patch.object(QGuiApplication, "primaryScreen", return_value=fake_screen), patch.object(
                win, "screen", return_value=fake_screen
            ):
                info = inspect_xlsx(xlsx_path)
                dlg = ExcelImportPreviewDialog(info, win)
                dlg.show()
                _APP.processEvents()
                try:
                    self.assertLessEqual(dlg.height(), 672 - 48)
                    self.assertLessEqual(dlg.buttons.geometry().bottom(), dlg.height())
                    self.assertTrue(dlg.error_label.isHidden())
                finally:
                    dlg.validate_and_accept()
                    dlg.deleteLater()

            notices = win.load_imported_worksheets(
                dlg.imported_worksheets, source_path=str(xlsx_path)
            )
            joined = "\n".join(notices)
            self.assertIn("Imported Excel workbook", joined)
            self.assertIn("verify_xbar_s.xlsx", joined)
            self.assertNotIn("StatCraft-authored MPX project", joined)
            self.assertEqual(win.result_title.text(), "Excel workbook imported")
        finally:
            self._close_window(win)

    def test_02_window_screen_clamp_and_compact_r_translator_flow_wrapping(self):
        fake_screen = _FakeScreen(1280, 672)
        win = self._new_window()
        try:
            with patch.object(win, "screen", return_value=fake_screen), patch.object(
                QGuiApplication, "primaryScreen", return_value=fake_screen
            ):
                win.resize(1400, 900)
                win._clamp_to_available_screen()
                self.assertLessEqual(win.width(), 1280)
                self.assertLessEqual(win.height(), 672 - 38)

            # Compact 914px window width matching Nov 23 live capture
            win.resize(914, 620)
            entry = win.presenter.two_sample_t(
                settings={"data_format": 0, "samples_col": 0, "sample_ids_col": 2}
            )
            win.show_result(entry)
            win.show()
            _APP.processEvents()

            report_scroll = win.result_tabs.widget(0)
            bar = report_scroll.content.findChild(StatCraftAnalysisBar)
            self.assertIsNotNone(bar)
            flow_layouts = [
                bar.layout().itemAt(i).layout()
                for i in range(bar.layout().count())
                if isinstance(bar.layout().itemAt(i).layout(), FlowLayout)
            ]
            self.assertEqual(len(flow_layouts), 1)
            for btn in bar.findChildren(QPushButton):
                self.assertLessEqual(btn.geometry().right(), bar.width() + 2)
        finally:
            self._close_window(win)

    def test_03_auto_error_labels_hidden_until_error_across_dialogs(self):
        win = self._new_window()
        try:
            dlg = CreateFactorialDialog(win)
            self.assertTrue(dlg.error.isHidden())
            sub_hidden_results = []

            def accept_designs():
                child = _APP.activeModalWidget()
                errs = [l for l in child.findChildren(QLabel) if l.objectName() == "error"]
                sub_hidden_results.append(("designs", all(l.isHidden() for l in errs), len(errs)))
                child.accept()

            QTimer.singleShot(0, accept_designs)
            dlg.designs()
            dlg.error.setText("Temporary message")
            self.assertFalse(dlg.error.isHidden())
            dlg.error.clear()
            self.assertTrue(dlg.error.isHidden())

            def inspect_factors():
                child = _APP.activeModalWidget()
                errs = [l for l in child.findChildren(QLabel) if l.objectName() == "error"]
                sub_hidden_results.append(("factors", all(l.isHidden() for l in errs), len(errs)))
                child.reject()

            QTimer.singleShot(0, inspect_factors)
            dlg.factor_settings()

            def inspect_options():
                child = _APP.activeModalWidget()
                errs = [l for l in child.findChildren(QLabel) if l.objectName() == "error"]
                seed_edits = [e for e in child.findChildren(QLineEdit) if "automatic" in e.placeholderText().lower()]
                sub_hidden_results.append(("options", all(l.isHidden() for l in errs), len(seed_edits)))
                if seed_edits:
                    self.assertGreaterEqual(seed_edits[0].minimumWidth(), 200)
                child.reject()

            QTimer.singleShot(0, inspect_options)
            dlg.options()
            dlg.deleteLater()

            self.assertEqual(len(sub_hidden_results), 3)
            for name, all_hidden, count in sub_hidden_results:
                self.assertTrue(all_hidden, name)
                self.assertGreaterEqual(count, 1, name)

            for make_dlg in (
                lambda: DefineCustomFactorialDialog(win, win.presenter.worksheet),
                lambda: TwoSampleTDialog(win.presenter.worksheet, win),
                lambda: OneWayAnovaDialog(win),
                lambda: CapabilityDialog(win.presenter.worksheet, win),
                lambda: XbarRChartDialog(win),
                lambda: HistogramDialog(win, win.presenter.worksheet, "simple"),
                lambda: AnalyzeFactorialDialog(win, win.presenter.worksheet),
            ):
                d = make_dlg()
                errs = [l for l in d.findChildren(QLabel) if l.objectName() == "error"]
                self.assertTrue(errs, type(d).__name__)
                for err in errs:
                    self.assertTrue(err.isHidden(), type(d).__name__)
                d.deleteLater()
        finally:
            self._close_window(win)

    def test_04_create_factorial_defining_relation_option_and_output(self):
        win = self._new_window()
        try:
            dlg = CreateFactorialDialog(win)
            # Confirm 3-factor default half-fraction (4 runs, Res III)
            def accept_half_fraction():
                child = _APP.activeModalWidget()
                child.accept()

            QTimer.singleShot(0, accept_half_fraction)
            dlg.designs()
            self.assertTrue(dlg._has_fractional_generators())

            def choose_full_defining():
                child = _APP.activeModalWidget()
                def_rb = next(
                    rb
                    for rb in child.findChildren(QRadioButton)
                    if "defining relation" in rb.text().lower()
                )
                self.assertTrue(def_rb.isEnabled())
                def_rb.setChecked(True)
                child.accept()

            QTimer.singleShot(0, choose_full_defining)
            dlg.results()
            self.assertEqual(dlg.result_level, "full_defining")
            dlg.validate()
            self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted, dlg.error.text())

            entry = win.presenter.create_factorial(**dlg.parameters)
            self.assertIsNotNone(entry)
            self.assertIn("I =", entry["result"].get("defining_relation", ""))
            rep = format_entry(entry)
            self.assertIn("Defining relation", rep)
            self.assertIn("Design Table:", rep)
        finally:
            self._close_window(win)

    def test_05_two_sample_options_dropdown_width_and_everyday_var_filters(self):
        opt = TwoSampleTOptionsDialog(two_sample_t_settings())
        opt.show()
        _APP.processEvents()
        try:
            self.assertGreaterEqual(opt.width(), 450)
            full_text = "Difference ≠ hypothesized difference"
            text_w = opt.alt_combo.fontMetrics().horizontalAdvance(full_text)
            self.assertGreaterEqual(opt.alt_combo.width(), text_w + 20)
        finally:
            opt.deleteLater()

        win = self._new_window()
        try:
            ts = TwoSampleTDialog(win.presenter.worksheet, win)
            self.assertEqual([ts.var_list.item(i).text() for i in range(ts.var_list.count())], ["C1   Length", "C2   Width"])
            ts.var_filter.setText("wid")
            self.assertEqual([ts.var_list.item(i).text() for i in range(ts.var_list.count())], ["C2   Width"])
            ts.var_filter.clear()
            self.assertEqual(ts.var_list.count(), 2)
            ts.deleteLater()

            ow = OneWayAnovaDialog(win)
            ow.var_filter.setText("len")
            self.assertEqual(ow.available_list.count(), 1)
            self.assertIn("Length", ow.available_list.item(0).text())
            ow.deleteLater()

            xb = XbarRChartDialog(win)
            xb.var_filter.setText("wid")
            self.assertEqual(xb.col_list.count(), 1)
            self.assertIn("Width", xb.col_list.item(0).text())
            xb.deleteLater()

            cap = CapabilityDialog(win.presenter.worksheet, win)
            cap.var_filter.setText("len")
            self.assertEqual(cap.col_list.count(), 1)
            self.assertIn("Length", cap.col_list.item(0).text())
            cap.deleteLater()
        finally:
            self._close_window(win)

    def test_06_visual_qa_checked_mpx_gage_rr_excel_export_readonly(self):
        mpx_path = Path("artifacts/visual_qa/121.2.21-native/Visual-QA-Checked.mpx")
        if not mpx_path.is_file():
            self.skipTest("Visual-QA-Checked.mpx not present")
        before_sha = hashlib.sha256(mpx_path.read_bytes()).hexdigest()

        p = Presenter()
        p.load(mpx_path)
        gage_entry = next(
            (e for e in p.history if xlsx_supports(e) and e.get("recipe", {}).get("action") == "gage_rr"),
            None,
        )
        if gage_entry is None:
            # Ensure a Gage R&R sheet / run can be exported cleanly if none cached in history
            gage_ws_idx = next(
                (i for i, name in enumerate(getattr(p.native_project, "worksheet_names", [])) if "gage" in name.lower()),
                None,
            )
            if gage_ws_idx is not None:
                p.select_worksheet(gage_ws_idx)
            cols = [c.name.lower() for c in p.worksheet.columns]
            part_idx = next((i for i, n in enumerate(cols) if "part" in n), 0)
            op_idx = next((i for i, n in enumerate(cols) if "op" in n), 1)
            meas_idx = next((i for i, n in enumerate(cols) if "meas" in n or "diam" in n or "read" in n), len(cols) - 1)
            gage_entry = p.gage_rr(part_idx, op_idx, meas_idx, options={"tolerance": 10.0})

        out_xlsx = Path(self._tmp.name) / "gage_rr_reopened_verify.xlsx"
        write_verification(out_xlsx, p, gage_entry)
        self.assertTrue(out_xlsx.is_file())
        self.assertGreater(out_xlsx.stat().st_size, 5000)

        after_sha = hashlib.sha256(mpx_path.read_bytes()).hexdigest()
        self.assertEqual(before_sha, after_sha)


if __name__ == "__main__":
    unittest.main()
