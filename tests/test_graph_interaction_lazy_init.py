"""Chart widgets that inherit GraphInteractionMixin but never call
_init_graph_interaction() must not crash on mouse move / click
(AttributeError: ... has no attribute 'is_brushing')."""
import importlib
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPointingDevice
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

WIDGETS = [
    ("pareto_chart", "ParetoChartWidget"),
    ("run_chart_plot", "RunChartWidget"),
    ("time_weighted_control_chart", "TimeWeightedControlChartWidget"),
    ("graphical_summary_chart", "GraphicalSummaryChartWidget"),
    ("tolerance_intervals_chart", "ToleranceIntervalChartWidget"),
    ("fitted_line_plot_chart", "FittedLinePlotChartWidget"),
    ("attribute_control_chart", "AttributeControlChartWidget"),
    ("imr_chart", "IMRChartWidget"),
]


def _mouse_event(widget, kind, button=Qt.MouseButton.NoButton):
    pos = QPointF(40, 40)
    return QMouseEvent(
        kind, pos, widget.mapToGlobal(pos), button, button,
        Qt.KeyboardModifier.NoModifier, QPointingDevice.primaryPointingDevice(),
    )


class TestGraphInteractionLazyInit(unittest.TestCase):
    def test_state_exists_and_events_do_not_raise(self):
        for module, name in WIDGETS:
            with self.subTest(widget=name):
                cls = getattr(importlib.import_module("statcraft." + module), name)
                widget = cls({"result": {}, "graph_styles": {}})
                self.assertFalse(widget.is_brushing)
                self.assertEqual(widget.brushed_rows, set())
                widget.mouseMoveEvent(_mouse_event(widget, QEvent.Type.MouseMove))
                widget.mousePressEvent(
                    _mouse_event(widget, QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton))

    def test_lazy_init_keeps_values_set_by_the_widget(self):
        from statcraft.run_chart_plot import RunChartWidget

        widget = RunChartWidget({"result": {}})
        marker = object()
        widget.hit_regions = [marker]
        widget.is_brushing  # triggers lazy init of the remaining state
        self.assertEqual(widget.hit_regions, [marker])

    def test_unknown_attribute_still_raises(self):
        from statcraft.pareto_chart import ParetoChartWidget

        widget = ParetoChartWidget({"result": {}})
        with self.assertRaises(AttributeError):
            widget.this_attribute_does_not_exist


if __name__ == "__main__":
    unittest.main()
