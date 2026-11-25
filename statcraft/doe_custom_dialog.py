"""Define Custom Factorial Design dialogs (main, Low/High, and Designs)."""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .dialog_theme import AutoErrorLabel, dialog_stylesheet, is_dark_active
from .doe_custom import define_custom_factorial
from .model import finite_number
from .variable_dialogs import format_variable_list, resolve_variables


class DefineCustomLowHighDialog(QDialog):
    """Low/High endpoint editor for selected 2-level numeric or text factors."""

    def __init__(
        self,
        parent,
        worksheet,
        factor_indices: List[int],
        existing_low_high: Optional[Dict[int, tuple]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Define Custom Factorial Design: Low/High")
        self.setMinimumWidth(520)
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent)))
        self.worksheet = worksheet
        self.factor_indices = list(factor_indices)
        self.low_high: Dict[int, tuple] = copy.deepcopy(existing_low_high or {})

        layout = QVBoxLayout(self)
        note = QLabel("Verify or adjust the Low and High coded endpoints for each 2-level factor.")
        note.setObjectName("secondary")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(len(self.factor_indices), 4, self)
        self.table.setHorizontalHeaderLabels(["Column", "Name", "Type", "Low / High"])
        # Use 5 columns cleanly: Column ID, Name, Type, Low, High
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Col", "Name", "Type", "Low", "High"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)

        for row, idx in enumerate(self.factor_indices):
            col = worksheet.columns[idx]
            vals = [v for v in col.values if v is not None and (col.kind != "text" or str(v).strip() != "")]
            if idx in self.low_high:
                low_v, high_v = self.low_high[idx]
            elif vals:
                ordered = sorted(set(vals), key=(lambda x: float(x)) if col.kind == "number" else (lambda x: str(x).casefold()))
                low_v = ordered[0]
                high_v = ordered[-1] if len(ordered) > 1 else ordered[0]
            else:
                low_v, high_v = "", ""

            for col_i, text in enumerate(
                (f"C{idx + 1}", col.name, "Text" if col.kind == "text" else "Numeric")
            ):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col_i, item)
            self.table.setItem(row, 3, QTableWidgetItem(str(low_v)))
            self.table.setItem(row, 4, QTableWidgetItem(str(high_v)))

        layout.addWidget(self.table, 1)
        self.error = AutoErrorLabel()
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate(self):
        self.error.hide()
        parsed: Dict[int, tuple] = {}
        try:
            for row, idx in enumerate(self.factor_indices):
                col = self.worksheet.columns[idx]
                low_txt = (self.table.item(row, 3).text() if self.table.item(row, 3) else "").strip()
                high_txt = (self.table.item(row, 4).text() if self.table.item(row, 4) else "").strip()
                if col.kind == "text":
                    if not low_txt or not high_txt or low_txt == high_txt:
                        raise ValueError(f"Text factor '{col.name}' requires distinct non-empty Low and High labels.")
                    parsed[idx] = (low_txt, high_txt)
                else:
                    low_val = finite_number(float(low_txt))
                    high_val = finite_number(float(high_txt))
                    if low_val >= high_val:
                        raise ValueError(f"Numeric factor '{col.name}' requires Low < High.")
                    parsed[idx] = (low_val, high_val)
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.low_high = parsed
        self.accept()


