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

    def test_chart_quick_bar_toggles_work_on_chart_widget(self):
        from statcraft.micro_innovations import build_chart_quick_bar
        from statcraft.modern_charts import ChartWidget
        from statcraft.graph_frame import GraphFrame
        self.win.presenter.paste(0, 0, "1\t2\n2\t4\n3\t8\n")
        entry = self.win.presenter.scatter_plot(0, 1)
        chart = ChartWidget(entry)
        frame = GraphFrame(chart, entry)
        bar = build_chart_quick_bar(frame, chart, entry, self.win)
        actions = {a.text(): a for a in bar.menu().actions() if a.text()}
        actions["Show Gridlines"].trigger()
        self.assertFalse(chart.annotation_grid)
        actions["Logarithmic Y Scale"].trigger()
        self.assertTrue(chart.annotation_y_log)
        actions["Crosshair Mode"].trigger()
        self.assertTrue(chart._crosshair_enabled)
        actions["Copy as PNG"].trigger()
        self.assertFalse(QApplication.clipboard().pixmap().isNull())
        frame.close()
        chart.close()

    def test_data_copy_submenu_and_presenter_workflows(self):
        bar = self.win.menuBar()
        menus = {act.text().replace("&", ""): act.menu() for act in bar.actions() if act.menu()}
        data_submenus = {a.text().replace("&", ""): a.menu() for a in menus["Data"].actions() if a.menu()}
        self.assertIn("Copy", data_submenus)
        copy_items = [a.text().replace("&", "") for a in data_submenus["Copy"].actions() if not a.isSeparator()]
        self.assertEqual(copy_items, ["Columns to Columns…", "Columns to Constants…", "Constants to Columns…"])

        self.win.presenter.paste(0, 0, "10\n20\n30\n40\n")
        created = self.win.presenter.copy_columns_to_columns([0], include_rows={0, 2})
        self.assertEqual(len(created), 1)
        self.assertEqual(self.win.presenter.worksheet.columns[created[0]].values, [10.0, 30.0])

        stored = self.win.presenter.copy_columns_to_constants([0], ["K1", "K2"])
        self.assertEqual(stored, ["K1", "K2"])
        col_idx = self.win.presenter.copy_constants_to_columns(["K1", "K2"], target_name="FromConsts")
        self.assertEqual(self.win.presenter.worksheet.columns[col_idx].name, "FromConsts")
        self.assertEqual(self.win.presenter.worksheet.columns[col_idx].values, [10.0, 20.0])

    def test_custom_dialog_get_set_state_roundtrip(self):
        from statcraft.oneway_dialogs import OneWayAnovaDialog
        from statcraft.capability_dialogs import CapabilityDialog

        self.win.presenter.paste(0, 0, "10\tA\n20\tB\n")
        ow1 = OneWayAnovaDialog(self.win)
        ow1.response_edit.setText("C1")
        ow1.factor_edit.setText("C2")
        ow1.options["confidence"] = 99.0
        self.win._save_custom_dialog_state("oneway_anova", ow1)
        ow2 = OneWayAnovaDialog(self.win)
        self.win._restore_custom_dialog_state("oneway_anova", ow2)
        self.assertEqual(ow2.response_edit.text(), "C1")
        self.assertEqual(ow2.factor_edit.text(), "C2")
        self.assertEqual(ow2.options["confidence"], 99.0)
        ow1.close(); ow2.close()

        cap1 = CapabilityDialog(self.win.presenter.worksheet, self.win)
        cap1.edit_single_col.setText("C1")
        cap1.edit_lsl.setText("5")
        cap1.edit_usl.setText("25")
        cap1.options["confidence_level"] = 99.0
        self.win._save_custom_dialog_state("capability_normal", cap1)
        cap2 = CapabilityDialog(self.win.presenter.worksheet, self.win)
        self.win._restore_custom_dialog_state("capability_normal", cap2)
        self.assertEqual(cap2.edit_single_col.text(), "C1")
        self.assertEqual(cap2.edit_lsl.text(), "5")
        self.assertEqual(cap2.edit_usl.text(), "25")
        self.assertEqual(cap2.options["confidence_level"], 99.0)
        cap1.close(); cap2.close()

    def test_arrow_key_navigation_into_and_across_column_names(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent

        self.win.show()
        self.win.activateWindow()
        self.win.table.setCurrentCell(0, 0)
        self.win.table.setFocus()
        QApplication.processEvents()

        # Up from Row 0 moves focus to column_names C1 (0, 0)
        up_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
        self.win.table.event(up_ev)
        QApplication.processEvents()
        self.assertTrue(self.win.column_names.hasFocus())
        self.assertEqual(self.win.column_names.currentColumn(), 0)

        # Right in column_names moves to C2 (0, 1) and stays in column_names
        right_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        self.win.column_names.event(right_ev)
        QApplication.processEvents()
        self.assertTrue(self.win.column_names.hasFocus())
        self.assertEqual(self.win.column_names.currentColumn(), 1)

        # Left in column_names moves back to C1 (0, 0)
        left_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
        self.win.column_names.event(left_ev)
        QApplication.processEvents()
        self.assertTrue(self.win.column_names.hasFocus())
        self.assertEqual(self.win.column_names.currentColumn(), 0)

        # Down from column_names moves back to table Row 0, Col 0
        down_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        self.win.column_names.event(down_ev)
        QApplication.processEvents()
        self.assertTrue(self.win.table.hasFocus())
        self.assertEqual(self.win.table.currentRow(), 0)
        self.assertEqual(self.win.table.currentColumn(), 0)

    def test_twoway_imr_state_and_default_confidence_wiring(self):
        from PySide6.QtCore import QSettings
        from statcraft.twoway_anova_dialogs import TwoWayAnovaDialog
        from statcraft.imr_dialogs import IMRChartDialog
        from statcraft.regression_dialog import default_regression_options

        settings = QSettings("StatCraft", "Desktop")
        prev_val = settings.value("options/default_confidence")
        try:
            settings.setValue("options/default_confidence", 99.0)
            self.win.presenter.paste(0, 0, "10\tA\tX\n20\tB\tY\n")
            tw1 = TwoWayAnovaDialog(self.win.presenter.worksheet, self.win)
            self.assertEqual(tw1.spin_ci.value(), 99.0)
            tw1.chk_interaction.setChecked(False)
            tw1.spin_ci.setValue(90.0)
            self.win._save_custom_dialog_state("twoway_anova", tw1)
            tw2 = TwoWayAnovaDialog(self.win.presenter.worksheet, self.win)
            self.win._restore_custom_dialog_state("twoway_anova", tw2)
            self.assertFalse(tw2.chk_interaction.isChecked())
            self.assertEqual(tw2.spin_ci.value(), 90.0)
            tw1.close(); tw2.close()

            self.assertAlmostEqual(default_regression_options()["confidence"], 0.99)

            imr1 = IMRChartDialog(self.win.presenter.worksheet, self.win)
            imr1.edit_vars.setText("C1")
            imr1.options["span"] = 3
            self.win._save_custom_dialog_state("imr_dialog", imr1)
            imr2 = IMRChartDialog(self.win.presenter.worksheet, self.win)
            self.win._restore_custom_dialog_state("imr_dialog", imr2)
            self.assertEqual(imr2.edit_vars.text(), "C1")
            self.assertEqual(imr2.options["span"], 3)
            imr1.close(); imr2.close()
        finally:
            if prev_val is None:
                settings.remove("options/default_confidence")
            else:
                settings.setValue("options/default_confidence", prev_val)

    def test_change_data_type_with_date_format_and_target_column(self):
        self.win.presenter.set_column_type(0, "text")
        self.win.presenter.worksheet.columns[0].values = ["03/15/2025", "04/20/2025"]
        self.win.presenter.set_column_type(0, "date", target_index="new", date_format="%m/%d/%Y")
        new_col = self.win.presenter.worksheet.columns[-1]
        self.assertEqual(new_col.kind, "date")
        self.assertEqual(new_col.metadata.get("date_format"), "%m/%d/%Y")
        self.assertEqual(len(new_col.values), 2)
        self.assertEqual(self.win.presenter.worksheet.columns[0].kind, "text")

    def test_attribute_chart_dialog_state_roundtrip(self):
        from statcraft.attribute_control_dialogs import AttributeChartDialog
        self.win.presenter.paste(0, 0, "2\t50\n3\t50\n")
        d1 = AttributeChartDialog(self.win.presenter.worksheet, chart_type="P", parent=self.win)
        d1.edit_vars.setText("C1")
        d1.edit_subgroup.setText("C2")
        self.win._save_custom_dialog_state("attribute_control_P", d1)
        d2 = AttributeChartDialog(self.win.presenter.worksheet, chart_type="P", parent=self.win)
        self.win._restore_custom_dialog_state("attribute_control_P", d2)
        self.assertEqual(d2.edit_vars.text(), "C1")
        self.assertEqual(d2.edit_subgroup.text(), "C2")
        d1.close(); d2.close()


if __name__ == "__main__":
    unittest.main()
