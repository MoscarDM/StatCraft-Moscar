import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape
from zipfile import ZipFile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from statcraft import settings_scope
from statcraft.app import Presenter
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.xlsx_import import inspect_xlsx, load_xlsx, load_xlsx_with_options
from statcraft.xlsx_import_dialog import ExcelImportPreviewDialog

_APP = QApplication.instance() or QApplication([])


def _col_letter(idx: int) -> str:
    out = []
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out.append(chr(ord("A") + rem))
    return "".join(reversed(out))


def _write_raw_xlsx(path: Path, sheets_rows: list[tuple[str, list[list[object]]]], date_cells=None):
    """Build a standard OOXML .xlsx workbook with explicit cells (including title/blank rows)."""
    date_cells = set(date_cells or ())
    shared: list[str] = []
    shared_index: dict[str, int] = {}

    def intern(text: str) -> int:
        if text not in shared_index:
            shared_index[text] = len(shared)
            shared.append(text)
        return shared_index[text]

    with ZipFile(path, "w") as z:
        sheet_tags = []
        rel_tags = []
        for s_idx, (name, rows) in enumerate(sheets_rows, start=1):
            sheet_tags.append(
                f'<sheet name="{escape(name)}" sheetId="{s_idx}" r:id="rId{s_idx}"/>'
            )
            rel_tags.append(
                f'<Relationship Id="rId{s_idx}" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{s_idx}.xml"/>'
            )
            row_xml = []
            for r_idx, row_vals in enumerate(rows, start=1):
                c_xml = []
                for c_idx, val in enumerate(row_vals):
                    if val is None:
                        continue
                    ref = f"{_col_letter(c_idx)}{r_idx}"
                    if (name, r_idx, c_idx) in date_cells and isinstance(val, (int, float)):
                        c_xml.append(f'<c r="{ref}" s="1"><v>{val}</v></c>')
                    elif isinstance(val, str):
                        idx = intern(val)
                        c_xml.append(f'<c r="{ref}" t="s"><v>{idx}</v></c>')
                    else:
                        c_xml.append(f'<c r="{ref}"><v>{val}</v></c>')
                if c_xml:
                    row_xml.append(f'<row r="{r_idx}">{"".join(c_xml)}</row>')
            z.writestr(
                f"xl/worksheets/sheet{s_idx}.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>',
            )

        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-officedocument.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '</Types>',
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        )
        z.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(sheet_tags)}</sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{"".join(rel_tags)}</Relationships>',
        )
        si_xml = "".join(f"<si><t>{escape(s)}</t></si>" for s in shared)
        z.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{si_xml}</sst>',
        )
        z.writestr(
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs>'
            '</styleSheet>',
        )


def _paper_airplane_workbook(path: Path) -> Path:
    setup_rows = [
        ["Paper Airplane Experiment Setup"],
        ["Drop from 2m height and record flight distance."],
    ]
    crabtree_rows = [
        ["Paper Airplane Trial - Crabtree"],
        ["Instructions: skip title rows and start at row 3"],
        ["Plane ID", "Angle", "Distance", "OperatorNotes"],
        [1, 15.0, 12.4, "calm"],
        [2, 30.0, 18.2, "wind"],
        [3, 45.0, 14.9, "turn"],
    ]
    clyde_rows = [
        ["Paper Airplane Trial - Clyde"],
        ["Instructions: separate team workbook tab"],
        ["Plane ID", "Angle", "Distance", "OperatorNotes"],
        [101, 15.0, 13.1, "dry"],
        [102, 30.0, 19.5, "ok"],
        [103, 45.0, 15.0, "drift"],
    ]
    ref_rows = [
        ["Reference Constants", "Value"],
        ["Wing span target", 21.0],
    ]
    _write_raw_xlsx(
        path,
        [
            ("Setup", setup_rows),
            ("Crabtree", crabtree_rows),
            ("Clyde", clyde_rows),
            ("Reference", ref_rows),
        ],
    )
    return path


class XlsxImportPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _APP

    def _make_window(self, settings_dir: Path):
        self._sandbox_patch = patch.object(settings_scope, "_sandbox_workspace", settings_dir)
        self._recent_patch = patch.object(ModernWindow, "_add_recent_file", lambda *a, **k: None)
        self._sandbox_patch.start()
        self._recent_patch.start()
        return ModernWindow()

    def _cleanup_window(self, win: ModernWindow):
        try:
            win.close()
            win.deleteLater()
            self.app.processEvents()
        finally:
            self._recent_patch.stop()
            self._sandbox_patch.stop()

    def test_paper_airplane_multisheet_preview_and_open_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wb_path = _paper_airplane_workbook(tmp_path / "paper_airplane.xlsx")

            # Existing single-sheet load_xlsx remains intact
            raw_sheets = load_xlsx(wb_path)
            self.assertEqual([s.name for s in raw_sheets], ["Setup", "Crabtree", "Clyde", "Reference"])

            info = inspect_xlsx(wb_path)
            self.assertEqual([s["name"] for s in info["sheets"]], ["Setup", "Crabtree", "Clyde", "Reference"])

            win = self._make_window(tmp_path)
            try:
                dlg = ExcelImportPreviewDialog(info, win)
                self.addCleanup(dlg.deleteLater)
                self.assertEqual(dlg.tabs.count(), 4)

                # Skip Setup and Reference; configure Crabtree & Clyde from row 3 with headers,
                # Plane ID as Text, Angle/Distance numeric, and exclude OperatorNotes (col 3).
                dlg.tab_by_name("Setup").import_checkbox.setChecked(False)
                dlg.tab_by_name("Reference").import_checkbox.setChecked(False)

                for name in ("Crabtree", "Clyde"):
                    tab = dlg.tab_by_name(name)
                    tab.import_checkbox.setChecked(True)
                    tab.start_row_spin.setValue(3)
                    tab.has_header_checkbox.setChecked(True)
                    tab.set_column_type(0, "text")
                    tab.set_column_included(3, False)
                    self.app.processEvents()

                    # Preview reflects source rows 4..6, Excel letters, types, and excludes OperatorNotes
                    self.assertEqual(tab.preview_table.columnCount(), 3)
                    self.assertEqual(tab.preview_table.rowCount(), 3)
                    self.assertEqual(tab.preview_table.verticalHeaderItem(0).text(), "Row 4")
                    hdr0 = tab.preview_table.horizontalHeaderItem(0).text()
                    self.assertIn("Plane ID", hdr0)
                    self.assertIn("Excel A", hdr0)
                    self.assertIn("Text", hdr0)

                crab_tab = dlg.tab_by_name("Crabtree")
                self.assertEqual([crab_tab.preview_table.item(r, 0).text() for r in range(3)], ["1", "2", "3"])

                dlg.validate_and_accept()
                self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
                self.assertEqual([w.name for w in dlg.imported_worksheets], ["Crabtree", "Clyde"])

                crab_ws, clyde_ws = dlg.imported_worksheets
                self.assertEqual([c.name for c in crab_ws.columns], ["Plane ID", "Angle", "Distance"])
                self.assertEqual(crab_ws.columns[0].kind, "text")
                self.assertEqual(crab_ws.columns[0].values, ["1", "2", "3"])
                self.assertEqual(crab_ws.columns[1].kind, "number")
                self.assertEqual(crab_ws.columns[1].values, [15.0, 30.0, 45.0])
                self.assertEqual(clyde_ws.columns[0].values, ["101", "102", "103"])

                # Wire through ModernWindow.open_document and verify MPX roundtrip
                with (
                    patch("statcraft.modern_app.QFileDialog.getOpenFileName", return_value=(str(wb_path), "Excel Workbooks (*.xlsx)")),
                    patch("statcraft.xlsx_import_dialog.ExcelImportPreviewDialog.exec", lambda d: (d.imported_worksheets.extend(dlg.imported_worksheets) or QDialog.DialogCode.Accepted)),
                ):
                    win.open_document(typed=False)

                self.assertIsNotNone(win.presenter.native_project)
                self.assertEqual([w.name for w in win.presenter.native_project.worksheets], ["Crabtree", "Clyde"])
                self.assertEqual(win.presenter.worksheet.columns[0].values, ["1", "2", "3"])

                mpx_path = tmp_path / "imported_airplanes.mpx"
                win.presenter.save(mpx_path)
                reopened = Presenter()
                reopened.load(mpx_path)
                self.assertEqual([w.name for w in reopened.native_project.worksheets], ["Crabtree", "Clyde"])
                self.assertEqual(reopened.native_project.worksheets[0].columns[0].values, ["1", "2", "3"])
                self.assertEqual(reopened.native_project.worksheets[1].columns[2].values, [13.1, 19.5, 15.0])
            finally:
                self._cleanup_window(win)

    def test_differing_per_sheet_options_and_headerless_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            wb_path = Path(tmp) / "mixed_sheets.xlsx"
            _write_raw_xlsx(
                wb_path,
                [
                    ("Titled", [
                        ["Banner Row"],
                        ["Batch", "SkipMe", "Yield"],
                        [10, "ignored", 92.5],
                        [11, "ignored", 94.0],
                    ]),
                    ("Headerless", [
                        ["L1", 46156, 1.5],
                        ["L2", 46157, 2.5],
                    ]),
                ],
                date_cells={("Headerless", 1, 1), ("Headerless", 2, 1)},
            )
            info = inspect_xlsx(wb_path)
            dlg = ExcelImportPreviewDialog(info)
            self.addCleanup(dlg.deleteLater)

            t1 = dlg.tab_by_name("Titled")
            t1.start_row_spin.setValue(2)
            t1.has_header_checkbox.setChecked(True)
            t1.set_column_included(1, False)
            t1.set_column_type(0, "text")

            t2 = dlg.tab_by_name("Headerless")
            t2.start_row_spin.setValue(1)
            t2.has_header_checkbox.setChecked(False)
            self.app.processEvents()

            self.assertEqual(t2.preview_table.horizontalHeaderItem(0).text().splitlines()[0], "C1")
            self.assertEqual(t2.preview_table.item(0, 1).text(), "2026-05-14")

            dlg.validate_and_accept()
            self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
            ws1, ws2 = dlg.imported_worksheets
            self.assertEqual([c.name for c in ws1.columns], ["Batch", "Yield"])
            self.assertEqual(ws1.columns[0].kind, "text")
            self.assertEqual(ws1.columns[0].values, ["10", "11"])
            self.assertEqual([c.name for c in ws2.columns], ["C1", "C2", "C3"])
            self.assertEqual([c.kind for c in ws2.columns], ["text", "date", "number"])
            self.assertEqual(ws2.columns[2].values, [1.5, 2.5])

            # Programmatic loader helper matches dialog output cleanly
            via_api = load_xlsx_with_options(wb_path, dlg.selected_options)
            self.assertEqual(via_api[0].columns[1].values, [92.5, 94.0])
            self.assertEqual(via_api[1].columns[0].values, ["L1", "L2"])

    def test_validation_errors_inline_and_cancel_leaves_project_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wb_path = _paper_airplane_workbook(tmp_path / "validate.xlsx")
            info = inspect_xlsx(wb_path)

            dlg = ExcelImportPreviewDialog(info)
            self.addCleanup(dlg.deleteLater)

            # 1) Empty import (no sheets selected)
            for tab in dlg.sheet_tabs:
                tab.import_checkbox.setChecked(False)
            dlg.validate_and_accept()
            self.assertNotEqual(dlg.result(), QDialog.DialogCode.Accepted)
            self.assertTrue(dlg.error_label.isVisibleTo(dlg) or bool(dlg.error_label.text()))
            self.assertIn("Select at least one worksheet", dlg.error_label.text())

            # 2) Invalid starting row (> max_row)
            crab = dlg.tab_by_name("Crabtree")
            crab.import_checkbox.setChecked(True)
            crab.start_row_spin.setValue(99)
            dlg.validate_and_accept()
            self.assertNotEqual(dlg.result(), QDialog.DialogCode.Accepted)
            self.assertIn("outside 'Crabtree'", dlg.error_label.text())

            # 3) Conversion failure when overriding text values to Numeric
            crab.start_row_spin.setValue(3)
            crab.has_header_checkbox.setChecked(True)
            crab.set_column_type(3, "number")
            self.app.processEvents()
            self.assertIn("Conversion warning", crab.status_label.text())
            dlg.validate_and_accept()
            self.assertNotEqual(dlg.result(), QDialog.DialogCode.Accepted)
            self.assertIn("column D", dlg.error_label.text())
            self.assertIn("row 4", dlg.error_label.text().lower())

            # 4) Cancel in open_document preserves active worksheet/project untouched
            win = self._make_window(tmp_path)
            try:
                win.presenter.worksheet = Worksheet("KeepMe", [Column("Existing", "number", [10.0, 20.0])])
                win.refresh()
                with (
                    patch("statcraft.modern_app.QFileDialog.getOpenFileName", return_value=(str(wb_path), "Excel Workbooks (*.xlsx)")),
                    patch("statcraft.xlsx_import_dialog.ExcelImportPreviewDialog.exec", return_value=QDialog.DialogCode.Rejected),
                ):
                    win.open_document(typed=False)
                self.assertEqual(win.presenter.worksheet.name, "KeepMe")
                self.assertEqual(win.presenter.worksheet.columns[0].values, [10.0, 20.0])
                self.assertIsNone(win.presenter.native_project)
            finally:
                self._cleanup_window(win)


if __name__ == "__main__":
    unittest.main()