class DefineCustomDesignsDialog(QDialog):
    """Independent order, point type, and block column configuration for custom factorial designs."""

    def __init__(self, parent, worksheet, state: Optional[dict] = None):
        super().__init__(parent)
        self.setWindowTitle("Define Custom Factorial Design: Designs")
        self.setMinimumWidth(520)
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent)))
        self.worksheet = worksheet
        self.state = copy.deepcopy(state or {
            "std_order_mode": "row_order",
            "std_order_index": None,
            "run_order_mode": "row_order",
            "run_order_index": None,
            "point_type_mode": "unknown",
            "point_type_index": None,
            "blocks_mode": "none",
            "blocks_index": None,
        })

        layout = QVBoxLayout(self)
        note = QLabel(
            "Specify optional worksheet columns for Standard Order, Run Order, Point Type, and Blocks."
        )
        note.setObjectName("secondary")
        note.setWordWrap(True)
        layout.addWidget(note)

        numeric_cols = [(i, col) for i, col in enumerate(worksheet.columns) if col.kind == "number"]
        block_cols = [(i, col) for i, col in enumerate(worksheet.columns) if col.kind in ("number", "text")]

        def _populate_combo(combo: QComboBox, items, saved_index: Optional[int]):
            for idx, col in items:
                combo.addItem(f"C{idx + 1}   {col.name}", idx)
            if saved_index is not None:
                pos = combo.findData(saved_index)
                if pos >= 0:
                    combo.setCurrentIndex(pos)

        # Standard Order (independent)
        std_group = QGroupBox("Standard Order")
        std_layout = QVBoxLayout(std_group)
        self.std_row_radio = QRadioButton("Use worksheet row order")
        self.std_col_radio = QRadioButton("Specify column:")
        self.std_combo = QComboBox()
        _populate_combo(self.std_combo, numeric_cols, self.state.get("std_order_index"))
        std_col_row = QHBoxLayout()
        std_col_row.addWidget(self.std_col_radio)
        std_col_row.addWidget(self.std_combo, 1)
        std_layout.addWidget(self.std_row_radio)
        std_layout.addLayout(std_col_row)
        layout.addWidget(std_group)

        # Run Order (independent)
        run_group = QGroupBox("Run Order")
        run_layout = QVBoxLayout(run_group)
        self.run_row_radio = QRadioButton("Use worksheet row order")
        self.run_col_radio = QRadioButton("Specify column:")
        self.run_combo = QComboBox()
        _populate_combo(self.run_combo, numeric_cols, self.state.get("run_order_index"))
        run_col_row = QHBoxLayout()
        run_col_row.addWidget(self.run_col_radio)
        run_col_row.addWidget(self.run_combo, 1)
        run_layout.addWidget(self.run_row_radio)
        run_layout.addLayout(run_col_row)
        layout.addWidget(run_group)

        # Point Type
        pt_group = QGroupBox("Point Type")
        pt_layout = QVBoxLayout(pt_group)
        self.pt_unknown_radio = QRadioButton("Unknown")
        self.pt_col_radio = QRadioButton("Specify column:")
        self.pt_combo = QComboBox()
        _populate_combo(self.pt_combo, numeric_cols, self.state.get("point_type_index"))
        pt_col_row = QHBoxLayout()
        pt_col_row.addWidget(self.pt_col_radio)
        pt_col_row.addWidget(self.pt_combo, 1)
        pt_layout.addWidget(self.pt_unknown_radio)
        pt_layout.addLayout(pt_col_row)
        layout.addWidget(pt_group)

        # Blocks
        blk_group = QGroupBox("Blocks")
        blk_layout = QVBoxLayout(blk_group)
        self.blk_none_radio = QRadioButton("No blocks")
        self.blk_col_radio = QRadioButton("Specify column:")
        self.blk_combo = QComboBox()
        _populate_combo(self.blk_combo, block_cols, self.state.get("blocks_index"))
        blk_col_row = QHBoxLayout()
        blk_col_row.addWidget(self.blk_col_radio)
        blk_col_row.addWidget(self.blk_combo, 1)
        blk_layout.addWidget(self.blk_none_radio)
        blk_layout.addLayout(blk_col_row)
        layout.addWidget(blk_group)

        # Initialize independent selections
        self.std_col_radio.setChecked(self.state.get("std_order_mode") == "column" and self.std_combo.count() > 0)
        self.std_row_radio.setChecked(not self.std_col_radio.isChecked())

        self.run_col_radio.setChecked(self.state.get("run_order_mode") == "column" and self.run_combo.count() > 0)
        self.run_row_radio.setChecked(not self.run_col_radio.isChecked())

        self.pt_col_radio.setChecked(self.state.get("point_type_mode") == "column" and self.pt_combo.count() > 0)
        self.pt_unknown_radio.setChecked(not self.pt_col_radio.isChecked())

        self.blk_col_radio.setChecked(self.state.get("blocks_mode") == "column" and self.blk_combo.count() > 0)
        self.blk_none_radio.setChecked(not self.blk_col_radio.isChecked())

        for col_radio, combo in (
            (self.std_col_radio, self.std_combo),
            (self.run_col_radio, self.run_combo),
            (self.pt_col_radio, self.pt_combo),
            (self.blk_col_radio, self.blk_combo),
        ):
            if combo.count() == 0:
                col_radio.setEnabled(False)
            col_radio.toggled.connect(lambda checked, box=combo: box.setEnabled(checked and box.count() > 0))
            combo.setEnabled(col_radio.isChecked() and combo.count() > 0)

        self.error = AutoErrorLabel()
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate(self):
        self.error.hide()
        std_idx = self.std_combo.currentData() if self.std_col_radio.isChecked() else None
        run_idx = self.run_combo.currentData() if self.run_col_radio.isChecked() else None
        pt_idx = self.pt_combo.currentData() if self.pt_col_radio.isChecked() else None
        blk_idx = self.blk_combo.currentData() if self.blk_col_radio.isChecked() else None

        chosen = [
            (label, idx)
            for label, idx in (
                ("Standard Order", std_idx),
                ("Run Order", run_idx),
                ("Point Type", pt_idx),
                ("Blocks", blk_idx),
            )
            if idx is not None
        ]
        seen = {}
        for label, idx in chosen:
            if idx in seen:
                col_name = self.worksheet.columns[idx].name
                self.error.setText(f"{label} and {seen[idx]} cannot use the same column ('{col_name}').")
                self.error.show()
                return
            seen[idx] = label

        self.state = {
            "std_order_mode": "column" if std_idx is not None else "row_order",
            "std_order_index": std_idx,
            "run_order_mode": "column" if run_idx is not None else "row_order",
            "run_order_index": run_idx,
            "point_type_mode": "column" if pt_idx is not None else "unknown",
            "point_type_index": pt_idx,
            "blocks_mode": "column" if blk_idx is not None else "none",
            "blocks_index": blk_idx,
        }
        self.accept()


