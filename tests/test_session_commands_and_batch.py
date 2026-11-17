import os
import sys
import unittest
from PySide6.QtWidgets import QApplication
from statcraft.app import Presenter
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.session_commands import parse_script_blocks

os.environ["QT_QPA_PLATFORM"] = "offscreen"


class TestSessionCommandsAndBatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_parse_comments_and_semicolon_subcommands(self):
        script = """
        NOTE Sample Batch Exec Script
        # Comment line
        CAPABILITY C1;
          LSPEC 9.0;
          USPEC 11.0;
          TARGET 10.0.
        LET K1 = MEAN(C1) # Trailing comment
        """
        blocks = parse_script_blocks(script)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0][0], "CAPABILITY C1")
        self.assertEqual(blocks[0][1], ["LSPEC 9.0", "USPEC 11.0", "TARGET 10.0"])
        self.assertEqual(blocks[1][0], "LET K1 = MEAN(C1)")

    def test_batch_mtb_script_execution_and_do_loop(self):
        p = Presenter()
        p.worksheet = Worksheet("Batch", [
            Column("Diameter", "number", [9.8, 10.1, 10.0, 9.9, 10.2, 10.0, 9.7, 10.3]),
            Column("Shift", "text", ["Day", "Day", "Night", "Night", "Day", "Day", "Night", "Night"]),
        ])
        script = """
        # Set values and compute capability with subcommands
        SET C3; 1:8.
        NAME C3 'Index'
        LET K1 = MEAN(C1)
        CAPABILITY C1;
          LSPEC 9.5;
          USPEC 10.5;
          TARGET 10.0.
        RANDOM 8 C4;
          WEIBULL 2.0 10.0.
        TALLY C2
        INDICATOR C2
        DO K2 = 1:2
          LET C5 = C1 + K2
        ENDDO
        """
        entries = p.execute_session_script(script)
        self.assertEqual(len(entries), 9)
        self.assertEqual(p.worksheet.columns[2].name, "Index")
        self.assertEqual(p.worksheet.columns[2].values, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
        self.assertAlmostEqual(p.worksheet.constants[0].values[0], 10.0, places=4)
        self.assertEqual(len(p.worksheet.columns[3].values), 8)
        self.assertIn("Shift_Day", [c.name for c in p.worksheet.columns])
        self.assertEqual(p.worksheet.columns[4].values[0], 11.8)

    def test_subset_and_erase_commands(self):
        p = Presenter()
        p.worksheet = Worksheet("Main", [
            Column("Val", "number", [5.0, 15.0, 25.0]),
            Column("Temp", "number", [100.0, 200.0, 300.0]),
        ])
        p.execute_session_script("SUBSET; WHERE C1 >= 15; NAME 'Filtered'.")
        self.assertEqual(p.worksheet.name, "Filtered")
        self.assertEqual(p.worksheet.row_count, 2)
        p.execute_session_command("ERASE C2")
        self.assertEqual(p.worksheet.columns[1].values, [])
        self.assertEqual(p.worksheet.columns[1].name, "C2")

    def test_command_line_ui_executes_multiline(self):
        win = ModernWindow(sandbox_mode=True)
        win._confirm_leave = lambda: True
        win.presenter.worksheet = Worksheet("CmdUI", [Column("X", "number", [1.0, 2.0, 3.0, 4.0, 5.0])])
        win.command_editor.setPlainText("CAPABILITY C1;\n LSPEC 0;\n USPEC 10.")
        win.run_command_line()
        self.assertTrue(any("Capability" in e.get("title", "") for e in win.presenter.history))
        self.assertTrue(hasattr(win, "run_mtb_script_dialog"))
        self.assertTrue(hasattr(win, "round_datetime_dialog"))
        self.assertTrue(hasattr(win, "convert_text_to_datetime_dialog"))
        win.close()

    def test_convert_text_and_round_datetime(self):
        from statcraft.model import display_date
        p = Presenter()
        p.worksheet = Worksheet("Dates", [
            Column("RawDates", "text", ["2026-05-14 14:35:22", "11/09/2026", None]),
        ])
        p.convert_text_to_datetime(0, "", "ParsedDate")
        self.assertEqual(p.worksheet.columns[1].kind, "date")
        self.assertEqual(display_date(p.worksheet.columns[1].values[1]), "2026-11-09")

        p.round_datetime(1, "Month", "MonthStart")
        self.assertEqual(display_date(p.worksheet.columns[2].values[0]), "2026-05-01")
        self.assertEqual(display_date(p.worksheet.columns[2].values[1]), "2026-11-01")

    def test_local_macro_with_do_loop_and_conditional(self):
        p = Presenter()
        script = """
        MACRO
        SUMSEQ N RES
        MCONSTANT N I S
        MCOLUMN RES
        LET S = 0
        DO I = 1:N
          IF I > 2
            LET S = S + I
          ENDIF
        ENDDO
        LET RES(1) = S
        ENDMACRO
        %SUMSEQ 4 C1
        """
        p.execute_session_script(script)
        self.assertEqual(p.worksheet.columns[0].values[0], 7)

    def test_global_macro_and_if_elseif_else_and_matrix(self):
        p = Presenter()
        p.worksheet = Worksheet("MacroTest", [Column("X", "number", [5.0, 10.0])])
        script = """
        GMACRO
        CLASSIFY
        MCONSTANT THRESH
        MMATRIX M1
        LET THRESH = MEAN(C1)
        IF THRESH < 5
          LET K1 = -1
        ELSEIF THRESH = 7.5
          LET K1 = 0
        ELSE
          LET K1 = 1
        ENDIF
        ENDMACRO
        CLASSIFY
        """
        p.execute_session_script(script)
        self.assertEqual(p.worksheet.constants[0].values[0], 0.0)

    def test_macro_runaway_loop_recursion_and_partial_def_guards(self):
        p = Presenter()
        # Unclosed MACRO must not leave partial definition
        with self.assertRaises(ValueError):
            p.execute_session_script("MACRO\nBADMAC\nLET K1 = 1")
        with self.assertRaises(ValueError):
            p.execute_session_script("%BADMAC")

        # Runaway DO loop hits MAX_MACRO_STEPS
        with self.assertRaises(ValueError):
            p.execute_session_script("DO K1 = 1:200000\nLET K2 = K1\nENDDO")

        # Infinite recursion hits recursion guard
        rec_script = """
        MACRO
        INFREC
        %INFREC
        ENDMACRO
        %INFREC
        """
        with self.assertRaises(ValueError):
            p.execute_session_script(rec_script)

    def test_summary_print_read_control_multivariate_and_ts_verbs(self):
        p = Presenter()
        p.execute_session_script("READ C1 C2; 10 20; 30 40; 50 60.")
        self.assertEqual(p.worksheet.columns[0].values, [10.0, 30.0, 50.0])
        self.assertEqual(p.worksheet.columns[1].values, [20.0, 40.0, 60.0])

        e_mean = p.execute_session_command("MEAN C1 K1")
        e_sd = p.execute_session_command("STDEV C1")
        e_med = p.execute_session_command("MEDIAN C1")
        e_print = p.execute_session_command("PRINT C1 C2")
        self.assertAlmostEqual(p.worksheet.constants[0].values[0], 30.0)
        self.assertAlmostEqual(e_mean["result"]["value"], 30.0)
        self.assertAlmostEqual(e_sd["result"]["value"], 20.0)
        self.assertAlmostEqual(e_med["result"]["value"], 30.0)
        self.assertIn("10.0\t20.0", e_print["result"]["text"])

        # Attribute, Time-Weighted, Multivariate, and Time-Series verbs
        p.worksheet = Worksheet("Rich", [
            Column("Defects", "number", [2, 3, 1, 4, 2, 5, 3, 2, 1, 3, 4, 2]),
            Column("SampleN", "number", [50] * 12),
            Column("X1", "number", [10.1, 10.4, 9.8, 10.5, 11.2, 10.9, 11.6, 12.1, 11.8, 12.4, 12.9, 13.2]),
            Column("X2", "number", [20.5, 21.0, 19.7, 21.3, 22.4, 21.9, 23.1, 24.0, 23.6, 24.8, 25.4, 26.1]),
            Column("X3", "number", [5.2, 5.1, 5.4, 5.0, 4.9, 5.1, 4.8, 4.7, 4.9, 4.6, 4.5, 4.4]),
        ])
        entries = p.execute_session_script("""
        CCHART C1
        PCHART C1 C2
        EWMA C3
        CUSUM C3
        PCA C3 C4 C5
        FACTOR C3 C4 C5
        CLUSTER C3 C4 C5
        KMEANS C3 C4 C5
        ACF C3
        PACF C3
        ARIMA 1 0 0 C3
        """)
        self.assertEqual(len(entries), 11)
        self.assertTrue(all(isinstance(e, dict) and e.get("title") for e in entries))


if __name__ == "__main__":
    unittest.main()
