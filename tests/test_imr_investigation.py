import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from statcraft.app import Presenter, format_entry
from statcraft.imr_investigation import IMRInvestigationDialog
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow


class IMRInvestigationTests(unittest.TestCase):
    def test_signal_context_pending_followup_and_saved_comparison(self):
        app = QApplication.instance() or QApplication([])
        presenter = Presenter()
        presenter.worksheet = Worksheet('Before', [
            Column('Reading', 'number', [10, 10, 18, 10, 10]),
            Column('Shift', 'text', ['A', 'A', 'B', 'B', 'B']),
            Column('Lot', 'text', ['1', '1', '2', '2', '2']),
            Column('Machine', 'text', ['M1'] * 5),
            Column('Tool', 'text', ['T1', 'T1', 'T2', 'T2', 'T2']),
        ])
        settings = {'variables': [0], 'options': {'historical_mean': 10, 'historical_sigma': 1}}
        before = presenter.imr_chart(settings)
        presenter.add_worksheet('After').columns = [Column('Reading', 'number', [10, 10, 11, 9, 10])]
        after = presenter.imr_chart(settings)
        window = ModernWindow(presenter)
        completed = []
        try:
            open_action = next(action for action in window.build_output_context_menu(before).actions()
                               if action.text() == 'Investigate Signal…')

            def record_action():
                dialog = next(dialog for dialog in window.findChildren(IMRInvestigationDialog) if dialog.isVisible())
                dialog.save()
                completed.append(dialog.error.text())
                dialog.notes['cause'].setPlainText('Tool changed at row 3')
                dialog.notes['action'].setPlainText('Verify setup at tool change')
                dialog.save()
                completed.append(dialog.saved_entry)
                if dialog.isVisible():
                    dialog.reject()

            QTimer.singleShot(180, record_action)
            open_action.trigger()
            self.assertIn('Enter a suspected cause', completed[0])
            investigation = completed[1]
            self.assertEqual(investigation['worksheet_id'], before['worksheet_id'])
            self.assertIn('C5 Tool=T2', format_entry(investigation))
            self.assertIsNone(investigation['result']['after'])
            dialog = IMRInvestigationDialog(window, None, investigation)
            dialog.after.setCurrentIndex(dialog.after.findData(after['entry_id']))
            dialog.notes['evidence'].setPlainText('Follow-up sample shows no signals')
            dialog.reject()
            self.assertIsNone(investigation['result']['after'])
            dialog.save()
            self.assertEqual(investigation['result']['after']['i_signals'], 0)

            # Worksheet context and report persist independently of live worksheet cells.
            source = presenter.result_worksheet(before)
            source.columns[4].values[2] = 'Changed later'
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'investigation.mpx'
                presenter.save(path)
                presenter.load(path)
            report = next(item for item in presenter.history if item['entry_id'] == investigation['entry_id'])
            self.assertIn('C5 Tool=T2', format_entry(report))
            self.assertIn('Individuals signals: 0/5', format_entry(report))
            self.assertIn('Follow-up sample', format_entry(report))
        finally:
            window.hide()
            window.deleteLater()
            app.processEvents()
