"""Gate 5 verification: Packaged workflow acceptance and open QA fixes."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from statcraft.app import Presenter
from statcraft.connect import create_connected_two_sample_t
from statcraft.connect_hub import StatCraftAnalysisBar
from statcraft.connect_report import generate_connected_report
from statcraft.dsd_chart import DSDParetoEffectsWidget
from statcraft.everyday_smoke import verify_packaged_acceptance
from statcraft.micro_innovations import StaleOutputBanner
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.r_universal_translator import generate_dataframe_r_code, translate_entry_to_r


_APP = QApplication.instance() or QApplication([])


class Gate5PackagedAcceptanceTests(unittest.TestCase):
    def test_two_sample_r_translator_independent_counts_order_and_ragged_dataframe(self):
        before = [2, 2, 3, None, 4, 5, 6, 7, 30]
        after = [1, 2, None, 4, 3, 4, 5, 6]
        ws = Worksheet("WelchQA", [Column("Before", "number", before), Column("After", "number", after)])
        p = Presenter()
        p.worksheet = ws
        entry = p.two_sample_t({
            "data_format": 1,
            "sample1_col": 1,  # Reversed: After first!
            "sample2_col": 0,  # Before second!
            "assume_equal_variances": True,
            "confidence_level": 90.0,
            "alternative": "greater",
            "hypothesized_difference": 1.5,
        })
        settings = entry["recipe"]["parameters"]["settings"]
        conn = create_connected_two_sample_t(ws, settings, entry["result"])
        self.assertEqual(conn.metadata.get("sample1_n"), 7)
        self.assertEqual(conn.metadata.get("sample2_n"), 8)

        win = ModernWindow(p)
        try:
            bar = StatCraftAnalysisBar(win, entry, conn.to_dict())
            self.assertIn("N1 = 7, N2 = 8", bar.model_info.text())
            self.assertNotIn("N = 6", bar.model_info.text())
        finally:
            win.close()
            win.deleteLater()
            _APP.processEvents()

        conn_rep = generate_connected_report(conn, ws)
        self.assertIn("N1=7, N2=8", conn_rep)

        df_code = generate_dataframe_r_code(ws)
        # After must be padded with NA to match Before's length 9
        after_line = next(line for line in df_code.splitlines() if '"After"' in line)
        after_vec = after_line.split("c(", 1)[1].rsplit(")", 1)[0]
        self.assertEqual(len([tok.strip() for tok in after_vec.split(",")]), 9)
        self.assertTrue(after_vec.endswith("NA"))

        base_r, tidy_r, _ = translate_entry_to_r(entry, ws)
        # Verify selected sample order (After first, Before second) and options
        self.assertIn('na.omit(df[["After"]])', base_r)
        self.assertIn('na.omit(df[["Before"]])', base_r)
        self.assertLess(base_r.index('df[["After"]]'), base_r.index('df[["Before"]]'))
        self.assertIn("var.equal = TRUE", base_r)
        self.assertIn("conf.level = 0.9", base_r)
        self.assertIn("alternative = 'greater'", base_r)
        self.assertIn("mu = 1.5", base_r)
        self.assertIn("na.omit", tidy_r)
        self.assertIn("var.equal = TRUE", tidy_r)

    def test_save_and_export_do_not_trigger_false_stale_banner(self):
        p = Presenter()
        factors = [dict(name=name, low=-1, high=1) for name in "AB"]
        p.create_factorial(factors, replicates=2, randomize=False)
        p.add_column("Yield")
        for row in range(p.worksheet.row_count):
            std_order, _, _, _, a, b, _ = p.worksheet.row(row)
            dev = -1 if std_order <= 4 else 1
            p.set_cell(row, 6, str(20 + 3 * a + 2 * b + a * b + dev))
        win = ModernWindow(p)
        try:
            entry = win._call(lambda: p.analyze_factorial(6, [4, 5]), result=True)
            ver_before = win._sheet_versions.version(p.worksheet)
            with tempfile.TemporaryDirectory() as tmp:
                mpx_path = Path(tmp) / "no_false_stale.mpx"
                xlsx_path = Path(tmp) / "no_false_stale.xlsx"
                ok = bool(win._call(lambda: win.save_path(str(mpx_path)), mutates_sheet=False))
                self.assertTrue(ok)
                self.assertEqual(win._sheet_versions.version(p.worksheet), ver_before)
                res_xlsx = win._call(lambda: p.export_excel(str(xlsx_path), True), mutates_sheet=False)
                self.assertTrue(res_xlsx)
                self.assertEqual(win._sheet_versions.version(p.worksheet), ver_before)
                win.show_result(entry, target_tab="Effects Pareto")
                page = win.result_tabs.currentWidget()
                self.assertEqual(page.findChildren(StaleOutputBanner), [])
        finally:
            p.dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()

    def test_pareto_90_percent_reference_line_avoids_value_labels(self):
        entry = {
            "title": "Pareto 90%",
            "result": {
                "analysis": "definitive_screening_analysis",
                "response_name": "Yield",
                "alpha": 0.10,
                "t_crit": 2.00,
                "pareto_effects": [
                    {"term": "A", "effect": 4.50, "p_val": 0.002},
                    {"term": "B", "effect": 2.02, "p_val": 0.095},
                    {"term": "C", "effect": 2.00, "p_val": 0.100},
                    {"term": "D", "effect": 0.80, "p_val": 0.450},
                ],
            },
        }
        for width in (480, 760, 1280):
            widget = DSDParetoEffectsWidget(entry)
            widget.resize(width, 420)
            pix = widget.grab()
            self.assertFalse(pix.isNull())
            crit_x = getattr(widget, "_crit_x", None)
            label_rects = getattr(widget, "_value_label_rects", None)
            self.assertIsNotNone(crit_x)
            self.assertEqual(len(label_rects), 4)
            for rect in label_rects:
                self.assertIsInstance(rect, QRectF)
                self.assertFalse(
                    rect.left() - 1.0 <= crit_x <= rect.right() + 1.0,
                    f"Reference line x={crit_x} intersects label {rect} at width={width}",
                )
                self.assertGreaterEqual(rect.left(), 0.0)
                self.assertLessEqual(rect.right(), float(width))

    def test_verify_packaged_acceptance_helper(self):
        p = Presenter()
        win = ModernWindow(p)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                summary = verify_packaged_acceptance(win, Path(tmp))
                self.assertTrue(summary["freeze_panes_ok"])
                self.assertGreaterEqual(summary["exported_png_count"], 4)
                self.assertEqual(summary["exported_png_count"], summary["distinct_png_hashes"])
                self.assertTrue(summary["pointer_sweep_ok"])
                self.assertTrue(summary["r_translation_ok"])
        finally:
            p.dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()


if __name__ == "__main__":
    unittest.main()
