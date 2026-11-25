"""Multi-sheet Excel (.xlsx) import options and live preview dialog."""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .connect_hub import FlowLayout
from .dialog_theme import (
    AutoErrorLabel,
    clamp_dialog_to_screen,
    dialog_stylesheet,
    ensure_dialog_fits_screen,
    is_dark_active,
)
from .io import FormatError
from .xlsx_import import (
    _KIND_LABELS,
    _coerce_cell,
    _normalize_kind,
    build_worksheet_from_sheet_info,
    format_preview_cell,
    infer_sheet_columns,
)

_TYPE_CHOICES = [
    ("Auto (Inferred)", None),
    ("Numeric", "number"),
    ("Text", "text"),
    ("Date/Time", "date"),
]

_MAX_PREVIEW_ROWS = 80


class SheetImportTab(QWidget):
    """Per-sheet Excel import configuration and live resolved preview."""

    def __init__(self, sheet_info: dict, parent=None, on_change=None):
        super().__init__(parent)
        self.sheet_info = sheet_info
        self._on_change = on_change
        self._updating = False
        self._included_state: Dict[int, bool] = {}
        self._type_overrides: Dict[int, Optional[str]] = {}
        self._col_checkboxes: Dict[int, QCheckBox] = {}
        self._col_type_combos: Dict[int, QComboBox] = {}

        max_row = int(sheet_info.get("max_row", 0))
        max_col = int(sheet_info.get("max_col", 0))
        for c_idx in range(max_col):
            self._included_state[c_idx] = True
            self._type_overrides[c_idx] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        controls = FlowLayout(margin=0, h_spacing=10, v_spacing=4)

        self.import_checkbox = QCheckBox("Import this sheet")
        self.import_checkbox.setChecked(max_row > 0 and max_col > 0)
        self.import_checkbox.toggled.connect(self._handle_import_toggled)
        controls.addWidget(self.import_checkbox)

        row_box = QWidget(self)
        row_box_layout = QHBoxLayout(row_box)
        row_box_layout.setContentsMargins(0, 0, 0, 0)
        row_box_layout.setSpacing(6)
        row_box_layout.addWidget(QLabel("First row to read:"))
        self.start_row_spin = QSpinBox()
        self.start_row_spin.setRange(1, max(999999, max_row + 100))
        self.start_row_spin.setMaximumWidth(84)
        self.start_row_spin.setValue(1)
        self.start_row_spin.setToolTip(
            f"1-based Excel row number where header or data starts (sheet has {max_row} row(s))."
        )
        self.start_row_spin.valueChanged.connect(self._handle_options_changed)
        row_box_layout.addWidget(self.start_row_spin)
        controls.addWidget(row_box)

        self.has_header_checkbox = QCheckBox("First row contains column names")
        self.has_header_checkbox.setChecked(True)
        self.has_header_checkbox.toggled.connect(self._handle_options_changed)
        controls.addWidget(self.has_header_checkbox)
        layout.addLayout(controls)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_label = QLabel()
        self.status_label.setObjectName("secondary")
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status_row.addWidget(self.status_label, 1)

        self.sheet_summary_label = QLabel()
        self.sheet_summary_label.setObjectName("secondary")
        status_row.addWidget(self.sheet_summary_label)
        layout.addLayout(status_row)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setChildrenCollapsible(False)

        # Top pane: Column inclusion and type selection
        cols_box = QFrame(splitter)
        cols_layout = QVBoxLayout(cols_box)
        cols_layout.setContentsMargins(0, 0, 0, 0)
        cols_layout.setSpacing(3)
        cols_title = QLabel("Columns & Data Types")
        cols_title.setStyleSheet("font-weight: 600;")
        cols_layout.addWidget(cols_title)

        self.columns_table = QTableWidget(0, 5, cols_box)
        self.columns_table.setHorizontalHeaderLabels(
            ["Import", "Excel Col", "Imported Name", "Data Type", "Inferred"]
        )
        self.columns_table.verticalHeader().setVisible(False)
        self.columns_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.columns_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.columns_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.columns_table.setMinimumHeight(72)
        self.columns_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        cols_layout.addWidget(self.columns_table)

        # Bottom pane: Live preview of resolved values and source rows
        prev_box = QFrame(splitter)
        prev_layout = QVBoxLayout(prev_box)
        prev_layout.setContentsMargins(0, 2, 0, 0)
        prev_layout.setSpacing(3)
        prev_title = QLabel("Preview (Excel source rows, column letters, and resolved StatCraft values)")
        prev_title.setStyleSheet("font-weight: 600;")
        prev_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        prev_layout.addWidget(prev_title)

        self.preview_table = QTableWidget(0, 0, prev_box)
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.horizontalHeader().setDefaultSectionSize(125)
        self.preview_table.horizontalHeader().setMinimumHeight(32)
        self.preview_table.setMinimumHeight(88)
        self.preview_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        prev_layout.addWidget(self.preview_table)

        splitter.setSizes([110, 165])
        layout.addWidget(splitter, 1)

        self._refresh_tables()
        self._sync_enabled_state()

    def _sync_enabled_state(self):
        enabled = self.import_checkbox.isChecked()
        for w in (
            self.start_row_spin,
            self.has_header_checkbox,
            self.columns_table,
            self.preview_table,
        ):
            w.setEnabled(enabled)

    def _handle_import_toggled(self, _checked: bool):
        self._sync_enabled_state()
        self._refresh_status_only()
        if self._on_change is not None:
            self._on_change()

    def _handle_options_changed(self):
        if self._updating:
            return
        self._refresh_tables()
        if self._on_change is not None:
            self._on_change()

    def _on_column_include_toggled(self, c_idx: int, checked: bool):
        self._included_state[c_idx] = bool(checked)
        if not self._updating:
            self._refresh_preview()
            if self._on_change is not None:
                self._on_change()

    def _on_column_type_changed(self, c_idx: int, combo: QComboBox):
        self._type_overrides[c_idx] = combo.currentData()
        if not self._updating:
            self._refresh_preview()
            if self._on_change is not None:
                self._on_change()

    def set_column_included(self, c_idx: int, included: bool):
        cb = self._col_checkboxes.get(c_idx)
        if cb is not None:
            cb.setChecked(bool(included))
        else:
            self._included_state[c_idx] = bool(included)
            self._refresh_preview()

    def set_column_type(self, c_idx: int, kind: Optional[str]):
        normalized = _normalize_kind(kind)
        combo = self._col_type_combos.get(c_idx)
        if combo is not None:
            idx = combo.findData(normalized)
            if idx >= 0:
                combo.setCurrentIndex(idx)
                return
        self._type_overrides[c_idx] = normalized
        self._refresh_preview()

    def current_options(self) -> dict:
        max_col = int(self.sheet_info.get("max_col", 0))
        included = [i for i in range(max_col) if self._included_state.get(i, True)]
        return {
            "name": self.sheet_info["name"],
            "sheet_index": self.sheet_info["sheet_index"],
            "import_sheet": bool(self.import_checkbox.isChecked()),
            "start_row": int(self.start_row_spin.value()),
            "has_header": bool(self.has_header_checkbox.isChecked()),
            "included_columns": included,
            "column_types": {
                i: self._type_overrides.get(i)
                for i in included
                if self._type_overrides.get(i) is not None
            },
        }

    def _refresh_status_only(self):
        max_row = int(self.sheet_info.get("max_row", 0))
        max_col = int(self.sheet_info.get("max_col", 0))
        self.sheet_summary_label.setText(f"Source size: {max_row} row(s) × {max_col} column(s)")
        if not self.import_checkbox.isChecked():
            self.status_label.setText("This sheet is skipped and will not be imported.")

    def _refresh_tables(self):
        self._updating = True
        try:
            self._refresh_status_only()
            self._col_checkboxes.clear()
            self._col_type_combos.clear()
            max_row = int(self.sheet_info.get("max_row", 0))
            max_col = int(self.sheet_info.get("max_col", 0))
            start_row = int(self.start_row_spin.value())
            has_header = bool(self.has_header_checkbox.isChecked())

            try:
                descriptors = infer_sheet_columns(
                    self.sheet_info, start_row=start_row, has_header=has_header
                )
            except FormatError as exc:
                self.columns_table.setRowCount(0)
                self.preview_table.setRowCount(0)
                self.preview_table.setColumnCount(0)
                if self.import_checkbox.isChecked():
                    self.status_label.setText(str(exc))
                return

            self.columns_table.setRowCount(len(descriptors))
            for row_i, desc in enumerate(descriptors):
                c_idx = desc["col_index"]
                cb = QCheckBox()
                cb.setChecked(self._included_state.get(c_idx, True))
                cb.toggled.connect(lambda ch, idx=c_idx: self._on_column_include_toggled(idx, ch))
                self._col_checkboxes[c_idx] = cb
                wrap = QWidget()
                wl = QHBoxLayout(wrap)
                wl.setContentsMargins(4, 0, 4, 0)
                wl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                wl.addWidget(cb)
                self.columns_table.setCellWidget(row_i, 0, wrap)

                letter_item = QTableWidgetItem(desc["letter"])
                letter_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.columns_table.setItem(row_i, 1, letter_item)

                name_item = QTableWidgetItem(desc["name"])
                self.columns_table.setItem(row_i, 2, name_item)

                combo = QComboBox()
                for label, val in _TYPE_CHOICES:
                    combo.addItem(label, val)
                saved_type = self._type_overrides.get(c_idx)
                pos = combo.findData(saved_type)
                combo.setCurrentIndex(pos if pos >= 0 else 0)
                combo.currentIndexChanged.connect(
                    lambda _idx, idx=c_idx, box=combo: self._on_column_type_changed(idx, box)
                )
                self._col_type_combos[c_idx] = combo
                self.columns_table.setCellWidget(row_i, 3, combo)

                inf_label = _KIND_LABELS.get(desc["inferred_kind"], desc["inferred_kind"])
                inf_item = QTableWidgetItem(inf_label)
                inf_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.columns_table.setItem(row_i, 4, inf_item)
                self.columns_table.setRowHeight(row_i, 24)

            if max_row <= 0 or max_col <= 0:
                self.preview_table.setRowCount(0)
                self.preview_table.setColumnCount(0)
                self.status_label.setText("Source sheet is empty.")
                return
        finally:
            self._updating = False

        self._refresh_preview()

    def _refresh_preview(self):
        self._refresh_status_only()
        max_row = int(self.sheet_info.get("max_row", 0))
        max_col = int(self.sheet_info.get("max_col", 0))
        if max_row <= 0 or max_col <= 0:
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            return

        start_row = int(self.start_row_spin.value())
        has_header = bool(self.has_header_checkbox.isChecked())
        try:
            descriptors = infer_sheet_columns(
                self.sheet_info, start_row=start_row, has_header=has_header
            )
        except FormatError as exc:
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            if self.import_checkbox.isChecked():
                self.status_label.setText(str(exc))
            return

        included_descs = [d for d in descriptors if self._included_state.get(d["col_index"], True)]
        if not included_descs:
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            if self.import_checkbox.isChecked():
                self.status_label.setText("Select at least one column to import.")
            return

        # Keep column header table's Resolved Name aligned with sequential C1..Ck when header is blank
        for out_i, desc in enumerate(included_descs):
            resolved_name = desc["raw_header"] or f"C{out_i + 1}"
            name_item = self.columns_table.item(desc["col_index"], 2)
            if name_item is not None:
                name_item.setText(resolved_name)

        data_start_idx = start_row if has_header else start_row - 1
        preview_end_idx = min(max_row, data_start_idx + _MAX_PREVIEW_ROWS)
        n_prev_rows = max(0, preview_end_idx - data_start_idx)

        self.preview_table.setColumnCount(len(included_descs))
        col_headers = []
        target_kinds: List[str] = []
        for out_i, desc in enumerate(included_descs):
            c_idx = desc["col_index"]
            resolved_name = desc["raw_header"] or f"C{out_i + 1}"
            kind = self._type_overrides.get(c_idx) or desc["inferred_kind"]
            target_kinds.append(kind)
            kind_label = _KIND_LABELS.get(kind, kind)
            col_headers.append(f"{resolved_name}\nExcel {desc['letter']} • {kind_label}")
        self.preview_table.setHorizontalHeaderLabels(col_headers)

        self.preview_table.setRowCount(n_prev_rows)
        row_headers = [f"Row {r_idx + 1}" for r_idx in range(data_start_idx, preview_end_idx)]
        self.preview_table.setVerticalHeaderLabels(row_headers)

        grid = self.sheet_info["grid"]
        first_error: Optional[str] = None
        for r_off, r_idx in enumerate(range(data_start_idx, preview_end_idx)):
            row_cells = grid.get(r_idx, {})
            for col_off, desc in enumerate(included_descs):
                c_idx = desc["col_index"]
                kind = target_kinds[col_off]
                pair = row_cells.get(c_idx)
                try:
                    coerced = _coerce_cell(pair, kind)
                    text = format_preview_cell(coerced, kind) if pair is not None else ""
                    item = QTableWidgetItem(text)
                    if kind == "number" and coerced is not None:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                except (ValueError, TypeError, OverflowError):
                    raw_val = pair[1] if pair is not None else ""
                    item = QTableWidgetItem(f"! {raw_val}")
                    dark = is_dark_active(self)
                    item.setForeground(QBrush(QColor("#f87171" if dark else "#dc2626")))
                    item.setBackground(QBrush(QColor("#450a0a" if dark else "#fef2f2")))
                    if first_error is None:
                        kind_label = _KIND_LABELS.get(kind, kind)
                        resolved_name = desc["raw_header"] or f"C{col_off + 1}"
                        first_error = (
                            f"Row {r_idx + 1}, Excel {desc['letter']} ({resolved_name}): "
                            f"cannot convert {raw_val!r} to {kind_label}."
                        )
                self.preview_table.setItem(r_off, col_off, item)

        if self.import_checkbox.isChecked():
            if first_error:
                self.status_label.setText(f"Conversion warning: {first_error}")
            else:
                self.status_label.setText(
                    f"Ready: importing {len(included_descs)} column(s) starting at row {start_row} "
                    f"({max(0, max_row - data_start_idx)} data row(s))."
                )


