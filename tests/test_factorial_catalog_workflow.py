import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QTableWidget
from statcraft.doe_dialogs import CreateFactorialDialog
from statcraft.doe_planner_dialog import DOEPlannerDialog
from statcraft.app import Presenter


class FactorialCatalogWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_fraction_selection_creates_the_displayed_design(self):
        dialog = CreateFactorialDialog(None)
        self.addCleanup(dialog.deleteLater)
        dialog.factor_count.setCurrentText('8')

        def select_fraction(setup):
            table = setup.findChild(QTableWidget)
            self.assertEqual([int(table.item(row, 1).text()) for row in range(table.rowCount())],
                             [256, 128, 64, 32, 16])
            self.assertEqual(table.item(4, 2).text(), '4')
            table.setCurrentCell(4, 0)
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, 'exec', select_fraction):
            dialog.designs()
        dialog.validate()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        presenter = Presenter()
        presenter.create_factorial(**dialog.parameters)
        self.assertEqual(presenter.worksheet.row_count, 32)
        self.assertEqual(dialog.parameters['generators'],
                         {'E':'BCD','F':'ACD','G':'ABC','H':'ABD'})

    def test_screening_create_and_save_reopen(self):
        dialog = CreateFactorialDialog(None)
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.design_types[3].isEnabled())
        dialog.design_types[3].setChecked(True)

        def configure(planner):
            self.assertEqual(planner.family.currentData(), 'plackett_burman')
            planner.factor_count.setValue(5)
            planner.pb_runs.setCurrentIndex(planner.pb_runs.findData(20))
            planner.randomize.setChecked(False)
            planner.create()
            return planner.result()

        with patch.object(DOEPlannerDialog, 'exec', configure):
            dialog.validate()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        presenter = Presenter()
        presenter.create_doe_plan(**dialog.parameters)
        self.assertEqual(presenter.worksheet.row_count, 20)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'screening.mpx'
            presenter.save(path)
            reopened = Presenter()
            reopened.load(path)
            self.assertEqual(reopened.worksheet.metadata['doe']['planner_configuration'], dialog.parameters)
            self.assertEqual(reopened.worksheet.columns, presenter.worksheet.columns)

    def test_general_factorial_mixed_levels(self):
        dialog = CreateFactorialDialog(None)
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.design_types[4].isEnabled())
        dialog.design_types[4].setChecked(True)

        def configure(planner):
            planner.factor_count.setValue(2)
            planner.factor_table.item(0,2).setText('10, 20, 30')
            planner.factor_table.cellWidget(1,1).setCurrentIndex(1)
            planner.factor_table.item(1,2).setText('Low, High')
            planner.randomize.setChecked(False)
            planner.create()
            return planner.result()

        with patch.object(DOEPlannerDialog, 'exec', configure):
            dialog.validate()
        presenter = Presenter()
        presenter.create_doe_plan(**dialog.parameters)
        self.assertEqual(presenter.worksheet.row_count, 6)
        self.assertEqual(set(presenter.worksheet.columns[4].values), {10,20,30})
        self.assertEqual(set(presenter.worksheet.columns[5].values), {'Low','High'})

    def test_cancel_does_not_accept_or_replace_parameters(self):
        dialog = CreateFactorialDialog(None)
        self.addCleanup(dialog.deleteLater)
        dialog.design_types[3].setChecked(True)
        with patch.object(DOEPlannerDialog, 'exec', return_value=QDialog.DialogCode.Rejected):
            dialog.validate()
        self.assertIsNone(dialog.parameters)
        self.assertEqual(dialog.catalog_parameters, {})
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
