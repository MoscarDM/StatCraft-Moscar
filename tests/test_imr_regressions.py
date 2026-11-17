"""Regression tests for two I-MR crashes.

1. IMRChartDialog._select_variable passed (column, index) to
   format_variable_reference, whose signature is (index, worksheet).
2. IMRChartWidget never called _init_graph_interaction(), so any mouse move
   raised AttributeError ('is_brushing').
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPointingDevice
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)


class TestIMRRegressions(unittest.TestCase):
    def test_select_button_fills_variable_reference(self):
        from statcraft.imr_dialogs import IMRChartDialog
        from statcraft.model import Column, Worksheet

        sheet = Worksheet("Data", [
            Column("Week", values=[27, 28, 29, 30, 31]),
            Column("Mean", values=[17048, 17969, 18065, 18361, 18565]),
        ])
        dialog = IMRChartDialog(sheet)
        dialog.var_list.item(1).setSelected(True)
        dialog._select_variable()
        self.assertEqual(dialog.edit_vars.text(), 'C2: "Mean"')

    def test_chart_widget_survives_mouse_move(self):
        from statcraft.imr_chart import IMRChartWidget
        from statcraft.imr_engine import run_imr_chart

        result = run_imr_chart([17048, 17969, 18065, 18361, 18565], None, "Mean")
        result["graph"] = "imr_chart"
        widget = IMRChartWidget({"result": result, "graph_styles": {}})
        widget.resize(800, 700)
        widget.show()
        _app.processEvents()

        self.assertFalse(widget.is_brushing)
        device = QPointingDevice.primaryPointingDevice()
        for x in range(50, 700, 50):
            pos = QPointF(x, 300)
            event = QMouseEvent(
                QEvent.Type.MouseMove, pos, widget.mapToGlobal(pos),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier, device,
            )
            _app.sendEvent(widget, event)
        widget.close()


if __name__ == "__main__":
    unittest.main()
