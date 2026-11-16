import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit

from statcraft.conditional_formatting import effective_highlights, validate_rule
from statcraft.modern_app import ModernWindow, WelcomeWatermarkWidget
from statcraft.oneway_dialogs import OneWayOptionsDialog
from statcraft.regression_dialog import RegressionOptionsDialog, RegressionGraphsDialog, RegressionResultsDialog, RegressionStorageDialog
from statcraft.app import Column


def _app():
    return QApplication.instance() or QApplication(sys.argv)


class TestMinitabParityRound4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _app()

    def setUp(self):
        self.win = ModernWindow(sandbox_mode=True)

    def tearDown(self):
        self.win.presenter.dirty = False
        self.win.close()

    def test_menu_parity_tools_help_view_edit_file(self):
        bar = self.win.menuBar()
        menus = {act.text().replace("&", ""): act.menu() for act in bar.actions() if act.menu()}
        self.assertIn("Tools", menus)
        tools_items = [a.text().replace("&", "") for a in menus["Tools"].actions() if not a.isSeparator()]
        self.assertIn("Options…", tools_items)
        self.assertIn("Manage Profiles…", tools_items)
        self.assertIn("Customize…", tools_items)

        help_items = [a.text().replace("&", "") for a in menus["Help"].actions() if not a.isSeparator()]
        self.assertIn("Keyboard Map…", help_items)

        file_items = [a.text().replace("&", "") for a in menus["File"].actions() if not a.isSeparator()]
        self.assertIn("Close Worksheet", file_items)

        edit_items = [a.text().replace("&", "") for a in menus["Edit"].actions() if not a.isSeparator()]
        self.assertIn("Edit Command Line…", edit_items)
        self.assertEqual(self.win.delete_action.shortcut().toString(), "Ctrl+-")

        view_items = [a.text().replace("&", "") for a in menus["View"].actions() if not a.isSeparator()]
        self.assertNotIn("Edit Command Line…", view_items)

        # No consecutive separators in View
        view_actions = menus["View"].actions()
        for prev, curr in zip(view_actions, view_actions[1:]):
            self.assertFalse(prev.isSeparator() and curr.isSeparator())

        graph_items = [a.text().replace("&", "") for a in menus["Graph"].actions() if not a.isSeparator()]
        self.assertIn("Update All Graphs", graph_items)

    def test_cut_column_names_and_select_all_guard(self):
        self.win.show()
        self.win.activateWindow()
        self.win.presenter.rename_columns(0, ["Alpha", "Beta"])
        self.win.refresh()
        self.win.column_names.setFocus()
        self.win.column_names.setCurrentCell(0, 0)
        self.win.column_names.selectColumn(0)
        QApplication.processEvents()
        self.win.cut_cells()
        self.assertEqual(QApplication.clipboard().text(), "Alpha")
        self.assertEqual(self.win.presenter.worksheet.columns[0].name, "C1")

        # Select All inside command editor must not select worksheet table
        self.win.command_editor.setPlainText("DESCRIBE C1")
        self.win.command_editor.setFocus()
        QApplication.processEvents()
        self.win.select_all_dataset()
        self.assertEqual(self.win.command_editor.textCursor().selectedText(), "DESCRIBE C1")

    def test_welcome_hides_when_data_present(self):
        self.win.presenter.set_cell(0, 0, "42")
        self.win.refresh()
        self.assertGreater(self.win.presenter.worksheet.row_count, 0)
        self.assertFalse(isinstance(self.win.result_tabs.widget(0), WelcomeWatermarkWidget))

    def test_subdialogs_have_help_button(self):
        opts = {"confidence": 0.95, "graphs": "four", "results": {}, "storage": {}}
        for cls in (RegressionOptionsDialog, RegressionGraphsDialog, RegressionResultsDialog, RegressionStorageDialog):
            dlg = cls(self.win, dict(opts))
            boxes = dlg.findChildren(QDialogButtonBox)
            self.assertTrue(any(b.button(QDialogButtonBox.StandardButton.Help) is not None for b in boxes))
            dlg.close()

        ow_dlg = OneWayOptionsDialog(self.win, {})
        ow_boxes = ow_dlg.findChildren(QDialogButtonBox)
        self.assertTrue(any(b.button(QDialogButtonBox.StandardButton.Help) is not None for b in ow_boxes))
        ow_dlg.close()

    def test_conditional_formatting_frequent_and_diagnostics(self):
        col = Column("X", "number", [1.0, 1.0, 1.0, 2.0, 2.0, 9.0, 100.0])
        most = effective_highlights(col, rules=[{"type": "most_frequent", "param1": 1, "color": "#d4edda"}])
        self.assertEqual(set(most.keys()), {"0", "1", "2"})

        least = effective_highlights(col, rules=[{"type": "least_frequent", "param1": 1, "color": "#fff3cd"}])
        # 9.0 and 100.0 both have count 1; sorted deterministically by str(val) -> "100.0" < "9.0"
        self.assertEqual(len(least), 1)

        col_diag = Column("Y", "number", [10.0, 11.0, 12.0, 13.0], metadata={"large_residual_rows": [2], "unusual_x_rows": [0]})
        res_hl = effective_highlights(col_diag, rules=[{"type": "large_residuals", "color": "#f8d7da"}])
        self.assertEqual(res_hl, {"2": "#f8d7da"})
        ux_hl = effective_highlights(col_diag, rules=[{"type": "unusual_x", "color": "#fff3cd"}])
        self.assertEqual(ux_hl, {"0": "#fff3cd"})

    def test_update_all_graphs_and_custom_dialog_state(self):
        called = []
        fake_entry = {"plots": [{"kind": "histogram"}], "_rerun_action": lambda: called.append(True)}
        self.win.presenter.history.append(fake_entry)
        with patch.object(self.win.presenter, "result_stale", return_value=True):
            count = self.win.update_all_graphs()
        self.assertEqual(count, 1)
        self.assertEqual(called, [True])

        dummy = SimpleNamespace(selected_params={"col": 0})
        self.win._save_custom_dialog_state("test_dlg", dummy)
        dummy2 = SimpleNamespace(selected_params=None)
        self.win._restore_custom_dialog_state("test_dlg", dummy2)
        self.assertEqual(dummy2.selected_params, {"col": 0})

    def test_wheel_event_requires_ctrl_for_zoom(self):
        from statcraft.modern_charts import ChartWidget
        chart = ChartWidget(self.win)
        chart.spec = {"kind": "scatter", "x": [1, 2, 3], "y": [2, 4, 6]}
        ev_no_ctrl = QWheelEvent(
            QPointF(50, 50),
            QPointF(50, 50),
            QPointF(0, 0).toPoint(),
            QPointF(0, 120).toPoint(),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        ev_no_ctrl.accept()
        chart.wheelEvent(ev_no_ctrl)
        self.assertFalse(ev_no_ctrl.isAccepted())
        chart.close()


if __name__ == "__main__":
    unittest.main()
