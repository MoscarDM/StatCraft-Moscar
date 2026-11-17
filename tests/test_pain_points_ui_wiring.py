import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit

from statcraft.app import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft import session_io


def _app():
    return QApplication.instance() or QApplication(sys.argv)


class PainPointsUIWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.win = ModernWindow()

    def tearDown(self):
        self.win.presenter.dirty = False
        self.win._confirm_leave = lambda: True
        self.win.close()

    def _menu_actions(self):
        actions = []
        for act in self.win.menuBar().actions():
            menu = act.menu()
            if not menu:
                continue
            stack = list(menu.actions())
            while stack:
                item = stack.pop(0)
                if item.menu():
                    stack.extend(item.menu().actions())
                elif not item.isSeparator():
                    actions.append(item)
        return actions

    def _make_graph_entry(self, title="Histogram of X"):
        entry = {
            "entry_id": "g1",
            "title": title,
            "worksheet_name": self.win.presenter.worksheet.name,
            "time": "12:00:00",
            "graph_only": True,
            "result": {
                "title": title,
                "text": "",
                "tables": [],
                "graphs": [
                    {
                        "type": "histogram",
                        "title": title,
                        "values": [1.0, 2.0, 3.0, 4.0, 5.0],
                    }
                ],
            },
        }
        self.win.presenter.history.append(entry)
        self.win.selected_entry = entry
        return entry

    def test_01_freeze_and_unfreeze_panes(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertIn("Freeze Panes", texts)
        self.assertIn("Unfreeze Rows/Cols", texts)

        self.win.presenter.worksheet.columns = [
            Column("A", "number", [1, 2, 3, 4]),
            Column("B", "number", [5, 6, 7, 8]),
            Column("C", "number", [9, 10, 11, 12]),
        ]
        self.win.refresh()
        self.win.table.setCurrentCell(2, 1)
        self.win.freeze_panes()
        self.assertEqual(self.win._frozen_rows, 2)
        self.assertEqual(self.win._frozen_cols, 1)
        self.assertIn("2R × 1C", self.win.status_freeze_label.text())

        self.win.refresh()
        self.assertEqual(self.win._frozen_rows, 2)
        self.assertEqual(self.win._frozen_cols, 1)

        self.win.unfreeze_panes()
        self.assertEqual(self.win._frozen_rows, 0)
        self.assertEqual(self.win._frozen_cols, 0)
        self.assertEqual(self.win.status_freeze_label.text(), "")

    def test_02_autosave_and_crash_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "autosave_recovery.json"
            with patch.object(self.win, "_autosave_path", return_value=snap_path):
                self.win.presenter.worksheet.columns = [Column("Score", "number", [10.0, 20.0])]
                self.win.presenter.history = [{"title": "Mean Score", "worksheet_name": "Worksheet 1", "result": {"text": "15"}}]
                saved_path = self.win.autosave_now()
                self.assertTrue(Path(saved_path).is_file())

                # Reset state and recover
                self.win.presenter.worksheet = Worksheet("Blank", [Column("C1", "number", [])])
                self.win.presenter.history = []
                recovered = self.win.recover_autosave_if_present()
                self.assertTrue(recovered)
                self.assertEqual(self.win.presenter.worksheet.columns[0].name, "Score")
                self.assertEqual(len(self.win.presenter.history), 1)

                # Clean save clears autosave
                proj_path = Path(tmp) / "clean_proj.mpx"
                self.win.save_path(str(proj_path))
                self.assertFalse(snap_path.exists())

                # Re-create autosave and verify clean closeEvent clears it when not dirty
                self.win.autosave_now()
                self.assertTrue(snap_path.is_file())
                self.win.presenter.dirty = False
                self.win.close()
                self.assertFalse(snap_path.exists())

    def test_03_save_history_and_clear_history(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertIn("Save History As…", texts)
        self.assertIn("Clear History", texts)
        self.assertEqual(self.win.save_history_btn.text(), "Save History As…")
        self.assertEqual(self.win.clear_history_btn.text(), "Clear History")

        self.win._cmd_history = ["LET C1 = 1:5", "MEAN C1"]
        self.win.command_history_view.setPlainText("LET C1 = 1:5\nMEAN C1")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "hist.mtb"
            with patch("statcraft.modern_app.QFileDialog.getSaveFileName", return_value=(str(out), "Minitab Exec (*.mtb)")):
                res = self.win.save_history_dialog()
            self.assertEqual(res, out)
            self.assertIn("MEAN C1", out.read_text(encoding="utf-8"))

        self.win.clear_history()
        self.assertEqual(self.win._cmd_history, [])
        self.assertEqual(self.win.command_history_view.toPlainText(), "")

    def test_04_save_session_window(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertIn("Save Session Window…", texts)
        self.win.presenter.history = [
            {"title": "Summary", "worksheet_name": "Worksheet 1", "time": "10:00", "result": {"text": "Mean = 5"}}
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out_html = Path(tmp) / "session.html"
            with patch("statcraft.modern_app.QFileDialog.getSaveFileName", return_value=(str(out_html), "HTML Document (*.html)")):
                res = self.win.save_session_window_dialog()
            self.assertEqual(res, out_html)
            self.assertIn("Mean = 5", out_html.read_text(encoding="utf-8"))

    def test_05_navigator_output_ordering(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertIn("Chronological", texts)
        self.assertIn("By Worksheet", texts)
        self.assertIn("By Title", texts)

        self.win._navigator_group_by_sheet = False
        self.win.presenter.history = [
            {"origin": "statcraft", "title": "Zebra", "worksheet_name": "Sheet B", "worksheet": "Sheet B", "result": {"text": "1"}},
            {"origin": "statcraft", "title": "Alpha", "worksheet_name": "Sheet A", "worksheet": "Sheet A", "result": {"text": "2"}},
        ]
        self.win.set_navigator_order("title")
        self.assertEqual(self.win._navigator_order, "title")
        titles = [self.win.navigator.topLevelItem(i).text(0) for i in range(self.win.navigator.topLevelItemCount())]
        self.assertEqual(titles, ["Alpha", "Zebra"])

        self.win.set_navigator_order("chronological")
        titles_chron = [self.win.navigator.topLevelItem(i).text(0) for i in range(self.win.navigator.topLevelItemCount())]
        self.assertEqual(titles_chron, ["Zebra", "Alpha"])

    def test_06_split_and_unsplit_view(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertIn("Split View", texts)
        self.assertIn("Unsplit View", texts)

        self.win.presenter.history = [
            {"entry_id": "e1", "title": "Out 1", "result": {"text": "A"}},
            {"entry_id": "e2", "title": "Out 2", "result": {"text": "B"}},
        ]
        self.win.refresh()
        self.win.show_result(self.win.presenter.history[0])
        self.win.show_result(self.win.presenter.history[1])
        self.assertTrue(self.win.split_output_view())
        self.assertTrue(self.win._workspace.is_split())
        self.assertTrue(self.win.unsplit_output_view())
        self.assertFalse(self.win._workspace.is_split())

    def test_07_tile_with_worksheet(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertGreaterEqual(texts.count("Tile With Worksheet"), 2)

        self.win.set_view_mode("data")
        self.win.tile_with_worksheet()
        self.assertEqual(self.win._view_mode, "both")
        sizes = self.win.work_splitter.sizes()
        self.assertEqual(len(sizes), 2)
        self.assertAlmostEqual(sizes[0], sizes[1], delta=2)

    def test_08_merge_worksheets_menu_and_handler(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertIn("Merge Worksheets…", texts)

        with patch("statcraft.data_prep_dialogs.open_dialog") as mock_open:
            self.win.merge_worksheets_dialog()
            mock_open.assert_called_once_with(self.win, "merge")

    def test_09_append_to_report_pad(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertGreaterEqual(texts.count("Append to ReportPad"), 2)

        entry = {"entry_id": "r1", "title": "Regression", "result": {"text": "R-sq = 99%"}}
        self.win.presenter.history = [entry]
        self.win.selected_entry = entry
        self.assertTrue(self.win.append_active_to_report_pad())
        self.assertIn("Regression", self.win._workspace.pad.toPlainText())

    def test_10_set_cell_comment(self):
        actions = [a for a in self._menu_actions() if a.text() == "Set Cell Comment…"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].shortcut().toString(), "Ctrl+Shift+M")

        self.win.presenter.worksheet.columns = [Column("X", "number", [1.0, 2.0])]
        self.win.refresh()
        self.win.table.setCurrentCell(0, 0)
        with patch("statcraft.modern_app.QInputDialog.getMultiLineText", return_value=("Check outlier", True)):
            self.win.set_cell_comment_dialog()
        self.assertEqual(self.win.presenter.worksheet.columns[0].metadata["cell_comments"]["0"], "Check outlier")

    def test_11_auto_update_graphs(self):
        act = next((a for a in self._menu_actions() if a.text() == "Update Graph Automatically"), None)
        self.assertIsNotNone(act)
        self.assertTrue(act.isCheckable())

        with patch.object(self.win, "update_all_graphs", return_value=0) as mock_update:
            self.win.toggle_auto_update_graphs(True)
            self.assertTrue(self.win._auto_update_graphs)
            self.assertTrue(self.win.auto_update_graphs_action.isChecked())
            self.assertEqual(mock_update.call_count, 1)

            self.win._call(lambda: self.win.presenter.set_cell(0, 0, "42"))
            self.assertEqual(mock_update.call_count, 2)

            self.win.toggle_auto_update_graphs(False)
            self.assertFalse(self.win._auto_update_graphs)

    def test_12_add_reference_and_percentile_lines(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertIn("Add Reference Line…", texts)
        self.assertIn("Add Percentile Line…", texts)

        entry = self._make_graph_entry()
        self.win.presenter.worksheet.columns = [Column("X", "number", [10.0, 20.0, 30.0, 40.0])]

        def _accept_ref(dlg):
            edits = dlg.findChildren(QLineEdit)
            edits[0].setText("25")
            edits[1].setText("Target")
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", _accept_ref):
            self.assertTrue(self.win.add_reference_line_dialog())
        self.assertEqual(entry["reference_lines"][-1]["value"], 25.0)
        self.assertEqual(entry["reference_lines"][-1]["label"], "Target")

        def _accept_pct(dlg):
            edits = dlg.findChildren(QLineEdit)
            edits[0].setText("50")
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", _accept_pct):
            self.assertTrue(self.win.add_percentile_line_dialog())
        self.assertEqual(entry["reference_lines"][-1]["value"], 25.0)
        self.assertEqual(entry["reference_lines"][-1]["label"], "P50")

    def test_13_edit_graph_titles_dialog(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertIn("Edit Graph Title / Subtitle / Footnote…", texts)

        entry = self._make_graph_entry()

        def _accept_titles(dlg):
            edits = dlg.findChildren(QLineEdit)
            edits[0].setText("New Title")
            edits[1].setText("Sub A")
            edits[2].setText("Source: Lab")
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", _accept_titles):
            self.assertTrue(self.win.edit_graph_titles_dialog())
        self.assertEqual(entry["title"], "New Title")
        self.assertEqual(entry["graph_presentation"]["subtitle"], "Sub A")
        self.assertEqual(entry["graph_presentation"]["footnote"], "Source: Lab")

    def test_14_toggle_graph_gridlines(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertIn("Toggle Gridlines", texts)

        entry = self._make_graph_entry()
        first = self.win.toggle_graph_gridlines_action()
        second = self.win.toggle_graph_gridlines_action()
        self.assertEqual(second, not first)
        self.assertEqual(entry["graph_presentation"]["grid_enabled"], second)

    def test_15_brushing_color_and_palette(self):
        texts = [a.text() for a in self._menu_actions()]
        self.assertIn("Set Brushing Color…", texts)
        self.assertGreaterEqual(texts.count("Show/Hide Brushing Palette"), 2)

        with patch("statcraft.modern_app.QColorDialog.getColor", return_value=QColor("#2563eb")):
            chosen = self.win.set_brushing_color_dialog()
        self.assertEqual(chosen, "#2563eb")
        self.assertEqual(self.win._brush_color, "#2563eb")

        self.assertTrue(self.win.toggle_brushing_palette(True))
        self.assertTrue(self.win._brushing_palette_visible)
        self.assertIn("#2563eb", self.win.status_brush_label.text())
        self.assertFalse(self.win.toggle_brushing_palette(False))
        self.assertFalse(self.win._brushing_palette_visible)


if __name__ == "__main__":
    unittest.main()
