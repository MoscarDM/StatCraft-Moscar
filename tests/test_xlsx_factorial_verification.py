import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication, QFileDialog

from statcraft.app import Presenter
from statcraft.doe import create_factorial
from statcraft.model import Column
from statcraft.modern_app import ModernWindow
from statcraft.xlsx_verification import write_verification


def factorial_fixture(blocks=3, centers=0):
    presenter = Presenter()
    presenter.worksheet = create_factorial(
        [{'name': 'Heat', 'low': 10, 'high': 30}, {'name': 'Time', 'low': 40, 'high': 60}],
        replicates=3, randomize=True, seed=73, blocks=blocks, centers=centers)
    sheet = presenter.worksheet
    measured = [12 + a / 2 + b / 4 + a * b / 100 + (i % 4) * 0.2
                for i, (a, b) in enumerate(zip(sheet.columns[4].values, sheet.columns[5].values))]
    measured[2] = None
    sheet.columns.append(Column('Yield', 'number', measured))
    return presenter, presenter.analyze_factorial(
        6, [4, 5], selected_terms=[[0], [1], [0, 1]], include_blocks=blocks > 1)


class ExcelFactorialVerificationTests(unittest.TestCase):
    def test_multiblock_interactions_and_saved_rows_survive_project_reopen(self):
        presenter, entry = factorial_fixture(centers=1)
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'factorial.mpx'
            presenter.save(project)
            presenter = Presenter()
            presenter.load(project)
            reopened = next(item for item in presenter.history if item['entry_id'] == entry['entry_id'])
            workbook = load_workbook(write_verification(project.with_suffix('.xlsx'), presenter, reopened))
            self.assertEqual([c.value for c in workbook['Inputs'][1]],
                             ['Worksheet row', 'In saved fit', 'Yield', 'Heat', 'Time', 'Blocks'])
            self.assertFalse(workbook['Inputs']['B4'].value)
            result = reopened['result']
            fit = workbook['Calculations']
            self.assertEqual([fit.cell(row, 1).value for row in range(2, result['count'] + 2)],
                             [index + 1 for index in result['row_indices']])
            coding = workbook['Factor Coding']
            self.assertEqual([coding.cell(2, col).value for col in range(7, 12)],
                             ['Heat', 10, 30, 20, 10])
            self.assertEqual([coding.cell(9, col).value for col in range(7, 10)], [3, -1, -1])
            self.assertIn('Inputs!F2', coding['D2'].value)
            self.assertIn('VLOOKUP', coding['E2'].value)
            self.assertIn("COUNT('Factor Coding'!B2:C2)=2", fit['G2'].value)
            self.assertIn("PRODUCT('Factor Coding'!B2,'Factor Coding'!C2)", fit['G2'].value)
            verification = workbook['Verification']
            self.assertEqual(verification['A21'].value, 'Effect: Heat*Time')
            self.assertIn('2*C15', verification['C21'].value)
            chart = verification._charts[1]
            self.assertEqual((chart.x_axis.axPos, chart.y_axis.axPos), ('l', 'b'))
            self.assertEqual(chart.series[0].val.numRef.f, "'Verification'!$C$19:$C$21")

    def test_changed_block_assignments_and_missing_legacy_coding_require_refit(self):
        presenter, entry = factorial_fixture()
        blocks = presenter.worksheet.columns[3].values
        blocks[0] = 1 if blocks[0] != 1 else 2
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'reject.xlsx'
            with self.assertRaisesRegex(ValueError, 'Rerun'):
                write_verification(path, presenter, entry)
            self.assertFalse(path.exists())
            presenter, entry = factorial_fixture()
            entry['result'].pop('verification_block_columns')
            with self.assertRaisesRegex(ValueError, 'Rerun'):
                write_verification(path, presenter, entry)
            self.assertFalse(path.exists())

    def test_unblocked_factorial_menu_exports_with_no_block_inputs(self):
        app = QApplication.instance() or QApplication([])
        presenter, entry = factorial_fixture(blocks=1)
        window = ModernWindow(presenter)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'factorial.xlsx'
                action = next(action for action in window.build_output_context_menu(entry).actions()
                              if action.text().startswith('Export Excel Verification'))
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')):
                    action.trigger()
                workbook = load_workbook(path)
                self.assertEqual(workbook['Inputs'].max_column, 5)
                self.assertEqual(len(workbook['Verification']._charts), 2)
        finally:
            presenter.dirty = False
            window.close()
            window.deleteLater()
            app.processEvents()
