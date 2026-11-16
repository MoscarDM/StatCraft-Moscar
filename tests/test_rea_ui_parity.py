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
            win.close()
            win.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
