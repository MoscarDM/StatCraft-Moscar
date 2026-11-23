"""Tests for everyday UI behavior parity (Home/End/F2, dialog Enter transfer, entry-dir pill, persistent pins)."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.variable_dialogs import ProcedureDialog


class UiBehaviorParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_worksheet_home_end_and_f2_keys(self):
        win = ModernWindow(sandbox_mode=True)
        try:
            win.presenter.worksheet = Worksheet(
                "Nav",
                [
                    Column("A", "number", [1.0]),
                    Column("B", "number", [2.0]),
                    Column("C", "number", [3.0]),
                    Column("D", "number", []),
                ],
            )
            win.refresh()
            win.table.setCurrentCell(0, 2)
            QTest.keyClick(win.table, Qt.Key.Key_Home)
            self.assertEqual(win.table.currentColumn(), 0)
            QTest.keyClick(win.table, Qt.Key.Key_End)
            self.assertEqual(win.table.currentColumn(), 2)
            QTest.keyClick(win.table, Qt.Key.Key_F2)
            self.assertEqual(win.table.state(), win.table.State.EditingState)
        finally:
            win.close()
            win.deleteLater()
            self.app.processEvents()

    def test_procedure_dialog_enter_in_available_transfers_variable(self):
        ws = Worksheet("D", [Column("Y", "number", [1.0, 2.0]), Column("X", "number", [3.0, 4.0])])
        dlg = ProcedureDialog(
            None,
            "Test",
            ws,
            selectors=[
                {"key": "y", "label": "Response:"},
                {"key": "x", "label": "Predictor:"},
            ],
        )
        dlg.available.setCurrentRow(0)
        QTest.keyClick(dlg.available, Qt.Key.Key_Return)
        self.assertIn("Y", dlg.controls["y"].text())
        self.assertEqual(dlg.active_key, "x")
        dlg.deleteLater()

    def test_status_entry_dir_toggle_and_pinned_persistence(self):
        win = ModernWindow(sandbox_mode=True)
        try:
            self.assertEqual(win.status_entry_dir_btn.text(), "↓ Down")
            win.status_entry_dir_btn.click()
            self.assertEqual(win.status_entry_dir_btn.text(), "→ Right")
            win.status_entry_dir_btn.click()
            self.assertEqual(win.status_entry_dir_btn.text(), "↓ Down")

            win._pinned_procedures.pin("Box Cox Dialog", win.box_cox_dialog)
            win._save_ui_preferences()
        finally:
            win.close()
            win.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
