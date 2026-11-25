"""Desktop usability, menu grouping/icons, right-edge column insert, R code viewer, split view, trace formatting, and Xbar-S Excel DAG tests (v121.2.23)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

from openpyxl import load_workbook
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from statcraft.app import Presenter
from statcraft.attribute_workflows import AttributeTraceDialog
from statcraft.connect_hub import ViewRCodeDialog, create_chemical_process_sample
from statcraft.imr_trace import IMRTraceDialog
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.r_workbench_widget import RCodeEditor, VSCodeRSyntaxHighlighter
from statcraft.subgroup_workflows import SubgroupTraceDialog
from statcraft.xlsx_verification import write_verification


class _InspectableRHighlighter(VSCodeRSyntaxHighlighter):
    """Subclass capturing setFormat calls during highlightBlock for deterministic verification."""

    def __init__(self, parent=None, is_dark: bool = False):
        self.last_spans: list[tuple[int, int, str]] = []
        super().__init__(parent, is_dark=is_dark)

    def highlightBlock(self, text: str) -> None:
        self.last_spans = []
        super().highlightBlock(text)

    def setFormat(self, start: int, count: int, fmt) -> None:  # type: ignore[override]
        super().setFormat(start, count, fmt)
        self.last_spans.append((start, count, fmt.foreground().color().name()))


def _clean_menu_label(text: str) -> str:
    return text.replace("&&", "\x00").replace("&", "").replace("\x00", "&")


_APP = QApplication.instance() or QApplication([])


class DesktopUsabilityV121223Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _APP
        cls._prev_fmt = QSettings.defaultFormat()
        cls._tmp_settings = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, cls._tmp_settings.name)

    @classmethod
    def tearDownClass(cls):
        from statcraft.modern_icons import tool_icon
        tool_icon.cache_clear()
        cls.app.processEvents()
        QSettings.setDefaultFormat(cls._prev_fmt)
        cls._tmp_settings.cleanup()

    def _make_win(self, presenter=None):
        p = presenter or Presenter()
        win = ModernWindow(p)
        win.resize(1280, 760)
        win.show()
        self.app.processEvents()
        return win

    def test_01_r_highlighter_precedence_themes_and_code_viewer(self):
        editor = RCodeEditor(is_dark=False, read_only=True, with_highlighter=False)
        hl = _InspectableRHighlighter(editor.document(), is_dark=False)
        line = 'fit <- lm(Yield ~ Temp + 1.5e-2, data = df); col <- "#0284c7" # comment 123 if(TRUE)'
        editor.setPlainText(line)
        editor.show()
        self.app.processEvents()

        def color_at(pos):
            matched = [c for s, n, c in hl.last_spans if s <= pos < s + n]
            return matched[-1] if matched else None

        hash_in_str = line.index("#0284c7")
        comm_idx = line.index("# comment")
        num_idx = line.index("123")
        self.assertEqual(color_at(line.index("lm(")), "#795e26")
        self.assertEqual(color_at(line.index("<-")), "#0f172a")
        self.assertEqual(color_at(hash_in_str), "#a31515")
        self.assertEqual(color_at(comm_idx), "#008000")
        self.assertEqual(color_at(num_idx), "#008000", "Numbers inside comments must stay comment-colored")

        # Switch to Dark Modern palette
        hl.set_dark_mode(True)
        editor.set_dark_mode(True)
        self.app.processEvents()
        self.assertEqual(color_at(hash_in_str), "#ce9178")
        self.assertEqual(color_at(comm_idx), "#6a9955")
        editor.close()
        editor.deleteLater()

        # Chemical_Process Multiple Regression ViewRCodeDialog + view_entry_r_code
        p = Presenter()
        p.worksheet = create_chemical_process_sample()
        entry = p.multiple_regression(response_index=0, predictor_indices=[1, 2], categorical_indices=[3])
        win = self._make_win(p)
        try:
            script, _ = win._resolve_entry_r_script(entry, dialect="tidyverse")
            dlg = ViewRCodeDialog(win, r_script=script, title="Chemical_Process OLS", tidyverse_script=script)
            self.assertIsInstance(dlg.code_view, RCodeEditor)
            self.assertEqual(dlg.code_view.lineWrapMode(), RCodeEditor.LineWrapMode.NoWrap)
            self.assertTrue(dlg.code_view.gutter.width() > 0)
            self.assertEqual(dlg.code_view.toPlainText(), script)
            dlg._copy_code()
            self.assertEqual(QApplication.clipboard().text(), script)
            dlg.close()
            dlg.deleteLater()

            seen_texts = []
            with patch.object(QDialog, "exec", lambda d: seen_texts.append((d.findChild(RCodeEditor) is not None, d.findChild(RCodeEditor).toPlainText() if d.findChild(RCodeEditor) else "")) or 1):
                win.view_entry_r_code(entry)
            self.assertTrue(seen_texts and seen_texts[0][0])
            viewed_lines = seen_texts[0][1].splitlines()
            script_lines = script.splitlines()
            # Ignore 1-second timestamp tick in header while verifying exact script body preservation
            self.assertEqual([l for l in viewed_lines if not l.startswith("# Generated")],
                             [l for l in script_lines if not l.startswith("# Generated")])
        finally:
            p.dirty = False
            p._results_dirty = False
            win.close()
            win.deleteLater()
            self.app.processEvents()

    def test_02_right_edge_column_insertion_and_undo_redo(self):
        p = Presenter()
        p.worksheet = create_chemical_process_sample()
        orig_names = [c.name for c in p.worksheet.columns]
        self.assertEqual(orig_names, ["Yield", "Temperature", "Pressure", "Catalyst"])
        reg_entry = p.multiple_regression(response_index=0, predictor_indices=[1, 2], categorical_indices=[3])
        win = self._make_win(p)
        try:
            # Select last occupied column (Catalyst, index 3) and insert 1 column -> appends after Catalyst
            win.select_worksheet_column(3)
            win.insert_columns_action_handler()
            self.assertEqual([c.name for c in p.worksheet.columns], ["Yield", "Temperature", "Pressure", "Catalyst", "C5"])
            self.assertEqual(reg_entry["recipe"]["parameters"]["categorical_indices"], [3])

            # Insert 2 columns at right edge (selecting Catalyst + new C5) -> appends after Catalyst
            win.select_worksheet_column(3)
            win.select_worksheet_column(4, extend=True)
            win.insert_columns_action_handler()
            self.assertEqual(p.worksheet.columns[3].name, "Catalyst")
            self.assertEqual(len(p.worksheet.columns), 7)

            # Interior column selection (index 2 = Pressure) still inserts BEFORE Pressure and updates recipe refs on Undo/Redo
            win.select_worksheet_column(2)
            win.insert_columns_action_handler()
            self.assertEqual([c.name for c in p.worksheet.columns[:5]], ["Yield", "Temperature", "C3", "Pressure", "Catalyst"])

            win.undo()
            self.assertEqual([c.name for c in p.worksheet.columns[:4]], orig_names)
            win.redo()
            self.assertEqual(p.worksheet.columns[3].name, "Pressure")
            win.undo()
            win.undo()
            win.undo()
            self.assertEqual([c.name for c in p.worksheet.columns], orig_names)

            # Single right-edge insert + MPX save/reopen preserves column order, data types, and analysis ref
            win.select_worksheet_column(3)
            win.insert_columns_action_handler()
            with tempfile.TemporaryDirectory() as tmp:
                mpx_path = Path(tmp) / "chem_cols.mpx"
                p.save(mpx_path)
                p2 = Presenter()
                p2.load(mpx_path)
                self.assertEqual([c.name for c in p2.worksheet.columns], ["Yield", "Temperature", "Pressure", "Catalyst", "C5"])
                self.assertEqual([c.kind for c in p2.worksheet.columns[:4]], ["number", "number", "number", "text"])
        finally:
            p.dirty = False
            p._results_dirty = False
            win.close()
            win.deleteLater()
            self.app.processEvents()

    def test_03_split_view_default_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tmp)
            s = QSettings("StatCraft", "StatCraft")
            s.clear()
            s.sync()

            win = self._make_win()
            try:
                sizes = win.work_splitter.sizes()
                self.assertEqual(len(sizes), 2)
                self.assertGreater(sizes[0], sizes[1], f"Expected output pane >50% by default, got {sizes}")

                tot = sum(sizes)
                win.work_splitter.setSizes([int(tot * 0.7), tot - int(tot * 0.7)])
                win._on_work_splitter_moved()
                win._save_ui_preferences()
            finally:
                win.presenter.dirty = False
                win.close()
                win.deleteLater()
                self.app.processEvents()

            win2 = self._make_win()
            try:
                sizes2 = win2.work_splitter.sizes()
                ratio2 = sizes2[0] / float(max(1, sum(sizes2)))
                self.assertGreater(ratio2, 0.60, f"Expected persisted split ratio >0.60, got {sizes2}")
                win2.set_view_mode("both")
                sizes3 = win2.work_splitter.sizes()
                ratio3 = sizes3[0] / float(max(1, sum(sizes3)))
                self.assertGreater(ratio3, 0.60, f"set_view_mode('both') should honor saved ratio, got {sizes3}")
            finally:
                win2.presenter.dirty = False
                win2.close()
                win2.deleteLater()
                self.app.processEvents()

    def test_04_menu_grouping_and_icons(self):
        p = Presenter()
        p.worksheet = Worksheet("P_Data", [
            Column("Def", "number", [2, 3, 1, 8, 2, 3, 2, 1]),
            Column("SubSz", "number", [100] * 8),
        ])
        p_entry = p.attribute_control_chart({
            "chart_type": "P", "variables": [0], "is_subgroup_col": True, "subgroup_col_idx": 1,
        })
        win = self._make_win(p)
        try:
            top_menus = {_clean_menu_label(act.text()): act.menu() for act in win.menuBar().actions() if act.menu()}
            file_items = [_clean_menu_label(a.text()) for a in top_menus["File"].actions() if not a.isSeparator()]
            self.assertIn("Export R", file_items)
            self.assertIn("Export Reports", file_items)
            self.assertIn("Print", file_items)
            self.assertLessEqual(len(file_items), 15)

            view_items = [_clean_menu_label(a.text()) for a in top_menus["View"].actions() if not a.isSeparator()]
            self.assertIn("Output Tabs", view_items)
            self.assertIn("Worksheet Layout", view_items)
            self.assertLessEqual(len(view_items), 14)

            for m_name in ("File", "View", "Edit", "Data", "Calc", "Assistant", "Tools", "Help"):
                menu = top_menus[m_name]
                for act in menu.actions():
                    if act.isSeparator() or act in win.recent_menu.actions():
                        continue
                    self.assertFalse(act.icon().isNull(), f"{m_name} item '{act.text()}' missing icon")

            ctx = win.build_output_context_menu(p_entry)
            ctx_items = [_clean_menu_label(a.text()) for a in ctx.actions() if not a.isSeparator()]
            self.assertIn("Send & Export", ctx_items)
            self.assertIn("R Code", ctx_items)
            self.assertIn("Trace Attribute Result…", ctx_items)
            self.assertLessEqual(len(ctx_items), 16, f"Expected compact context menu, got {ctx_items}")
            ctx.deleteLater()
        finally:
            p.dirty = False
            p._results_dirty = False
            win.close()
            win.deleteLater()
            self.app.processEvents()

    def test_05_trace_settings_human_readable(self):
        p = Presenter()
        p.worksheet = Worksheet("TraceData", [
            Column("X", "number", [10.0, 10.2, 9.8, 10.1, 10.5, 9.9]),
            Column("Def", "number", [2, 3, 1, 2, 4, 2]),
            Column("Sz", "number", [100, 100, 100, 100, 100, 100]),
        ])
        imr = p.imr_chart({"variables": [0], "options": {}})
        sub = p.subgroup_control_chart(chart_type="xbar_s", stacked=True, response_index=0, subgroup_size=2)
        attr = p.attribute_control_chart({
            "chart_type": "P", "variables": [1], "is_subgroup_col": True, "subgroup_col_idx": 2,
        })
        for dlg in (
            IMRTraceDialog(None, imr, False),
            SubgroupTraceDialog(None, sub, False),
            AttributeTraceDialog(None, attr, False),
        ):
            txt = dlg.details.toPlainText()
            self.assertNotIn("{", txt, f"Raw dict/JSON leaked in trace dialog:\n{txt}")
            self.assertIn("Limit estimation", txt)
            self.assertIn("Saved analysis options", txt)
            dlg.close()

    def test_06_xbar_s_excel_one_way_dag(self):
        p = Presenter()
        p.worksheet = Worksheet("XbarS", [
            Column("Diam", "number", [10.0, 10.2, 9.8, 10.1, 10.3, 9.9, 9.7, 10.0, 10.2]),
            Column("Lot", "text", ["L1", "L1", "L1", "L2", "L2", "L2", "L3", "L3", "L3"]),
        ])
        entry = p.subgroup_control_chart(chart_type="xbar_s", stacked=True, response_index=0, factor_index=1)
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "xbar_s.xlsx"
            write_verification(out_path, p, entry)
            wb = load_workbook(out_path, data_only=False)
            self.assertEqual(wb.calculation.calcMode, "auto")
            self.assertTrue(wb.calculation.fullCalcOnLoad)
            calc = wb["Calculations"]
            for row in calc.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        self.assertNotIn("Verification!", cell.value, f"Cross-sheet cycle risk in {cell.coordinate}: {cell.value}")
            charts = wb["Verification"]._charts
            self.assertEqual(len(charts), 2)
            self.assertIn("$AM$", charts[0].series[0].val.numRef.f)
            self.assertIn("$AN$", charts[1].series[0].val.numRef.f)


if __name__ == "__main__":
    unittest.main()
