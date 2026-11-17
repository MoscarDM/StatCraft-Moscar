import json
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

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from statcraft.model import Column, Matrix, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.spatial_view import DEFAULT_VIEW


def _app():
    return QApplication.instance() or QApplication(sys.argv)


class MinitabParityRound5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.win = ModernWindow()

    def tearDown(self):
        self.win.presenter.dirty = False
        self.win._confirm_leave = lambda: True
        self.win.close()

    def _menu_actions(self, menu_prefix=None):
        actions = []
        for top in self.win.menuBar().actions():
            menu = top.menu()
            if not menu:
                continue
            if menu_prefix is not None and top.text().replace("&", "") != menu_prefix:
                continue
            stack = list(menu.actions())
            while stack:
                item = stack.pop(0)
                if item.menu():
                    stack.extend(item.menu().actions())
                elif not item.isSeparator():
                    actions.append(item.text().replace("&", ""))
        return actions

    def _make_graph_entry(self, title="Histogram of Process"):
        self.win.presenter.worksheet = Worksheet(
            "Process",
            [Column("Process", "number", [1.2, 2.5, 2.8, 3.1, 4.0, 4.4, 5.1])],
        )
        entry = self.win.presenter.histogram_graphs([0])
        self.win.show_result(entry, target_graph_index=0)
        return entry

    def test_01_all_round5_menu_actions_present(self):
        all_texts = self._menu_actions()
        expected = [
            "Save ReportPad As…",
            "Print ReportPad…",
            "Close All Worksheets",
            "Save All Worksheets As…",
            "Order Columns by ID",
            "Order Columns by Name",
            "Order Constants by ID",
            "Order Constants by Name",
            "Order Matrices by ID",
            "Order Matrices by Name",
            "Print Session Window…",
            "Print History…",
            "Export Dialog Settings…",
            "Create Indicator Variables from Brushed Rows…",
            "Crosshair Mode",
            "Insert Graph Text Annotation…",
            "Duplicate Graph Annotation",
            "Reset 3D View Defaults",
        ]
        for label in expected:
            self.assertIn(label, all_texts, f"Missing menu item: {label}")
        self.assertIn("Create Indicator Variables from Brushed Rows…", self._menu_actions("Data"))
        self.assertIn("Create Indicator Variables from Brushed Rows…", self._menu_actions("Graph"))

    def test_02_save_and_print_report_pad(self):
        self.win.append_to_report_pad("Quality Summary <Alpha & Beta>")
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "pad.html"
            txt_path = Path(tmp) / "pad.txt"
            self.assertEqual(self.win.save_report_pad_dialog(html_path), html_path)
            html_content = html_path.read_text(encoding="utf-8")
            self.assertIn("Quality Summary &lt;Alpha &amp; Beta&gt;", html_content)

            self.assertEqual(self.win.save_report_pad_dialog(txt_path), txt_path)
            self.assertIn("Quality Summary <Alpha & Beta>", txt_path.read_text(encoding="utf-8"))

        job = self.win.print_report_pad(show_dialog=False)
        self.assertEqual(job.title, "ReportPad")
        self.assertIn("Quality Summary &lt;Alpha &amp; Beta&gt;", job.documents[0])

    def test_03_save_all_and_close_all_worksheets(self):
        self.win.presenter.worksheet.columns = [Column("A", "number", [10.0, 20.0])]
        self.win.presenter.add_worksheet("SecondSheet")
        self.win.presenter.worksheet.columns = [Column("B", "number", [30.0, 40.0])]
        self.win.refresh()

        with tempfile.TemporaryDirectory() as tmp:
            xlsx_out = Path(tmp) / "all_sheets.xlsx"
            mpx_out = Path(tmp) / "all_sheets.mpx"
            self.assertEqual(self.win.save_all_worksheets_dialog(xlsx_out), xlsx_out)
            self.assertTrue(xlsx_out.is_file() and xlsx_out.stat().st_size > 0)

            self.assertEqual(self.win.save_all_worksheets_dialog(mpx_out), mpx_out)
            self.assertTrue(mpx_out.is_file() and mpx_out.stat().st_size > 0)

        self.assertTrue(self.win.close_all_worksheets(confirm=True))
        self.assertEqual(len(self.win.presenter.worksheets), 1)
        self.assertEqual(self.win.presenter.worksheet.name, "Untitled")
        self.assertFalse(self.win.presenter.dirty)

    def test_04_order_columns_constants_matrices_by_id_and_name(self):
        self.win.presenter.worksheet = Worksheet(
            "OrderTest",
            columns=[
                Column("Zebra", "number", [1.0]),
                Column("C10", "number", [10.0]),
                Column("C2", "number", [2.0]),
                Column("Alpha", "number", [0.5]),
            ],
            constants=[
                Column("Beta", "number", [2.0], {"mpx_id": "K1"}),
                Column("Alpha", "number", [1.0], {"mpx_id": "K10"}),
            ],
            matrices=[
                Matrix("Zeta", 1, 1, [9.0], {"mpx_id": "M1"}),
                Matrix("Alpha", 1, 1, [3.0], {"mpx_id": "M10"}),
            ],
        )
        self.win.refresh()

        self.assertEqual(self.win.order_columns_by_name(), ["Alpha", "C2", "C10", "Zebra"])
        self.assertEqual([c.values[0] for c in self.win.presenter.worksheet.columns], [0.5, 2.0, 10.0, 1.0])
        self.assertEqual(self.win.order_columns_by_id(), ["Zebra", "C10", "C2", "Alpha"])
        self.assertEqual([c.values[0] for c in self.win.presenter.worksheet.columns], [1.0, 10.0, 2.0, 0.5])

        self.assertEqual(self.win.order_constants_by_name(), ["Alpha", "Beta"])
        self.assertEqual(self.win.order_constants_by_id(), ["Beta", "Alpha"])

        self.assertEqual(self.win.order_matrices_by_name(), ["Alpha", "Zeta"])
        self.assertEqual(self.win.order_matrices_by_id(), ["Zeta", "Alpha"])

    def test_05_print_session_history_and_export_settings(self):
        self.win._cmd_history = ["MEAN C1", "STDEV C1"]
        self.win.presenter.history.append({"title": "Descriptive Statistics", "text": "N=5, Mean=3.0"})
        s_job = self.win.print_session_window(show_dialog=False)
        h_job = self.win.print_history(show_dialog=False)
        self.assertEqual(s_job.title, "Session Window")
        self.assertIn("Descriptive Statistics", s_job.documents[0])
        self.assertEqual(h_job.title, "Command History")
        self.assertIn("MEAN C1", h_job.documents[0])

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "settings.json"
            self.assertEqual(self.win.export_dialog_settings_dialog(cfg), cfg)
            payload = json.loads(cfg.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "statcraft.dialog_settings")
            self.assertIn("ui_preferences", payload)

    def test_06_create_indicator_from_brushed_rows(self):
        self.win.presenter.worksheet = Worksheet("Data", [Column("Val", "number", [10.0, 20.0, 30.0, 40.0])])
        self.win.refresh()
        self.win.create_indicator_from_brushed_dialog(rows=[2, 4], name="OutlierFlag")
        names = [c.name for c in self.win.presenter.worksheet.columns]
        self.assertIn("OutlierFlag", names)
        ind_col = self.win.presenter.worksheet.columns[names.index("OutlierFlag")]
        self.assertEqual(ind_col.values, [0, 1, 0, 1])

    def test_07_crosshair_annotations_duplicate_and_3d_reset(self):
        entry = self._make_graph_entry()
        frame = self.win._active_graph_frame
        self.assertIsNotNone(frame)

        # Crosshair toggle + paint exercise
        self.assertTrue(self.win.toggle_graph_crosshair(True))
        self.assertTrue(self.win.graph_crosshair_action.isChecked())
        self.assertTrue(frame.chart._crosshair_enabled)
        frame.resize(640, 420)
        self.app.processEvents()
        frame.chart._crosshair_pos = QPointF(200.0, 180.0)
        self.assertGreater(frame.capture().width(), 0)
        self.assertFalse(self.win.toggle_graph_crosshair(False))
        self.assertFalse(frame.chart._crosshair_enabled)

        # Text annotation + duplicate
        self.assertTrue(self.win.insert_graph_text_annotation_dialog("Shift A", x=0.40, y=0.80))
        self.assertEqual(len(entry["graph_text_annotations"]), 1)
        self.assertEqual(entry["graph_text_annotations"][0]["text"], "Shift A")
        self.assertGreater(self.win._active_graph_frame.capture().width(), 0)

        self.assertTrue(self.win.duplicate_graph_annotation())
        self.assertEqual(len(entry["graph_text_annotations"]), 2)
        self.assertAlmostEqual(entry["graph_text_annotations"][1]["x"], 0.45, places=6)

        # Reference line fallback duplication
        entry.pop("graph_text_annotations", None)
        from statcraft import graph_ergonomics
        graph_ergonomics.add_reference_line(entry, "y", 3.5, "Target")
        self.assertTrue(self.win.duplicate_graph_annotation())
        self.assertEqual(len(entry["reference_lines"]), 2)
        self.assertIn("Copy", entry["reference_lines"][1]["label"])

        # 3D view reset
        frame = self.win._active_graph_frame
        frame.chart.view_state = {"azimuth": 55.0, "elevation": 62.0, "zoom": 1.9, "pan_x": 0.2, "pan_y": -0.1}
        self.assertTrue(self.win.reset_graph_3d_view_defaults())
        self.assertEqual(frame.chart.view_state, DEFAULT_VIEW)

    def test_08_exclusive_name_and_cell_selection_and_splitter_range(self):
        self.win.show()
        self.app.processEvents()

        # Selecting column name cell (0, 0) must clear table selection and hide fill handle
        self.win.column_names.setCurrentCell(0, 0)
        self.app.processEvents()
        self.assertTrue(self.win._name_row_active)
        self.assertEqual(len(self.win.column_names.selectedRanges()), 1)
        self.assertEqual(self.win.table.selectedRanges(), [])
        self.assertTrue(self.win.table.fill_handle_rect().isNull())

        # Clicking/activating data cell (0, 0) must clear column_names selection and show only table selection
        self.win._on_table_cell_interacted(0, 0)
        self.app.processEvents()
        self.assertFalse(self.win._name_row_active)
        self.assertEqual(self.win.column_names.selectedRanges(), [])
        self.assertEqual(len(self.win.table.selectedRanges()), 1)
        self.assertFalse(self.win.table.fill_handle_rect().isNull())

        # Real mouse clicks on column_names vs table must also keep selection exclusive
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt

        cn_rect = self.win.column_names.visualRect(self.win.column_names.model().index(0, 1))
        QTest.mouseClick(self.win.column_names.viewport(), Qt.MouseButton.LeftButton, pos=cn_rect.center())
        self.app.processEvents()
        self.assertTrue(self.win._name_row_active)
        self.assertEqual(len(self.win.column_names.selectedRanges()), 1)
        self.assertEqual(self.win.table.selectedRanges(), [])

        t_rect = self.win.table.visualRect(self.win.table.model().index(0, 0))
        QTest.mouseClick(self.win.table.viewport(), Qt.MouseButton.LeftButton, pos=t_rect.center())
        self.app.processEvents()
        self.assertFalse(self.win._name_row_active)
        self.assertEqual(self.win.column_names.selectedRanges(), [])
        self.assertEqual(len(self.win.table.selectedRanges()), 1)

        # Vertical splitter must allow dragging top output/welcome pane up to <= 80px
        tot = sum(self.win.work_splitter.sizes())
        self.win.work_splitter.setSizes([80, max(580, tot - 80)])
        self.app.processEvents()
        top_h, bottom_h = self.win.work_splitter.sizes()
        self.assertLessEqual(top_h, 80)
        self.assertGreaterEqual(bottom_h, 550)


if __name__ == "__main__":
    unittest.main()
