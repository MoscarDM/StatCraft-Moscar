import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHeaderView, QLineEdit, QTableView

from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow


class FreezePanesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = ModernWindow(sandbox_mode=True)
        self.addCleanup(self.win.close)
        self.win._confirm_leave = lambda: True
        self.win.presenter.worksheet = Worksheet(
            "Wide worksheet",
            [Column(f"Measure {c + 1}", "number", [1000 * c + r for r in range(150)])
             for c in range(30)],
        )
        self.win.refresh()
        self.win.resize(1280, 672)
        self.win.show()
        self.app.processEvents()
        self.table = self.win.table
        self.names = self.win.column_names
        self.width = self.table.columnWidth(0)
        self.height = self.table.rowHeight(0)
        self.table.setCurrentCell(2, 1)
        self._view_action("Freeze Panes")

    def _view_action(self, text):
        view = next(a.menu() for a in self.win.menuBar().actions() if a.text().replace("&", "") == "View")
        stack = list(view.actions())
        while stack:
            item = stack.pop(0)
            if item.menu():
                stack.extend(item.menu().actions())
            elif item.text().replace("&", "") == text:
                item.trigger()
                self.app.processEvents()
                return
        raise AssertionError(f"View action not found: {text}")

    def _hit(self, viewport, x, y):
        point = viewport.mapToGlobal(QPoint(x, y))
        widget = self.win.childAt(self.win.mapFromGlobal(point))
        self.assertIsNotNone(widget, point)
        view = widget.parentWidget()
        return view, widget.mapFromGlobal(point)

    def _cell(self, viewport, x, y):
        view, point = self._hit(viewport, x, y)
        self.assertIsInstance(view, QTableView)
        index = view.indexAt(point)
        self.assertTrue(index.isValid(), point)
        return view, point, (index.row(), index.column())

    def _label(self, viewport, x, y):
        header, point = self._hit(viewport, x, y)
        self.assertIsInstance(header, QHeaderView)
        section = header.logicalIndexAt(point)
        return section, header.model().headerData(section, header.orientation())

    def _scroll(self, horizontal, vertical):
        self.table.horizontalScrollBar().setValue(horizontal)
        self.table.verticalScrollBar().setValue(vertical)
        self.app.processEvents()

    def _edit(self, view, point, new_text, key):
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.app.processEvents()
        editor = self.app.focusWidget()
        self.assertIsInstance(editor, QLineEdit)
        editor.setText(new_text)
        QTest.keyClick(editor, key)
        self.app.processEvents()

    def test_pinned_rows_and_columns_keep_headers_and_model_indexes(self):
        self._scroll(950, 290)
        viewport = self.table.viewport()
        width, height = self.width, self.height
        self.assertEqual(self._cell(viewport, 12, 8)[2], (0, 0))
        self.assertEqual(self._cell(viewport, 12, height + 8)[2], (1, 0))
        top = self._cell(viewport, width + 12, 8)
        left = self._cell(viewport, 12, 2 * height + 8)
        moving = self._cell(viewport, width + 12, 2 * height + 8)
        self.assertGreater(moving[2][0], 2)
        self.assertGreater(moving[2][1], 1)
        self.assertEqual(top[2], (0, moving[2][1]))
        self.assertEqual(left[2], (moving[2][0], 0))
        self.assertEqual(self._label(self.table.verticalHeader().viewport(), 12, 8), (0, "1"))
        self.assertEqual(self._label(self.table.verticalHeader().viewport(), 12, height + 8), (1, "2"))
        self.assertEqual(self._label(self.names.horizontalHeader().viewport(), 12, 8), (0, "C1"))
        self.assertEqual(
            self._label(self.names.horizontalHeader().viewport(), width + 12, 8)[0],
            moving[2][1],
        )
        pinned_name = self._cell(self.names.viewport(), 12, 8)
        self.assertEqual(pinned_name[2], (0, 0))
        self.assertEqual(self._cell(self.names.viewport(), width + 12, 8)[2], (0, moving[2][1]))

        self._edit(*moving[:2], "67891", Qt.Key.Key_Return)
        r, c = moving[2]
        self.assertEqual(self.win.presenter.worksheet.columns[c].values[r], 67891)
        self._edit(*self._cell(viewport, 12, height + 8)[:2], "87654", Qt.Key.Key_Return)
        self.assertEqual(self.win.presenter.worksheet.columns[0].values[1], 87654)
        self._edit(*self._cell(viewport, 12, 8)[:2], "87655", Qt.Key.Key_Escape)
        self.assertEqual(self.win.presenter.worksheet.columns[0].values[0], 0)
        self._edit(*self._cell(self.names.viewport(), 12, 8)[:2], "Renamed measure", Qt.Key.Key_Return)
        self.assertEqual(self.win.presenter.worksheet.columns[0].name, "Renamed measure")

    def test_keyboard_reveals_cells_beside_pinned_regions(self):
        self._scroll(950, 290)
        self.table.setCurrentCell(1, 0)
        self.table.setFocus()
        QTest.keyClick(self.table, Qt.Key.Key_F2)
        self.app.processEvents()
        editor = self.app.focusWidget()
        self.assertIsInstance(editor, QLineEdit)
        self.assertEqual(editor.text(), "1")
        point = editor.mapToGlobal(editor.rect().center())
        self.assertEqual(self._hit(self.table.viewport(), 12, self.height + 8)[0], editor.parentWidget())
        self.assertLess(self.table.viewport().mapFromGlobal(point).y(), 2 * self.height)
        editor.setText("84")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.win.presenter.worksheet.columns[0].values[1], 84)
        self.assertEqual((self.table.currentRow(), self.table.currentColumn()), (2, 0))
        self.assertEqual(self._cell(self.table.viewport(), 12, 2 * self.height + 8)[2], (2, 0))
        self.win.undo()
        self.assertEqual(self.win.presenter.worksheet.columns[0].values[1], 1)
        QTest.keyClick(self.table, Qt.Key.Key_Right)
        self.app.processEvents()
        self.assertEqual(self._cell(self.table.viewport(), self.width + 12, 2 * self.height + 8)[2], (2, 1))

    def test_resize_hide_scroll_boundaries_and_unfreeze(self):
        header, point = self._hit(self.names.horizontalHeader().viewport(), self.width - 1, 8)
        QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseMove(header.viewport(), point + QPoint(31, 0))
        QTest.mouseRelease(header.viewport(), Qt.MouseButton.LeftButton, pos=point + QPoint(31, 0))
        self.app.processEvents()
        self.assertEqual(self.table.columnWidth(0), self.width + 31)
        self._scroll(0, 0)
        viewport = self.table.viewport()
        x = self.width + 12
        self.assertEqual(self._cell(viewport, x, 8)[2], (0, 0))
        self.assertEqual(self._cell(self.names.viewport(), x, 8)[2], (0, 0))
        self._scroll(self.table.horizontalScrollBar().maximum(), self.table.verticalScrollBar().maximum())
        x_right = viewport.width() - 8
        y_bottom = viewport.height() - 8
        self.assertEqual(
            self._cell(viewport, x_right, y_bottom)[2],
            (self.table.rowCount() - 1, self.table.columnCount() - 1),
        )
        self.assertEqual(self._cell(self.names.viewport(), x_right, 8)[2], (0, self.table.columnCount() - 1))
        self.assertEqual(self._cell(viewport, x, 8)[2], (0, 0))

        self.win.select_worksheet_column(0)
        self.win.hide_selected_columns()
        self.app.processEvents()
        self._scroll(0, 0)
        self.assertEqual(self._cell(viewport, 12, 8)[2], (0, 1))
        self.assertEqual(self._cell(self.names.viewport(), 12, 8)[2], (0, 1))
        self.win.unhide_all_columns()
        self.app.processEvents()
        self._scroll(950, 290)
        self.assertEqual(self._cell(viewport, 12, 8)[2], (0, 0))
        self.assertEqual(self.table.columnWidth(0), self.width + 31)
        self._view_action("Unfreeze Rows/Cols")
        self._scroll(self.table.horizontalScrollBar().maximum(), self.table.verticalScrollBar().maximum())
        row, column = self._cell(viewport, 12, 8)[2]
        self.assertGreater(row, 2)
        self.assertGreater(column, 1)
        self.assertEqual(self._cell(self.names.viewport(), 12, 8)[2], (0, column))
