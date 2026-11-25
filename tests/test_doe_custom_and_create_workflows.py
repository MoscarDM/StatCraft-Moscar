import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QTableWidget,
)

from statcraft import settings_scope
from statcraft.app import Presenter, format_entry
from statcraft.doe_custom_dialog import (
    DefineCustomDesignsDialog,
    DefineCustomFactorialDialog,
    DefineCustomLowHighDialog,
)
from statcraft.doe_dialogs import AnalyzeFactorialDialog, CreateFactorialDialog
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow

_APP = QApplication.instance() or QApplication([])


def _paper_airplane_custom_worksheet() -> Worksheet:
    # 12-run general full factorial (Angle 15/30/45 x Wing Short/Long across 2 Block testers)
    std_seq = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    angle = [15.0, 30.0, 45.0, 15.0, 30.0, 45.0, 15.0, 30.0, 45.0, 15.0, 30.0, 45.0]
    wing = ["Short"] * 6 + ["Long"] * 6
    tester = ["Day1", "Day1", "Day1", "Day2", "Day2", "Day2"] * 2
    # Strong Angle, Wing, and Block effects for clear non-trivial ANOVA check
    dist = [
        10.0 + (a / 15.0) * 2.0 + (3.0 if w == "Long" else 0.0) + (1.5 if blk == "Day2" else 0.0)
        for a, w, blk in zip(angle, wing, tester)
    ]
    return Worksheet(
        "PaperAirplaneCustom",
        [
            Column("ExplicitStd", "number", std_seq),
            Column("Angle", "number", angle),
            Column("Wing", "text", wing),
            Column("TesterBlock", "text", tester),
            Column("Distance", "number", dist),
        ],
    )


class DoeCustomAndCreateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _APP

    def _make_window(self, settings_dir: Path):
        self._sandbox_patch = patch.object(settings_scope, "_sandbox_workspace", settings_dir)
        self._recent_patch = patch.object(ModernWindow, "_add_recent_file", lambda *a, **k: None)
        self._sandbox_patch.start()
        self._recent_patch.start()
        return ModernWindow()

    def _cleanup_window(self, win: ModernWindow):
        try:
            win.presenter.dirty = False
            win.presenter._results_dirty = False
            win.close()
            win.deleteLater()
            self.app.processEvents()
        finally:
            self._recent_patch.stop()
            self._sandbox_patch.stop()

    def test_01_define_custom_paper_airplane_general_factorial_blocks_and_mpx(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            win = self._make_window(tmp_path)
            try:
                ws = _paper_airplane_custom_worksheet()
                win.presenter.worksheet = ws
                win.refresh()

                # Verify menu action exists under Stat -> DOE -> Factorial
                define_acts = [a for a in win.findChildren(QAction) if a.text() == "Define Custom Factorial Design…"]
                self.assertTrue(define_acts)

                dlg = DefineCustomFactorialDialog(win, ws)
                self.addCleanup(dlg.deleteLater)
                # Left picker shows C#   Name
                picker_texts = [dlg.available.item(i).text() for i in range(dlg.available.count())]
                self.assertEqual(picker_texts[0], "C1   ExplicitStd")
                self.assertEqual(picker_texts[1], "C2   Angle")

                # Hard-to-change picker disabled until 2-level split-plot is selected
                self.assertFalse(dlg.hard_list.isEnabled())
                dlg.general_radio.setChecked(True)
                self.assertFalse(dlg.hard_list.isEnabled())
                self.assertFalse(dlg.low_high_btn.isEnabled())

                # Select Angle (C2) and Wing (C3)
                dlg.factors_edit.setText("C2 C3")
                self.app.processEvents()

                # Configure Designs…: explicit StdOrder C1, row order RunOrder, unknown PointType, Blocks C4
                designs = DefineCustomDesignsDialog(dlg, ws, dlg.design_options)
                self.addCleanup(designs.deleteLater)
                designs.std_col_radio.setChecked(True)
                designs.std_combo.setCurrentIndex(designs.std_combo.findData(0))
                designs.run_row_radio.setChecked(True)
                designs.pt_unknown_radio.setChecked(True)
                designs.blk_col_radio.setChecked(True)
                designs.blk_combo.setCurrentIndex(designs.blk_combo.findData(3))
                self.assertTrue(designs.std_combo.isEnabled())
                self.assertFalse(designs.run_combo.isEnabled())
                self.assertFalse(designs.pt_combo.isEnabled())
                self.assertTrue(designs.blk_combo.isEnabled())
                designs.validate()
                self.assertEqual(designs.result(), QDialog.DialogCode.Accepted)
                dlg.design_options = designs.state

                # Reopen Designs… -> verify previous selections retained and child Cancel discards edits
                designs2 = DefineCustomDesignsDialog(dlg, ws, dlg.design_options)
                self.addCleanup(designs2.deleteLater)
                self.assertTrue(designs2.std_col_radio.isChecked())
                self.assertTrue(designs2.run_row_radio.isChecked())
                self.assertTrue(designs2.pt_unknown_radio.isChecked())
                self.assertTrue(designs2.blk_col_radio.isChecked())
                designs2.blk_none_radio.setChecked(True)
                designs2.reject()  # Cancel discards child edit
                self.assertEqual(dlg.design_options["blocks_mode"], "column")

                dlg.validate()
                self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)

                # Cancel on another dialog instance must leave worksheet metadata untouched
                cancel_ws = _paper_airplane_custom_worksheet()
                cancel_dlg = DefineCustomFactorialDialog(win, cancel_ws)
                self.addCleanup(cancel_dlg.deleteLater)
                cancel_dlg.factors_edit.setText("C2 C3")
                cancel_dlg.reject()
                self.assertEqual(cancel_ws.metadata.get("doe", {}), {})

                # Apply via Presenter, save MPX, reopen, and analyze using configured blocks
                win.presenter.define_custom_factorial(**dlg.parameters)
                mpx_path = tmp_path / "custom_plane.mpx"
                win.presenter.save(mpx_path)

                reopened = Presenter()
                reopened.load(mpx_path)
                doe_meta = reopened.worksheet.metadata["doe"]
                self.assertEqual(doe_meta["design_type"], "general_full")
                self.assertEqual(doe_meta["factors"][0]["levels"], [15.0, 30.0, 45.0])
                self.assertEqual(doe_meta["std_order_column"], "ExplicitStd")
                self.assertEqual(doe_meta["run_order_mode"], "row_order")
                self.assertEqual(doe_meta["point_type_mode"], "unknown")
                self.assertEqual(doe_meta["blocks_column"], "TesterBlock")

                fit = reopened.analyze_factorial(4, [1, 2])
                res = fit["result"]
                self.assertTrue(res["include_blocks"])
                self.assertEqual(res["blocks_column"], "TesterBlock")
                self.assertEqual(res["blocks"], 2)
                self.assertGreater(res["r_squared"], 0.99)
                self.assertIn("Factor Information", format_entry(fit))
            finally:
                self._cleanup_window(win)

    def test_02_define_custom_two_level_split_plot_and_invalid_selections(self):
        ws = Worksheet(
            "SplitCustom",
            [
                Column("Temp", "number", [100, 100, 150, 150, 100, 100, 150, 150]),
                Column("Speed", "number", [10, 20, 10, 20, 10, 20, 10, 20]),
                Column("Operator", "text", ["A", "A", "A", "A", "B", "B", "B", "B"]),
                Column("DateCol", "date", [46156.0] * 8),
            ],
        )
        dlg = DefineCustomFactorialDialog(None, ws)
        self.addCleanup(dlg.deleteLater)
        dlg.factors_edit.setText("C1 C2 C3")
        self.app.processEvents()

        # Hard-to-change picker restricted strictly to selected factors C1, C2, C3
        dlg.split_plot_radio.setChecked(True)
        self.assertTrue(dlg.hard_list.isEnabled())
        self.assertTrue(dlg.low_high_btn.isEnabled())
        self.assertEqual(dlg.hard_list.count(), 3)

        # Colliding Blocks column == selected factor produces clear inline error
        dlg.set_hard_factors([0])
        dlg.design_options["blocks_mode"] = "column"
        dlg.design_options["blocks_index"] = 2
        dlg.validate()
        self.assertNotEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertIn("cannot also be selected as a Factor", dlg.error.text())

        # Valid 2-level split-plot selection succeeds cleanly
        dlg.design_options["blocks_mode"] = "none"
        dlg.design_options["blocks_index"] = None
        dlg.validate()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dlg.parameters["hard_factor_indices"], [0])

        # Low/High dialog validates invalid low >= high cleanly
        lh = DefineCustomLowHighDialog(dlg, ws, [0, 1])
        self.addCleanup(lh.deleteLater)
        lh.table.item(0, 3).setText("200")
        lh.table.item(0, 4).setText("100")
        lh.validate()
        self.assertNotEqual(lh.result(), QDialog.DialogCode.Accepted)
        self.assertIn("Low < High", lh.error.text())

        # Unsupported date column in factors expression fails clearly
        dlg_err = DefineCustomFactorialDialog(None, ws)
        self.addCleanup(dlg_err.deleteLater)
        dlg_err.two_level_radio.setChecked(True)
        dlg_err.factors_edit.setText("C1 C4")
        dlg_err.validate()
        self.assertNotEqual(dlg_err.result(), QDialog.DialogCode.Accepted)
        self.assertTrue(bool(dlg_err.error.text()))

    def test_03_create_factorial_gating_defaults_and_families(self):
        # 1) Gating, defaults, half-fraction highlighted at k=3, re-gating on change, 8-run full factorial
        dlg = CreateFactorialDialog(None)
        self.addCleanup(dlg.deleteLater)
        self.assertFalse(dlg.factors_btn.isEnabled())
        self.assertFalse(dlg.options_btn.isEnabled())
        self.assertFalse(dlg.results_btn.isEnabled())
        self.assertFalse(dlg.ok_button.isEnabled())
        self.assertIn("(2–15 factors)", dlg.design_types[0].text())
        self.assertIn("(1–8 factors)", dlg.design_types[4].text())
        self.assertEqual(dlg.replicates, 1)
        self.assertEqual(dlg.centers, 0)
        self.assertEqual(dlg.blocks, 1)
        self.assertIsNone(dlg.seed)

        # Open Designs… at k=3: row 0 = 4-run half fraction Res III highlighted, row 1 = 8-run full factorial
        def pick_full_factorial(sub):
            table = sub.findChild(QTableWidget)
            self.assertEqual(table.currentRow(), 0)
            self.assertEqual(table.item(0, 1).text(), "4")
            self.assertEqual(table.item(0, 2).text(), "III")
            self.assertEqual(table.item(1, 1).text(), "8")
            self.assertEqual(table.item(1, 2).text(), "Full")
            table.setCurrentCell(1, 0)
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", pick_full_factorial):
            dlg.designs()
        self.assertTrue(dlg.factors_btn.isEnabled())
        self.assertTrue(dlg.options_btn.isEnabled())
        self.assertTrue(dlg.results_btn.isEnabled())
        self.assertTrue(dlg.ok_button.isEnabled())

        # Changing factor count re-gates until Designs… re-confirmed
        dlg.factor_count.setCurrentText("4")
        self.assertFalse(dlg.ok_button.isEnabled())
        dlg.factor_count.setCurrentText("3")
        with patch.object(QDialog, "exec", lambda sub: (sub.findChild(QDialogButtonBox).accepted.emit() or QDialog.DialogCode.Accepted)):
            dlg.designs()

        # Verify Options… blank seed & Store design checkbox
        def tweak_options(opt_dlg):
            checks = opt_dlg.findChildren(QCheckBox)
            rnd_cb = next(c for c in checks if "Randomize" in c.text())
            store_cb = next(c for c in checks if "Store" in c.text())
            self.assertTrue(store_cb.isEnabled())
            self.assertTrue(store_cb.isChecked())
            rnd_cb.setChecked(False)
            opt_dlg.findChild(QDialogButtonBox).accepted.emit()
            return opt_dlg.result()

        with patch.object(QDialog, "exec", tweak_options):
            dlg.options()

        dlg.validate()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        p = Presenter()
        entry = p.create_factorial(**dlg.parameters)
        self.assertEqual(p.worksheet.row_count, 8)
        self.assertEqual(p.worksheet.headers, ["StdOrder", "RunOrder", "PtType", "Blocks", "A", "B", "C"])
        self.assertEqual(entry["result"]["runs"], 8)
        self.assertEqual(entry["result"]["replicates"], 1)

        # 2) Half-fraction 3 factors -> 4 runs
        dlg_half = CreateFactorialDialog(None)
        self.addCleanup(dlg_half.deleteLater)
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            dlg_half.designs()
        dlg_half.randomize = False
        dlg_half.validate()
        p_half = Presenter()
        p_half.create_factorial(**dlg_half.parameters)
        self.assertEqual(p_half.worksheet.row_count, 4)

        # 3) Text factor + center points validation & valid 2-level text factorial -> analysis -> MPX
        dlg_txt = CreateFactorialDialog(None)
        self.addCleanup(dlg_txt.deleteLater)
        dlg_txt.factor_count.setCurrentText("2")
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            dlg_txt.designs()

        def set_text_factor(f_dlg):
            tbl = f_dlg.findChild(QTableWidget)
            self.assertEqual(tbl.item(0, 0).text(), "A")
            tbl.cellWidget(1, 2).setCurrentIndex(1)  # Switch factor B to Text
            tbl.item(1, 3).setText("Cold")
            tbl.item(1, 4).setText("Hot")
            f_dlg.findChild(QDialogButtonBox).accepted.emit()
            return f_dlg.result()

        with patch.object(QDialog, "exec", set_text_factor):
            dlg_txt.factor_settings()
        dlg_txt.centers = 2  # Incompatible with Text factor
        dlg_txt.validate()
        self.assertNotEqual(dlg_txt.result(), QDialog.DialogCode.Accepted)
        self.assertIn("Center points require all factors to be Numeric", dlg_txt.error.text())

        dlg_txt.centers = 0
        dlg_txt.randomize = False
        dlg_txt.validate()
        self.assertEqual(dlg_txt.result(), QDialog.DialogCode.Accepted)
        p_txt = Presenter()
        p_txt.create_factorial(**dlg_txt.parameters)
        self.assertEqual(p_txt.worksheet.columns[5].kind, "text")
        self.assertEqual(set(p_txt.worksheet.columns[5].values), {"Cold", "Hot"})
        p_txt.create_factorial(
            factors=dlg_txt.parameters["factors"],
            replicates=2,
            randomize=False,
            seed=5,
        )
        p_txt.add_column("Y")
        for r in range(p_txt.worksheet.row_count):
            a = p_txt.worksheet.columns[4].values[r]
            b = 1.0 if p_txt.worksheet.columns[5].values[r] == "Hot" else -1.0
            p_txt.set_cell(r, 6, str(10 + 2 * a + 3 * b))
        fit_txt = p_txt.analyze_factorial(6, [4, 5])
        self.assertEqual(fit_txt["result"]["df_error"], 4)

        # 4) General full 3 x 2 x 2 = 12 runs and Split-plot whole x subplot reps
        dlg_gf = CreateFactorialDialog(None)
        self.addCleanup(dlg_gf.deleteLater)
        dlg_gf.design_types[4].setChecked(True)
        dlg_gf.factor_count.setCurrentText("3")

        def set_gf_322(sub):
            spins = sub.findChildren(QSpinBox)
            spins[0].setValue(3)
            spins[1].setValue(2)
            spins[2].setValue(2)
            sub.findChild(QDialogButtonBox).accepted.emit()
            return sub.result()

        with patch.object(QDialog, "exec", set_gf_322):
            dlg_gf.designs()
        dlg_gf.randomize = False
        dlg_gf.validate()
        p_gf = Presenter()
        p_gf.create_doe_plan(**dlg_gf.parameters)
        self.assertEqual(p_gf.worksheet.row_count, 12)

        dlg_sp = CreateFactorialDialog(None)
        self.addCleanup(dlg_sp.deleteLater)
        dlg_sp.design_types[2].setChecked(True)
        dlg_sp.factor_count.setCurrentText("3")

        def set_sp_reps(sub):
            spins = sub.findChildren(QSpinBox)
            spins[0].setValue(1)  # 1 hard factor
            spins[1].setValue(2)  # 2 whole-plot reps
            spins[2].setValue(2)  # 2 subplot reps -> 2 * 2 * 4 * 2 = 32 runs
            sub.findChild(QDialogButtonBox).accepted.emit()
            return sub.result()

        with patch.object(QDialog, "exec", set_sp_reps):
            dlg_sp.designs()
        dlg_sp.validate()
        p_sp = Presenter()
        p_sp.create_split_plot_design(**dlg_sp.parameters)
        self.assertEqual(p_sp.worksheet.row_count, 32)
        self.assertEqual(p_sp.worksheet.metadata["doe"]["subplot_replicates"], 2)

    def test_04_preview_only_quiet_creation_blank_reuse_and_occupied_new_tab(self):
        # Clean blank sheet reuse + preserve prior history on quiet creation + output-only preview
        p = Presenter()
        seed_entry = p._record("Prior Report", {"columns": [{"name": "X", "count": 3, "missing": 0, "mean": 2.0, "standard_error": 0.5, "stdev": 1.0, "variance": 1.0, "min": 1.0, "q1": 1.0, "median": 2.0, "q3": 3.0, "max": 3.0, "sum": 6.0}]})

        # Preview-only (store_in_worksheet=False) leaves active blank worksheet empty
        p.create_factorial(
            [{"name": "A", "low": -1, "high": 1}, {"name": "B", "low": -1, "high": 1}],
            replicates=1,
            randomize=False,
            store_in_worksheet=False,
            result_level="full",
        )
        self.assertEqual(p.worksheet.row_count, 0)
        self.assertIsNone(p.native_project)
        self.assertTrue(any("Design Table:" in format_entry(e) for e in p.history))

        # Blank active sheet reuse + quiet creation preserves prior history
        blank_p = Presenter()
        prior = blank_p._record("Prior Entry", {"value": 123})
        quiet = blank_p.create_factorial(
            [{"name": "A", "low": -1, "high": 1}, {"name": "B", "low": -1, "high": 1}],
            replicates=1,
            randomize=False,
            store_in_worksheet=True,
            result_level="none",
        )
        self.assertIsNone(quiet)
        self.assertEqual(blank_p.history, [prior])
        self.assertIsNone(blank_p.native_project)
        self.assertEqual(blank_p.worksheet.row_count, 4)

        # Occupied active sheet creates a new tab and preserves existing data & history
        occ_p = Presenter()
        occ_p.worksheet = Worksheet("ExistingSheet", [Column("Obs", "number", [10.0, 20.0, 30.0])])
        occ_prior = occ_p._record("Existing Analysis", {"note": "keep me"})
        occ_p.create_factorial(
            [{"name": "A", "low": -1, "high": 1}, {"name": "B", "low": -1, "high": 1}],
            replicates=1,
            randomize=False,
        )
        self.assertIsNotNone(occ_p.native_project)
        self.assertEqual(len(occ_p.native_project.worksheets), 2)
        self.assertEqual(occ_p.native_project.worksheets[0].columns[0].values, [10.0, 20.0, 30.0])
        self.assertEqual(occ_p.native_project.worksheets[1].row_count, 4)
        self.assertTrue(any(e["entry_id"] == occ_prior["entry_id"] for e in occ_p.history))


if __name__ == "__main__":
    unittest.main()
