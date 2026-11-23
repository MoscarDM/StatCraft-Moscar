import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from statcraft.app import Presenter
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.xlsx_verification import supports, write_verification


def regression_fixture():
    presenter = Presenter()
    presenter.worksheet = Worksheet('Regression', [
        Column('Speed', 'number', [1, 2, None, 4, 5, 6, 7, 8]),
        Column('Depth', 'number', [2, 5, 3, 1, 5, 2, 1, None]),
        Column('Output', 'number', [7, 16, 15, 20, 24, 27, 32, 40]),
    ])
    return presenter, presenter.multiple_regression(2, [0, 1])


class ExcelVerificationTests(unittest.TestCase):
    def test_export_reads_original_rows_and_formula_linked_chart(self):
        presenter, result = regression_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'regression.xlsx'
            write_verification(path, presenter, result)
            workbook = load_workbook(path)
            self.assertEqual(workbook.sheetnames, ['Verification', 'Inputs', 'Calculations'])
            self.assertEqual([cell.value for cell in workbook['Inputs'][4]], [3, False, 15, None, 3])
            self.assertEqual([cell.value for cell in workbook['Inputs'][9]], [8, False, 40, 8, None])
            verification = workbook['Verification']
            calculations = workbook['Calculations']
            self.assertEqual([calculations.cell(row, 1).value for row in range(2, 8)], [1, 2, 4, 5, 6, 7])
            self.assertEqual(calculations['C4'].value, '=IF(ISNUMBER(Inputs!D5),Inputs!D5,NA())')
            self.assertEqual(calculations['H2'].value.text, '=LINEST(B2:B7,C2:D7,TRUE,FALSE)')
            self.assertEqual([calculations[cell].value for cell in ('H4', 'I4')], ['=I2', '=H2'])
            self.assertEqual(calculations['E2'].value,
                             '=IF(Verification!$B$7="Valid",$J$2+SUMPRODUCT(C2:D2,$H$4:$I$4),NA())')
            self.assertEqual(verification['B11'].value, result['result']['coefficients'][1]['estimate'])
            self.assertIn('Calculations!I2', verification['C11'].value)
            chart = verification._charts[0]
            self.assertEqual((chart.x_axis.axPos, chart.y_axis.axPos), ('b', 'l'))
            self.assertEqual((chart.x_axis.tickLblPos, chart.y_axis.tickLblPos), ('low', 'low'))
            self.assertIs(chart.x_axis.delete, False)
            self.assertIs(chart.y_axis.delete, False)
            self.assertEqual(chart.y_axis.majorGridlines.spPr.line.solidFill.srgbClr, 'DFE5EC')
            series = chart.series[0]
            self.assertEqual(series.xVal.numRef.f, "'Calculations'!$E$2:$E$7")
            self.assertEqual(series.yVal.numRef.f, "'Calculations'!$F$2:$F$7")

    def test_result_saved_to_mpx_reopens_and_uses_source_worksheet(self):
        presenter, entry = regression_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.mpx'
            presenter.save(path)
            loaded = Presenter()
            loaded.load(path)
            entry = next(e for e in loaded.history if e['entry_id'] == entry['entry_id'])
            destination = path.with_suffix('.xlsx')
            write_verification(destination, loaded, entry)
            original = destination.read_bytes()
            loaded.worksheet.columns[0].values[0] = 10
            with self.assertRaisesRegex(ValueError, 'Rerun'):
                write_verification(destination, loaded, entry)
            self.assertEqual(destination.read_bytes(), original)

    def test_ui_action_cancel_and_invalid_export(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        os.environ.setdefault('STATCRAFT_TESTING', '1')
        app = QApplication.instance() or QApplication([])
        presenter, entry = regression_fixture()
        window = ModernWindow(presenter)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'from-menu'
                action = next(action for action in window.build_output_context_menu(entry).actions()
                              if action.text().startswith('Export Excel Verification'))
                with patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
                    action.trigger()
                self.assertFalse(path.with_suffix('.xlsx').exists())
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')):
                    action.trigger()
                self.assertTrue(path.with_suffix('.xlsx').is_file())
                self.assertFalse(presenter.result_stale(entry))
                presenter.worksheet.columns[0].values[0] = 99
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')), \
                     patch.object(QMessageBox, 'warning') as warning:
                    action.trigger()
                self.assertIn('Rerun', warning.call_args.args[2])
        finally:
            presenter.dirty = False
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_other_regression_models_are_not_offered(self):
        self.assertFalse(supports({'recipe': {'action': 'multiple_regression',
                                              'parameters': {'categorical_indices': [1]}}}))
        self.assertFalse(supports({'recipe': {'action': 'multiple_regression',
                                              'parameters': {'model_terms': [[0, 1]]}}}))
