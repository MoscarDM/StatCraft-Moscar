import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from statcraft.app import Presenter
from statcraft.imr_trace import IMRTraceDialog, point_trace
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow


class IMRTraceTests(unittest.TestCase):
    def test_output_action_and_saved_source_trace(self):
        app = QApplication.instance() or QApplication([])
        presenter = Presenter()
        presenter.worksheet = Worksheet('Trace', [Column('Reading', 'number', [10, 11, None, 13, 17, 14])])
        entry = presenter.imr_chart({'variables': [0], 'options': {
            'span': 3, 'omit_subgroups': [5], 'historical_sigma': 2,
        }})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'trace.mpx'
            presenter.save(path)
            presenter.load(path)
        entry = presenter.history[-1]
        trace = point_trace(entry['result'], 'mr', 6)
        self.assertEqual(trace['value'], 4)
        self.assertEqual(trace['rows'], [(4, 13, False), (5, 17, True), (6, 14, False)])
        self.assertIsNone(point_trace(entry['result'], 'mr', 4)['value'])
        with self.assertRaises(ValueError):
            point_trace(entry['result'], 'mr', 0)
        presenter.worksheet.columns[0].values[4] = 100
        self.assertTrue(presenter.result_stale(entry))
        window = ModernWindow(presenter)
        observed = []
        try:
            menu = window.build_output_context_menu(entry)
            action = next(a for a in menu.actions() if a.text() == 'Trace I-MR Result…')

            def inspect():
                dialog = window.findChild(IMRTraceDialog)
                if dialog is not None:
                    dialog.panel.setCurrentIndex(1)
                    dialog.row.setValue(6)
                    observed.append(dialog.details.toPlainText())
                    dialog.reject()

            QTimer.singleShot(150, inspect)
            action.trigger()
            self.assertIn('5: 17.0 (omitted from limit estimation)', observed[0])
            self.assertIn('historical sigma', observed[0])
        finally:
            window.hide()
            window.deleteLater()
            app.processEvents()