class DefineCustomFactorialDialog(QDialog):
    """Attach StatCraft factorial design metadata to existing worksheet columns."""

    def __init__(self, parent, worksheet):
        super().__init__(parent)
        self.setWindowTitle("Define Custom Factorial Design")
        self.setMinimumWidth(720)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent)))
        self.worksheet = worksheet
        self.parameters = None
        self.low_high: Dict[int, tuple] = {}

        doe_meta = (worksheet.metadata or {}).get("doe", {}) if isinstance(worksheet.metadata, dict) else {}
        self.design_options = {
            "std_order_mode": doe_meta.get("std_order_mode", "row_order") if doe_meta.get("std_order_column_index") is not None else "row_order",
            "std_order_index": doe_meta.get("std_order_column_index"),
            "run_order_mode": doe_meta.get("run_order_mode", "row_order") if doe_meta.get("run_order_column_index") is not None else "row_order",
            "run_order_index": doe_meta.get("run_order_column_index"),
            "point_type_mode": doe_meta.get("point_type_mode", "unknown") if doe_meta.get("point_type_column_index") is not None else "unknown",
            "point_type_index": doe_meta.get("point_type_column_index"),
            "blocks_mode": doe_meta.get("blocks_mode", "none") if doe_meta.get("blocks_column_index") is not None else "none",
            "blocks_index": doe_meta.get("blocks_column_index"),
        }

        layout = QVBoxLayout(self)
        body = QHBoxLayout()

        # Left pane: worksheet columns showing C# IDs and names
        left = QVBoxLayout()
        left.addWidget(QLabel("Worksheet columns:"))
        self.available = QListWidget()
        self.available.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for i, column in enumerate(worksheet.columns):
            if column.kind in ("number", "text"):
                item = QListWidgetItem(f"C{i + 1}   {column.name}")
                item.setData(Qt.ItemDataRole.UserRole, i)
                self.available.addItem(item)
        left.addWidget(self.available, 1)
        self.select_btn = QPushButton("Select")
        self.select_btn.setAutoDefault(False)
        self.select_btn.clicked.connect(self.transfer_factors)
        self.available.itemDoubleClicked.connect(lambda _item: self.transfer_factors())
        left.addWidget(self.select_btn)
        body.addLayout(left, 1)

        # Right pane: Factors, Design Type, Hard-to-change picker, Low/High & Designs
        right = QVBoxLayout()
        right.addWidget(QLabel("Factors:"))
        self.factors_edit = QLineEdit()
        self.factors_edit.setPlaceholderText("e.g. C1 C2 or column names")
        self.factors_edit.textChanged.connect(self._on_factors_changed)
        right.addWidget(self.factors_edit)

        type_group = QGroupBox("Type of Design")
        type_layout = QVBoxLayout(type_group)
        self.two_level_radio = QRadioButton("2-level factorial")
        self.split_plot_radio = QRadioButton("2-level split-plot")
        self.general_radio = QRadioButton("General full factorial")
        for r in (self.two_level_radio, self.split_plot_radio, self.general_radio):
            type_layout.addWidget(r)
        existing_type = doe_meta.get("design_type")
        if existing_type == "split_plot":
            self.split_plot_radio.setChecked(True)
        elif existing_type == "general_full":
            self.general_radio.setChecked(True)
        else:
            self.two_level_radio.setChecked(True)
        right.addWidget(type_group)

        self.hard_label = QLabel("Hard-to-change factors (split-plot only):")
        right.addWidget(self.hard_label)
        self.hard_list = QListWidget()
        self.hard_list.setMaximumHeight(110)
        right.addWidget(self.hard_list)

        btn_row = QHBoxLayout()
        self.low_high_btn = QPushButton("Low/High…")
        self.low_high_btn.setAutoDefault(False)
        self.low_high_btn.clicked.connect(self.open_low_high)
        btn_row.addWidget(self.low_high_btn)

        self.designs_btn = QPushButton("Designs…")
        self.designs_btn.setAutoDefault(False)
        self.designs_btn.clicked.connect(self.open_designs)
        btn_row.addWidget(self.designs_btn)
        btn_row.addStretch(1)
        right.addLayout(btn_row)

        self.designs_summary = QLabel()
        self.designs_summary.setObjectName("secondary")
        self.designs_summary.setWordWrap(True)
        right.addWidget(self.designs_summary)
        right.addStretch(1)
        body.addLayout(right, 2)
        layout.addLayout(body, 1)

        self.error = AutoErrorLabel()
        layout.addWidget(self.error)

        footer = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        footer.accepted.connect(self.validate)
        footer.rejected.connect(self.reject)
        layout.addWidget(footer)

        # Prefill factors if existing DOE metadata present
        existing_indices = [
            f["column_index"]
            for f in doe_meta.get("factors", [])
            if isinstance(f, dict) and type(f.get("column_index")) is int
            and 0 <= f["column_index"] < len(worksheet.columns)
        ]
        if existing_indices:
            self.factors_edit.setText(format_variable_list(existing_indices, worksheet))
        hard_existing = {
            f["column_index"]
            for f in doe_meta.get("hard_factors", [])
            if isinstance(f, dict) and type(f.get("column_index")) is int
        }
        for r in (self.two_level_radio, self.split_plot_radio, self.general_radio):
            r.toggled.connect(self._sync_design_type_state)
        self._refresh_hard_list(checked_indices=hard_existing)
        self._sync_design_type_state()
        self._update_designs_summary()

    def current_design_type(self) -> str:
        if self.split_plot_radio.isChecked():
            return "split_plot"
        if self.general_radio.isChecked():
            return "general_full"
        return "two_level"

    def _parsed_factor_indices(self) -> List[int]:
        text = self.factors_edit.text().strip()
        if not text:
            return []
        try:
            indices = resolve_variables(text, self.worksheet, kinds=("number", "text"))
            seen = set()
            out = []
            for idx in indices:
                if idx not in seen:
                    seen.add(idx)
                    out.append(idx)
            return out
        except ValueError:
            return []

    def transfer_factors(self):
        selected = self.available.selectedItems()
        if not selected and self.available.currentItem() is not None:
            selected = [self.available.currentItem()]
        chosen_indices = [item.data(Qt.ItemDataRole.UserRole) for item in selected]
        if not chosen_indices:
            return
        current = self._parsed_factor_indices()
        for idx in chosen_indices:
            if idx not in current:
                current.append(idx)
        self.factors_edit.setText(format_variable_list(current, self.worksheet))

    def _on_factors_changed(self):
        self.error.hide()
        self._refresh_hard_list()

    def _refresh_hard_list(self, checked_indices=None):
        if checked_indices is None:
            checked_indices = set(self.selected_hard_indices())
        factor_indices = self._parsed_factor_indices()
        self.hard_list.clear()
        for idx in factor_indices:
            col = self.worksheet.columns[idx]
            item = QListWidgetItem(f"C{idx + 1}   {col.name}")
            item.setData(Qt.ItemDataRole.UserRole, idx)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(
                Qt.CheckState.Checked if idx in checked_indices else Qt.CheckState.Unchecked
            )
            self.hard_list.addItem(item)

    def selected_hard_indices(self) -> List[int]:
        out: List[int] = []
        for i in range(self.hard_list.count()):
            item = self.hard_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def set_hard_factors(self, col_indices: List[int]):
        target = set(col_indices)
        for i in range(self.hard_list.count()):
            item = self.hard_list.item(i)
            idx = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(Qt.CheckState.Checked if idx in target else Qt.CheckState.Unchecked)

    def _sync_design_type_state(self):
        dtype = self.current_design_type()
        is_split = dtype == "split_plot"
        self.hard_label.setEnabled(is_split)
        self.hard_list.setEnabled(is_split)
        self.low_high_btn.setEnabled(dtype in ("two_level", "split_plot"))
        self.error.hide()

    def _update_designs_summary(self):
        opts = self.design_options
        def _col_desc(idx):
            return f"C{idx + 1} ({self.worksheet.columns[idx].name})"
        std_s = _col_desc(opts["std_order_index"]) if opts["std_order_mode"] == "column" and opts["std_order_index"] is not None else "Row order"
        run_s = _col_desc(opts["run_order_index"]) if opts["run_order_mode"] == "column" and opts["run_order_index"] is not None else "Row order"
        pt_s = _col_desc(opts["point_type_index"]) if opts["point_type_mode"] == "column" and opts["point_type_index"] is not None else "Unknown"
        blk_s = _col_desc(opts["blocks_index"]) if opts["blocks_mode"] == "column" and opts["blocks_index"] is not None else "None"
        self.designs_summary.setText(
            f"Standard Order: {std_s}  |  Run Order: {run_s}  |  Point Type: {pt_s}  |  Blocks: {blk_s}"
        )

    def open_low_high(self):
        self.error.hide()
        try:
            factor_indices = resolve_variables(self.factors_edit.text(), self.worksheet, kinds=("number", "text"))
            if len(factor_indices) < 2:
                raise ValueError("Select at least 2 factors before configuring Low/High levels.")
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        dlg = DefineCustomLowHighDialog(self, self.worksheet, factor_indices, self.low_high)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.low_high = copy.deepcopy(dlg.low_high)

    def open_designs(self):
        self.error.hide()
        dlg = DefineCustomDesignsDialog(self, self.worksheet, self.design_options)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.design_options = copy.deepcopy(dlg.state)
            self._update_designs_summary()

    def validate(self):
        self.error.hide()
        try:
            factor_indices = resolve_variables(self.factors_edit.text(), self.worksheet, kinds=("number", "text"))
            dtype = self.current_design_type()
            hard_indices = self.selected_hard_indices() if dtype == "split_plot" else None
            opts = self.design_options
            params = {
                "factor_indices": factor_indices,
                "design_type": dtype,
                "hard_factor_indices": hard_indices,
                "std_order_index": opts["std_order_index"] if opts["std_order_mode"] == "column" else None,
                "run_order_index": opts["run_order_index"] if opts["run_order_mode"] == "column" else None,
                "point_type_index": opts["point_type_index"] if opts["point_type_mode"] == "column" else None,
                "blocks_index": opts["blocks_index"] if opts["blocks_mode"] == "column" else None,
                "low_high": self.low_high if dtype in ("two_level", "split_plot") and self.low_high else None,
            }
            # Validate on a shallow copy first so any invalid config never mutates worksheet
            probe = copy.copy(self.worksheet)
            probe.metadata = copy.deepcopy(self.worksheet.metadata)
            define_custom_factorial(probe, **params)
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.parameters = params
        self.accept()
