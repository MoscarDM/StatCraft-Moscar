"""Tests for REA-verified Minitab 22 UI behavior parity (Ctrl+Enter, Ctrl+L, F4/Shift+F4, Ctrl/Shift+Insert)."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow


class ReaUiParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ctrl_enter_jumps_to_top_of_next_column(self):
        win = ModernWindow(sandbox_mode=True)
        try:
            win.presenter.worksheet = Worksheet(
                "S1",
                [Column("A", "number", [1.0, 2.0, 3.0]), Column("B", "number", [4.0, 5.0, 6.0])],
            )
            win.refresh()
            win.table.setCurrentCell(2, 0)
            QTest.keyClick(win.table, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(win.table.currentRow(), 0)
            self.assertEqual(win.table.currentColumn(), 1)
        finally:
            win.presenter.dirty = False
            win.close()
            win.deleteLater()
            self.app.processEvents()

    def test_ctrl_l_opens_command_line_and_f4_shortcuts_bound(self):
        win = ModernWindow(sandbox_mode=True)
        try:
            self.assertEqual(win.next_brushed_action.shortcut().toString(), "F4")
            self.assertEqual(win.prev_brushed_action.shortcut().toString(), "Shift+F4")
            self.assertTrue(win.command_line_pane.isHidden())
            win.open_command_line()
            self.assertFalse(win.command_line_pane.isHidden())
            win.toggle_command_line()
            self.assertTrue(win.command_line_pane.isHidden())
        finally:
            win.presenter.dirty = False
            win.close()
            win.deleteLater()
            self.app.processEvents()

    def test_backspace_clears_multi_cell_selection_and_shift_row_selects_range(self):
        win = ModernWindow(sandbox_mode=True)
        try:
            win.presenter.worksheet = Worksheet(
                "S2",
                [Column("A", "number", [10.0, 20.0, 30.0, 40.0]), Column("B", "number", [1.0, 2.0, 3.0, 4.0])],
            )
            win.refresh()
            # Multi-cell range selection + Backspace -> clears all selected cells
            from PySide6.QtWidgets import QTableWidgetSelectionRange
            win.table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 1, 1), True)
            QTest.keyClick(win.table, Qt.Key.Key_Backspace)
            self.assertIsNone(win.presenter.worksheet.columns[0].values[0])
            self.assertIsNone(win.presenter.worksheet.columns[0].values[1])
            self.assertIsNone(win.presenter.worksheet.columns[1].values[0])
            self.assertIsNone(win.presenter.worksheet.columns[1].values[1])
            self.assertEqual(win.presenter.worksheet.columns[0].values[2], 30.0)

            # Row header anchor + Shift+Click selects contiguous rows 1..3
            win._row_selection_anchor = 1
            win.select_worksheet_row(1, extend=False)
            lo, hi = 1, 3
            for r in range(lo + 1, hi + 1):
                win.select_worksheet_row(r, extend=True)
            self.assertEqual(sorted(win._selected_rows), [1, 2, 3])
        finally:
            win.presenter.dirty = False
            win.close()
            win.deleteLater()
            self.app.processEvents()

    def test_pure_graph_opens_without_report_or_text_export_tabs(self):
        win = ModernWindow(sandbox_mode=True)
        try:
            win.presenter.worksheet = Worksheet(
                "G1",
                [Column("X", "number", [1.0, 2.0, 3.0]), Column("Y", "number", [2.0, 4.0, 6.0])],
            )
            entry = win.presenter.scatter_plot(1, 0)
            win.show_result(entry)
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), "Graph")
            self.assertTrue(win.result_tabs.tabBar().isHidden())
        finally:
            win.presenter.dirty = False
            win.close()
            win.deleteLater()
            self.app.processEvents()

    def test_hidden_columns_in_dialogs_and_conditional_rules_and_shortcuts(self):
        from statcraft.conditional_formatting import effective_highlights
        from statcraft.variable_dialogs import ProcedureDialog

        col = Column("V", "number", [1.0, 5.0, 10.0])
        hl_ne = effective_highlights(col, 3, rules=[{"type": "not_equal_to", "param1": 5.0, "color": "#fecaca"}])
        self.assertEqual(sorted(hl_ne.keys()), ["0", "2"])
        hl_nb = effective_highlights(col, 3, rules=[{"type": "not_between", "param1": 2.0, "param2": 8.0, "color": "#fecaca"}])
        self.assertEqual(sorted(hl_nb.keys()), ["0", "2"])

        win = ModernWindow(sandbox_mode=True)
        try:
            win.presenter.worksheet = Worksheet(
                "H1",
                [Column("A", "number", [1.0, 2.0]), Column("B", "number", [3.0, 4.0])],
            )
            win._hidden_columns = {1}
            win._use_hidden_in_dialogs = False
            dlg_hide = ProcedureDialog(win, "TestHide", win.presenter.worksheet, selectors=[{"key": "x", "label": "Var:"}])
            self.assertEqual(dlg_hide.available.count(), 1)
            dlg_hide.deleteLater()

            win._use_hidden_in_dialogs = True
            dlg_show = ProcedureDialog(win, "TestShow", win.presenter.worksheet, selectors=[{"key": "x", "label": "Var:"}])
            self.assertEqual(dlg_show.available.count(), 2)
            dlg_show.deleteLater()

            # Ctrl+Shift+D is owned uniquely by dark_mode_action (no duplicate on toggle_theme_action)
            self.assertEqual(win.toggle_theme_action.shortcut().toString(), "")
            self.assertEqual(win.dark_mode_action.shortcut().toString(), "Ctrl+Shift+D")
            self.assertEqual([s.toString() for s in win.format_column_action.shortcuts()], ["Ctrl+1", "Ctrl+B"])
        finally:
            win.presenter.dirty = False
            win.close()
            win.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
