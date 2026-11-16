import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QDialog

from statcraft.app import Column, Presenter
from statcraft.autofill_engine import autofill_sequence, get_custom_lists, set_custom_lists
from statcraft.conditional_formatting import effective_highlights, validate_rule
from statcraft.modern_app import ModernWindow


def _app():
    return QApplication.instance() or QApplication(sys.argv)


class MinitabParityRound4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.win = ModernWindow()

    def tearDown(self):
        self.win.close()

    def _menu_texts(self):
        texts = []
        for act in self.win.menuBar().actions():
            m = act.menu()
            if not m:
                continue
            stack = list(m.actions())
            while stack:
                a = stack.pop(0)
                if a.menu():
                    stack.extend(a.menu().actions())
                elif not a.isSeparator():
                    texts.append(a.text())
        return texts

    def test_new_conditional_formatting_rules(self):
        # #46094 Out of control (I-MR Nelson Rule 1 and explicit rows)
        col_ooc = Column("X", "number", [10.0, 10.2, 9.9, 10.1, 10.0, 40.0])
        hl_ooc = effective_highlights(col_ooc, rules=[{"type": "out_of_control", "color": "#f8d7da"}])
        self.assertEqual(hl_ooc, {"5": "#f8d7da"})

        col_ooc_meta = Column("X", "number", [1.0, 2.0, 3.0], metadata={"out_of_control_rows": [1]})
        hl_ooc_meta = effective_highlights(col_ooc_meta, rules=[{"type": "out_of_control", "color": "#f8d7da"}])
        self.assertEqual(hl_ooc_meta, {"1": "#f8d7da"})

        # #46101 Values from a list (in_list / not_in_list)
        col_txt = Column("Grade", "text", ["A", "B", "C", "D"])
        hl_in = effective_highlights(col_txt, rules=[{"type": "in_list", "param1": "a, c", "color": "#d4edda"}])
        self.assertEqual(hl_in, {"0": "#d4edda", "2": "#d4edda"})
        hl_not_in = effective_highlights(col_txt, rules=[{"type": "not_in_list", "param1": "A, C", "color": "#fff3cd"}])
        self.assertEqual(hl_not_in, {"1": "#fff3cd", "3": "#fff3cd"})

        # #46088 Date rules (date_before / date_after / date_between)
        d1 = Presenter.parse_cell("2025-01-10", "date")
        d2 = Presenter.parse_cell("2025-06-15", "date")
        d3 = Presenter.parse_cell("2025-12-20", "date")
        col_dt = Column("Date", "date", [d1, d2, d3])
        hl_between = effective_highlights(
            col_dt,
            rules=[{"type": "date_between", "param1": "2025-02-01", "param2": "2025-11-01", "color": "#d4edda"}],
        )
        self.assertEqual(hl_between, {"1": "#d4edda"})
        hl_before = effective_highlights(
            col_dt,
            rules=[{"type": "date_before", "param1": "2025-02-01", "color": "#fff3cd"}],
        )
        self.assertEqual(hl_before, {"0": "#fff3cd"})
        hl_after = effective_highlights(
            col_dt,
            rules=[{"type": "date_after", "param1": "2025-11-01", "color": "#f8d7da"}],
        )
        self.assertEqual(hl_after, {"2": "#f8d7da"})
        self.assertEqual(validate_rule({"type": "in_list", "param1": ["X", "Y"]})["param1"], "X, Y")

    def test_command_line_history_and_clear_text(self):
        # #46139, #46146, #46028
        self.assertEqual(self.win.clear_cmd_btn.text(), "Clear Text")
        self.win._cmd_history = ["LET C1 = 1:5", "MEAN C1"]
        self.win._cmd_history_idx = 2

        self.win.prev_command()
        self.assertEqual(self.win.command_editor.toPlainText(), "MEAN C1")
        self.win.prev_command()
        self.assertEqual(self.win.command_editor.toPlainText(), "LET C1 = 1:5")
        self.win.next_command()
        self.assertEqual(self.win.command_editor.toPlainText(), "MEAN C1")
        self.win.next_command()
        self.assertEqual(self.win.command_editor.toPlainText(), "")

        self.win.command_editor.setPlainText("DESCRIBE C1")
        self.win.clear_command_text()
        self.assertEqual(self.win.command_editor.toPlainText(), "")

    def test_custom_lists_autofill_integration(self):
        # #46032 Define Custom Lists
        orig = get_custom_lists()
        try:
            set_custom_lists([["Bronze", "Silver", "Gold"]])
            self.assertEqual(autofill_sequence(["Bronze"], 3), ["Silver", "Gold", "Bronze"])
        finally:
            set_custom_lists(orig)

    def test_go_to_next_column_and_pane_focus(self):
        # #46046 Go To Next Column (skipping hidden column)
        self.win.presenter.worksheet.columns = [
            Column("A", "number", [1, 2]),
            Column("B", "number", [3, 4]),
            Column("C", "number", [5, 6]),
        ]
        self.win._hidden_columns = {1}
        self.win.refresh()
        self.win.table.setCurrentCell(1, 0)
        self.win.go_to_next_column()
        self.assertEqual(self.win.table.currentRow(), 0)
        self.assertEqual(self.win.table.currentColumn(), 2)

        # #46159, #46160, #46171, #46178 Pane Focus
        self.win.set_view_mode("data")
        self.win.focus_session_window()
        self.assertFalse(self.win.output_pane.isHidden())
        self.win.focus_history_window()
        self.assertFalse(self.win.command_line_pane.isHidden())
        self.win.focus_navigator_window()
        self.assertFalse(self.win.navigator_container.isHidden())
        self.win.set_view_mode("output")
        self.win.focus_data_window()
        self.assertFalse(self.win.worksheet_pane.isHidden())

    def test_close_current_graph_and_menus(self):
        # #46157 Close Current Graph + menu parity items (#46099, #46040, #46048, #46051, #46052, #46053, #46111, #46105, #46106)
        texts = self._menu_texts()
        expected = [
            "Manage Rules…",
            "Hide or Unhide Columns…",
            "Column Width…",
            "Standard Column Width…",
            "Select Data Font…",
            "Select Label Font…",
            "Define Custom Lists…",
            "Go To Next Column",
            "Close Current Graph",
            "Session Window",
            "History Window",
            "Project Manager / Navigator",
            "Data Window",
            "&StatGuide (Interpret Output)…",
            "&Getting Started…",
            "&How Do I?…",
        ]
        for label in expected:
            self.assertIn(label, texts, f"Missing menu item: {label}")

        # Verify close_current_graph runs cleanly even with no open tabs
        self.win.close_current_graph()
        self.assertIn("Closed active graph/output tab", self.win.statusBar().currentMessage())


if __name__ == "__main__":
    unittest.main()
