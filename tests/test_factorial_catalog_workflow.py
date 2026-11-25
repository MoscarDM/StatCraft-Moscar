import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QSpinBox, QTableWidget
from statcraft.doe_dialogs import CreateFactorialDialog
from statcraft.app import Presenter


class FactorialCatalogWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_fraction_selection_creates_the_displayed_design(self):
        dialog = CreateFactorialDialog(None)
        self.addCleanup(dialog.deleteLater)
        dialog.factor_count.setCurrentText('8')
        self.assertFalse(dialog.ok_button.isEnabled())

        def select_fraction(setup):
            table = setup.findChild(QTableWidget)
            self.assertEqual([int(table.item(row, 1).text()) for row in range(table.rowCount())],
                             [16, 32, 64, 128, 256])
            self.assertEqual(table.item(0, 2).text(), 'IV')
            table.setCurrentCell(0, 0)
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, 'exec', select_fraction):
            dialog.designs()
        self.assertTrue(dialog.ok_button.isEnabled())
        dialog.validate()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        presenter = Presenter()
        presenter.create_factorial(**dialog.parameters)
        self.assertEqual(presenter.worksheet.row_count, 16)
        self.assertEqual(dialog.parameters['generators'],
                         {'E':'BCD','F':'ACD','G':'ABC','H':'ABD'})

    def test_screening_create_and_save_reopen(self):
        dialog = CreateFactorialDialog(None)
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.design_types[3].isEnabled())
        dialog.design_types[3].setChecked(True)
        dialog.factor_count.setCurrentText('5')

        def configure_pb(sub):
            combo = sub.findChild(QComboBox)
            idx = combo.findData(20)
            self.assertGreaterEqual(idx, 0)
            combo.setCurrentIndex(idx)
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, 'exec', configure_pb):
            dialog.designs()
        self.assertTrue(dialog.ok_button.isEnabled())
        dialog.randomize = False
        dialog.seed = 1
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
            self.assertEqual(reopened.worksheet.metadata['doe']['planner_configuration']['kind'], 'plackett_burman')
            self.assertEqual(reopened.worksheet.columns, presenter.worksheet.columns)

    def test_general_factorial_mixed_levels(self):
        dialog = CreateFactorialDialog(None)
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.design_types[4].isEnabled())
        dialog.design_types[4].setChecked(True)
        dialog.factor_count.setCurrentText('2')

        from PySide6.QtWidgets import QDialogButtonBox

        def configure_gf_designs(sub):
            spins = sub.findChildren(QSpinBox)
            spins[0].setValue(3)
            spins[1].setValue(2)
            sub.findChild(QDialogButtonBox).accepted.emit()
            return sub.result()

        with patch.object(QDialog, 'exec', configure_gf_designs):
            dialog.designs()

        def configure_gf_factors(sub):
            table = sub.findChild(QTableWidget)
            table.item(0, 3).setText('10, 20, 30')
            table.cellWidget(1, 2).setCurrentIndex(1)
            table.item(1, 3).setText('Low, High')
            sub.findChild(QDialogButtonBox).accepted.emit()
            return sub.result()

        with patch.object(QDialog, 'exec', configure_gf_factors):
            dialog.factor_settings()

        dialog.randomize = False
        dialog.seed = 1
        dialog.validate()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        presenter = Presenter()
        presenter.create_doe_plan(**dialog.parameters)
        self.assertEqual(presenter.worksheet.row_count, 6)
        self.assertEqual(set(presenter.worksheet.columns[4].values), {10, 20, 30})
        self.assertEqual(set(presenter.worksheet.columns[5].values), {'Low', 'High'})

    def test_cancel_does_not_accept_or_replace_parameters(self):
        dialog = CreateFactorialDialog(None)
        self.addCleanup(dialog.deleteLater)
        dialog.design_types[3].setChecked(True)
        with patch.object(QDialog, 'exec', return_value=QDialog.DialogCode.Rejected):
            dialog.designs()
        self.assertFalse(dialog.ok_button.isEnabled())
        dialog.validate()
        self.assertIsNone(dialog.parameters)
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
