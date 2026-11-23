"""Tests for Calc > Matrices Minitab parity (Arithmetic, Transpose, Invert, Eigenanalysis, Copy)."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from statcraft.app import Presenter
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow


class MatricesParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _sheet(self):
        return Worksheet(
            "MatSheet",
            [
                Column("X1", "number", [4.0, 2.0]),
                Column("X2", "number", [2.0, 3.0]),
                Column("Y1", "number", [1.0, 0.0]),
                Column("Y2", "number", [0.0, 1.0]),
            ],
        )

    def test_copy_arithmetic_transpose_invert_and_undo(self):
        ws = self._sheet()
        p = Presenter()
        p.worksheet = ws
        p.copy_columns_to_matrix([0, 1], dest_name="A")
        p.copy_columns_to_matrix([2, 3], dest_name="I2")
        self.assertEqual(len(ws.matrices), 2)

        p.matrix_arithmetic("Add", "A", right_name="I2", dest_name="A_plus_I")
        p.matrix_arithmetic("Multiply", "A", right_name="I2", dest_name="A_mul_I")
        p.matrix_arithmetic("Scalar", "I2", scalar=5.0, dest_name="FiveI")
        p.matrix_transpose("A", dest_name="AT")
        p.matrix_invert("A", dest_name="A_inv")

        by_name = {m.name: m for m in ws.matrices}
        self.assertEqual(by_name["A_plus_I"].as_rows(), [[5.0, 2.0], [2.0, 4.0]])
        self.assertEqual(by_name["A_mul_I"].as_rows(), [[4.0, 2.0], [2.0, 3.0]])
        self.assertEqual(by_name["FiveI"].as_rows(), [[5.0, 0.0], [0.0, 5.0]])
        self.assertEqual(by_name["AT"].as_rows(), [[4.0, 2.0], [2.0, 3.0]])

        # A = [[4, 2], [2, 3]], det = 8, A_inv = [[0.375, -0.25], [-0.25, 0.5]]
        inv_rows = by_name["A_inv"].as_rows()
        self.assertAlmostEqual(inv_rows[0][0], 0.375, places=6)
        self.assertAlmostEqual(inv_rows[0][1], -0.25, places=6)
        self.assertAlmostEqual(inv_rows[1][1], 0.5, places=6)

        # Copy back to worksheet columns
        p.copy_matrix_to_columns("A_inv", col_prefix="InvCol")
        self.assertEqual(ws.columns[-2].name, "InvCol_1")
        self.assertAlmostEqual(ws.columns[-2].values[0], 0.375, places=6)

        p.undo()
        self.assertEqual(len(ws.columns), 4)

    def test_eigenanalysis_symmetric_and_errors(self):
        ws = self._sheet()
        p = Presenter()
        p.worksheet = ws
        p.copy_columns_to_matrix([0, 1], dest_name="Sym")
        entry = p.matrix_eigenanalysis("Sym", store_values_col="EigVals", store_vectors_matrix="EigVecs")
        evals = entry["result"]["eigenvalues"]
        # Eigenvalues of [[4, 2], [2, 3]] are (7 +/- sqrt(17)) / 2
        self.assertAlmostEqual(evals[0], 5.5615528, places=5)
        self.assertAlmostEqual(evals[1], 1.4384472, places=5)
        self.assertEqual(ws.columns[-1].name, "EigVals")
        self.assertTrue(any(m.name == "EigVecs" for m in ws.matrices))

        # Singular matrix invert raises ValueError
        ws2 = Worksheet("Sing", [Column("C1", "number", [1.0, 2.0]), Column("C2", "number", [2.0, 4.0])])
        p2 = Presenter()
        p2.worksheet = ws2
        p2.copy_columns_to_matrix([0, 1], dest_name="S")
        with self.assertRaises(ValueError):
            p2.matrix_invert("S")

    def test_modern_window_exposes_matrix_dialogs(self):
        win = ModernWindow(sandbox_mode=True)
        try:
            for attr in (
                "copy_columns_to_matrix_dialog",
                "copy_matrix_to_columns_dialog",
                "matrix_arithmetic_dialog",
                "matrix_transpose_dialog",
                "matrix_invert_dialog",
                "matrix_eigenanalysis_dialog",
            ):
                self.assertTrue(hasattr(win, attr), f"Missing {attr}")
        finally:
            win.close()
            win.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
