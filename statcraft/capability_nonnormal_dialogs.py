"""Dialog for Nonnormal Capability Analysis matching StatCraft PE forms."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QFrame,
    QGroupBox,
    QWidget,
)

from .dialog_theme import AutoErrorLabel, clamp_dialog_to_screen, dialog_stylesheet, is_dark_active
from .model import Worksheet
from .variable_dialogs import resolve_variables


class CapabilityNonnormalDialog(QDialog):
    """Native StatCraft dialog for Nonnormal Capability Analysis."""

    def __init__(self, worksheet: Worksheet, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.worksheet = worksheet
        self.setWindowTitle("Capability Analysis (Nonnormal Distribution)")
        self.setModal(True)
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent or self)))
        self.setSizeGripEnabled(True)

        from .variable_dialogs import default_confidence_percent
        self.options: Dict[str, Any] = {
            "dist_or_transform": "weibull",
            "naming_convention": "classical",
            "tolerance_k": 6.0,
            "confidence_level": default_confidence_percent() / 100.0,
        }
        self.selected_params: Optional[Dict[str, Any]] = None
        self.entry: Optional[Dict[str, Any]] = None

        layout = QVBoxLayout(self)

        # Main grid: Left column picker, right form fields
        main_grid = QGridLayout()

        # Variable list
        v_box = QVBoxLayout()
        v_box.addWidget(QLabel("Columns:"))
        self.var_filter = QLineEdit()
        self.var_filter.setPlaceholderText("Filter variables…")
        self.var_filter.setClearButtonEnabled(True)
        self.var_filter.textChanged.connect(self._populate_col_list)
        v_box.addWidget(self.var_filter)

        self.col_list = QListWidget()
        self._populate_col_list()
        self.col_list.itemDoubleClicked.connect(self._on_col_double_clicked)
        v_box.addWidget(self.col_list)

        btn_select = QPushButton("Select")
        btn_select.clicked.connect(self._on_select_clicked)
        v_box.addWidget(btn_select)
        main_grid.addLayout(v_box, 0, 0, 5, 1)

        # Fields
        form_layout = QGridLayout()
        form_layout.addWidget(QLabel("Single column:"), 0, 0)
        self.edit_single_col = QLineEdit()
        form_layout.addWidget(self.edit_single_col, 0, 1)

        # Distribution / Transformation combo
        form_layout.addWidget(QLabel("Fit distribution:"), 1, 0)
        self.combo_dist = QComboBox()
        self.combo_dist.addItem("Weibull", "weibull")
        self.combo_dist.addItem("Lognormal", "lognormal")
        self.combo_dist.addItem("Exponential", "exponential")
        self.combo_dist.addItem("Gamma", "gamma")
        self.combo_dist.addItem("Box-Cox Transformation", "box_cox")
        form_layout.addWidget(self.combo_dist, 1, 1)

        # Specification limits
        form_layout.addWidget(QLabel("Lower spec (LSL):"), 2, 0)
        self.edit_lsl = QLineEdit()
        form_layout.addWidget(self.edit_lsl, 2, 1)

        form_layout.addWidget(QLabel("Upper spec (USL):"), 3, 0)
        self.edit_usl = QLineEdit()
        form_layout.addWidget(self.edit_usl, 3, 1)

        form_layout.addWidget(QLabel("Target:"), 4, 0)
        self.edit_target = QLineEdit()
        form_layout.addWidget(self.edit_target, 4, 1)

        # AIAG/VDA Nomenclature
        self.chk_aiag_vda = QCheckBox("Use Unified AIAG/VDA nomenclature (Cnp, Cnpk)")
        form_layout.addWidget(self.chk_aiag_vda, 5, 0, 1, 2)

        main_grid.addLayout(form_layout, 0, 1, 5, 1)
        layout.addLayout(main_grid)

        self.error = AutoErrorLabel()
        layout.addWidget(self.error)

        # Dialog Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        clamp_dialog_to_screen(self, 580, 440, min_w=520, min_h=380)

    def _populate_col_list(self):
        self.col_list.clear()
        needle = self.var_filter.text().strip().lower() if hasattr(self, "var_filter") else ""
        for idx, col in enumerate(self.worksheet.columns):
            if col.kind != "number":
                continue
            if needle and needle not in col.name.lower() and needle not in f"c{idx + 1}":
                continue
            item = QListWidgetItem(f"C{idx + 1}   {col.name}")
            item.setToolTip(f"C{idx + 1}: {col.name} ({col.kind})")
            item.setData(Qt.ItemDataRole.UserRole, (idx, col.name))
            self.col_list.addItem(item)

    def _on_col_double_clicked(self, item):
        meta = item.data(Qt.ItemDataRole.UserRole)
        self.edit_single_col.setText(meta[1] if isinstance(meta, tuple) else item.text())

    def _on_select_clicked(self):
        item = self.col_list.currentItem()
        if item:
            meta = item.data(Qt.ItemDataRole.UserRole)
            self.edit_single_col.setText(meta[1] if isinstance(meta, tuple) else item.text())

    def _on_ok(self):
        self.error.clear()
        raw_col = self.edit_single_col.text().strip()
        if not raw_col:
            self.error.setText("Please specify a numeric measurement column.")
            return

        col_idx = None
        cleaned = raw_col.strip("'\"")
        for i, c in enumerate(self.worksheet.columns):
            if cleaned.lower() == f"C{i + 1}   {c.name}".lower() or c.name == cleaned or f"C{i+1}" == cleaned.upper():
                if c.kind != "number":
                    self.error.setText(f"Column '{c.name}' must be numeric.")
                    return
                col_idx = i
                break
        if col_idx is None:
            try:
                tokens = resolve_variables(raw_col, self.worksheet, kinds=("number",))
                if tokens:
                    col_idx = tokens[0]
            except ValueError as exc:
                self.error.setText(str(exc))
                return

        if col_idx is None:
            self.error.setText(f"Column '{cleaned}' not found.")
            return

        lsl_val = None
        if self.edit_lsl.text().strip():
            try:
                lsl_val = float(self.edit_lsl.text().strip())
            except ValueError:
                self.error.setText("LSL must be a valid number.")
                return

        usl_val = None
        if self.edit_usl.text().strip():
            try:
                usl_val = float(self.edit_usl.text().strip())
            except ValueError:
                self.error.setText("USL must be a valid number.")
                return

        if lsl_val is None and usl_val is None:
            self.error.setText("At least one specification limit (LSL or USL) must be entered.")
            return

        if lsl_val is not None and usl_val is not None and lsl_val >= usl_val:
            self.error.setText("LSL must be strictly less than USL.")
            return

        target_val = None
        if self.edit_target.text().strip():
            try:
                target_val = float(self.edit_target.text().strip())
            except ValueError:
                self.error.setText("Target must be a valid number.")
                return

        dist_val = self.combo_dist.currentData()
        naming = "aiag_vda" if self.chk_aiag_vda.isChecked() else "classical"

        self.selected_params = {
            "variable_index": col_idx,
            "column_index": col_idx,
            "column_name": self.worksheet.columns[col_idx].name,
            "dist_or_transform": dist_val,
            "lsl": lsl_val,
            "usl": usl_val,
            "target": target_val,
            "naming_convention": naming,
            "tolerance_k": 6.0,
        }
        self.accept()

    def get_state(self) -> Dict[str, Any]:
        return {
            "col": self.edit_single_col.text(),
            "dist_idx": self.combo_dist.currentIndex(),
            "lsl": self.edit_lsl.text(),
            "usl": self.edit_usl.text(),
            "target": self.edit_target.text(),
            "aiag_vda": self.chk_aiag_vda.isChecked(),
        }

    def set_state(self, state: Dict[str, Any]) -> None:
        if not isinstance(state, dict):
            return
        if "dist_idx" in state:
            self.combo_dist.setCurrentIndex(int(state["dist_idx"]))
        for attr, key in (("edit_single_col", "col"), ("edit_lsl", "lsl"), ("edit_usl", "usl"), ("edit_target", "target")):
            if key in state:
                getattr(self, attr).setText(str(state[key]))
        if "aiag_vda" in state:
            self.chk_aiag_vda.setChecked(bool(state["aiag_vda"]))
