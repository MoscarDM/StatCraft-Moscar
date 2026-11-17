"""Tests for Data > Concatenate and Date/Time Extract to Numeric/Text parity."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from statcraft.app import Presenter
from statcraft.model import Column, Worksheet, datetime_to_serial
from statcraft.modern_app import ModernWindow
from datetime import datetime


class DataConcatAndDatetimeExtractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_concatenate_columns_with_separator_and_undo(self):
        ws = Worksheet(
            "Batch",
            [
                Column("Line", "text", ["L1", "L2", None]),
                Column("Shift", "number", [1.0, 2.0, None]),
            ],
        )
        p = Presenter()
        p.worksheet = ws
        p.concatenate_columns([0, 1], separator="-", destination="BatchID")
        self.assertEqual(len(ws.columns), 3)
        self.assertEqual(ws.columns[2].name, "BatchID")
        self.assertEqual(ws.columns[2].kind, "text")
        self.assertEqual(ws.columns[2].values, ["L1-1", "L2-2", None])
        p.undo()
        self.assertEqual(len(ws.columns), 2)

    def test_extract_datetime_to_numeric_and_text(self):
        d1 = datetime_to_serial(datetime(2026, 11, 15, 14, 35, 20))  # Sunday
        d2 = datetime_to_serial(datetime(2026, 1, 5, 8, 5, 0))      # Monday
        ws = Worksheet("Dates", [Column("Stamp", "date", [d1, d2, None])])
        p = Presenter()
        p.worksheet = ws

        p.extract_datetime_to_numeric(0, component="Year", destination="Yr")
        p.extract_datetime_to_numeric(0, component="Quarter", destination="Qtr")
        p.extract_datetime_to_numeric(0, component="Day of Week", destination="DOW_Num")
        p.extract_datetime_to_text(0, component="Month", destination="MonthName")
        p.extract_datetime_to_text(0, component="Day of Week", destination="Weekday")

        by_name = {c.name: c for c in ws.columns}
        self.assertEqual(by_name["Yr"].values, [2026.0, 2026.0, None])
        self.assertEqual(by_name["Qtr"].values, [4.0, 1.0, None])
        # Sunday = 1, Monday = 2 (Minitab convention)
        self.assertEqual(by_name["DOW_Num"].values, [1.0, 2.0, None])
        self.assertEqual(by_name["MonthName"].values, ["November", "January", None])
        self.assertEqual(by_name["Weekday"].values, ["Sunday", "Monday", None])

    def test_modern_window_exposes_new_actions(self):
        win = ModernWindow(sandbox_mode=True)
        try:
            self.assertTrue(hasattr(win, "concatenate_columns_dialog"))
            self.assertTrue(hasattr(win, "extract_datetime_numeric_dialog"))
            self.assertTrue(hasattr(win, "extract_datetime_text_dialog"))
        finally:
            win.close()
            win.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