class ExcelImportPreviewDialog(QDialog):
    """Tabbed multi-sheet Excel import options and preview dialog."""

    def __init__(self, workbook_info: dict, parent=None):
        super().__init__(parent)
        self.workbook_info = workbook_info
        self.imported_worksheets = []
        self.selected_options: List[dict] = []

        self.setWindowTitle("Import Excel Workbook")
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent)))
        self._did_clamp_on_show = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(5)

        title = QLabel(f"Excel Import Options & Preview — {workbook_info.get('filename', 'Workbook')}")
        title.setStyleSheet("font-size: 11pt; font-weight: 700;")
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(title)

        subtitle = QLabel(
            "Select the sheets to import, the 1-based starting row for each sheet, "
            "header usage, included columns, and column data types."
        )
        subtitle.setObjectName("secondary")
        subtitle.setWordWrap(True)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(subtitle)

        self.tabs = QTabWidget(self)
        self.sheet_tabs: List[SheetImportTab] = []
        for sheet_info in workbook_info.get("sheets", []):
            tab = SheetImportTab(sheet_info, self.tabs, on_change=self._clear_error)
            self.sheet_tabs.append(tab)
            self.tabs.addTab(tab, sheet_info["name"])
        root.addWidget(self.tabs, 1)

        self.error_label = AutoErrorLabel()
        root.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        clamp_dialog_to_screen(self, 820, 500, min_w=580, min_h=360)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._did_clamp_on_show:
            self._did_clamp_on_show = True
            ensure_dialog_fits_screen(self, margin=8)
            QTimer.singleShot(0, lambda: ensure_dialog_fits_screen(self, margin=8))

    def _clear_error(self):
        self.error_label.clear()
        self.error_label.hide()

    def tab_by_name(self, name: str) -> SheetImportTab:
        for tab in self.sheet_tabs:
            if tab.sheet_info["name"] == name:
                return tab
        raise KeyError(f"Unknown worksheet tab: {name}")

    def validate_and_accept(self):
        self._clear_error()
        selected = [tab for tab in self.sheet_tabs if tab.import_checkbox.isChecked()]
        if not selected:
            self.error_label.setText("Select at least one worksheet to import.")
            self.error_label.show()
            return

        worksheets = []
        options = []
        for tab in self.sheet_tabs:
            opts = tab.current_options()
            options.append(opts)
            if not opts["import_sheet"]:
                continue
            try:
                ws = build_worksheet_from_sheet_info(
                    tab.sheet_info,
                    start_row=opts["start_row"],
                    has_header=opts["has_header"],
                    included_columns=opts["included_columns"],
                    column_types=opts["column_types"],
                    strict=True,
                )
            except FormatError as exc:
                self.tabs.setCurrentWidget(tab)
                self.error_label.setText(str(exc))
                self.error_label.show()
                return
            worksheets.append(ws)

        self.selected_options = options
        self.imported_worksheets = worksheets
        self.accept()
