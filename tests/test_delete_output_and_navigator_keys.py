import os
import sys
import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow

os.environ["QT_QPA_PLATFORM"] = "offscreen"


class TestDeleteOutputAndNavigatorKeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_delete_output_entry(self):
        ws = Worksheet("Sheet1", [Column("C1", "number", [10, 20])])
        win = ModernWindow(sandbox_mode=True)
        self.addCleanup(self._close_graph_test_window, win)
        win._confirm_leave = lambda: True
        win.presenter.worksheet = ws

        entry = {"title": "Test Regression", "time": "12:00:00", "result": {"analysis": "regression", "text": "OK"}}
        win.presenter.history.append(entry)
        win.refresh()
        self.assertIn(entry, win.presenter.history)

        old_question = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        try:
            win.delete_output_entry(entry)
            self.assertNotIn(entry, win.presenter.history)
        finally:
            QMessageBox.question = old_question

    def test_navigator_delete_key(self):
        ws = Worksheet("Sheet1", [Column("C1", "number", [10, 20])])
        win = ModernWindow(sandbox_mode=True)
        self.addCleanup(self._close_graph_test_window, win)
        win._confirm_leave = lambda: True
        win.presenter.worksheet = ws

        entry = {"title": "Test ANOVA", "time": "12:00:00", "result": {"analysis": "anova", "text": "OK"}}
        win.presenter.history.append(entry)
        win.refresh()

        top = win.navigator.topLevelItem(0)
        item = top.child(0) if top.childCount() > 0 else top
        win.navigator.setCurrentItem(item)

        old_question = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        try:
            event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
            win.navigator.keyPressEvent(event)
            self.assertNotIn(entry, win.presenter.history)
        finally:
            QMessageBox.question = old_question

    def test_navigator_graph_edits_the_live_history_entry(self):
        win = ModernWindow(sandbox_mode=True)
        self.addCleanup(self._close_graph_test_window, win)
        win.presenter.worksheet = Worksheet("Measurements", [Column("Response", values=[1, 2, 4, 5])])
        graph = win.presenter.histogram_graphs([0])
        win.refresh()
        item = win.navigator.findItems(graph["title"], Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)[0]

        win.navigator.itemClicked.emit(item, 0)
        self.assertIs(win.selected_entry, graph)
        win._active_graph_frame.annotationActivated.emit("title")
        win.graph_options_pane.controls["title"].setText("Updated measurements")
        self.assertTrue(win.graph_options_pane.flush())
        self.assertEqual(graph["graph_presentation"]["title"], "Updated measurements")
        self.assertEqual(win._active_graph_frame.title_label.text(), "Updated measurements")

    def test_graph_export_waits_for_invalid_annotation_draft(self):
        win = ModernWindow(sandbox_mode=True)
        self.addCleanup(self._close_graph_test_window, win)
        win.presenter.worksheet = Worksheet("Measurements", [Column("Response", values=[1, 2, 4, 5])])
        graph = win.presenter.histogram_graphs([0])
        win.show_result(graph)
        win.edit_graph_dialog(graph)
        win.graph_options_pane.controls["x_min"].setText("invalid")

        with patch("statcraft.modern_app.QFileDialog.getExistingDirectory", return_value="") as destination:
            win.export_all_graphs_dialog()
            destination.assert_not_called()
            win.close_graph_options()
            win.export_all_graphs_dialog()
            destination.assert_called_once()

    def _close_graph_test_window(self, win):
        win.presenter.dirty = win.presenter._results_dirty = False
        win.close()
        win.deleteLater()
        QCoreApplication.sendPostedEvents(win, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
