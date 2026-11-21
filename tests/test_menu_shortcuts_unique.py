"""Ctrl+C / Ctrl+V (and the other edit shortcuts) must not be ambiguous.

ModernWindow builds its menu bar and then rebuilds it when the UI mode is set.
QMenuBar.clear() leaves the old QActions alive on the window, so each shortcut
existed twice and Qt ran neither ("Ambiguous shortcut overload: Ctrl+C").
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidgetSelectionRange

_app = QApplication.instance() or QApplication(sys.argv)

EDIT_SHORTCUTS = ("Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z", "Ctrl+Y", "Ctrl+S", "Ctrl+O", "Ctrl+N", "Ctrl+A")


class TestMenuShortcutsUnique(unittest.TestCase):
    def setUp(self):
        from statcraft.modern_app import ModernWindow

        self.win = ModernWindow()
        self.win.show()
        self.win.activateWindow()
        _app.processEvents()

    def tearDown(self):
        self.win.presenter.dirty = False  # avoid the modal "Unsaved changes" prompt
        self.win.close()

    def _live(self, sequence):
        return [a for a in self.win.findChildren(QAction)
                if any(s.toString() == sequence for s in a.shortcuts())]

    def test_edit_shortcuts_are_unique(self):
        for sequence in EDIT_SHORTCUTS:
            with self.subTest(shortcut=sequence):
                self.assertEqual(len(self._live(sequence)), 1)

    def test_shortcuts_stay_unique_after_switching_modes(self):
        for mode in ("jmp", "minitab", "r", "minitab"):
            self.win.set_ui_mode(mode)
            _app.processEvents()
        for sequence in ("Ctrl+C", "Ctrl+V"):
            with self.subTest(shortcut=sequence):
                self.assertEqual(len(self._live(sequence)), 1)

    def test_ctrl_c_and_ctrl_v_work_on_the_worksheet(self):
        sheet = self.win.presenter.worksheet
        sheet.columns[0].name = "X"
        sheet.columns[0].kind = "number"
        sheet.columns[0].values = [1.0, 2.0, 3.0]
        self.win.refresh()
        table = self.win.table
        table.setFocus()
        table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 2, 0), True)
        QApplication.clipboard().setText("sentinel")
        QTest.keyClick(table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(QApplication.clipboard().text().split(), ["1.0", "2.0", "3.0"])

        QApplication.clipboard().setText("9\n8\n7")
        table.clearSelection()
        table.setCurrentCell(0, 0)
        QTest.keyClick(table, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(sheet.columns[0].values[:3], [9.0, 8.0, 7.0])


if __name__ == "__main__":
    unittest.main()
