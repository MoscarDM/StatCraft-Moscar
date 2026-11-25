"""Native StatCraft Capability Sixpack (Normal) dialogs.

Corresponds to PE MenuID 40168 and HelpID 95021:
Main dialog: Capability Sixpack (Normal Distribution)
Child dialogs:
- Options: Capability Analysis (0471-CAPABILITY.MDF)
- Estimate: Estimating Standard Deviation (1017-QUALITYESTSIGMA.MDF)
- Tests: Tests for Special Causes (Control charts in Sixpack)
"""

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
)

from .capability_dialogs import CapabilityOptionsDialog, CapabilityEstimateDialog
from .dialog_theme import AutoErrorLabel, clamp_dialog_to_screen, dialog_stylesheet, is_dark_active


def _show_context_help(dialog: QDialog, title: str, text: str) -> None:
    target = dialog.parent()
    while target is not None and not hasattr(target, "context_help"):
        target = target.parent() if callable(getattr(target, "parent", None)) else None
    if target is not None and hasattr(target, "context_help"):
        target.context_help(title)
        return
    QMessageBox.information(dialog, title, text)


def _resolve_sheet_col_name(worksheet, raw: str, allowed_kinds: Optional[tuple[str, ...]] = None) -> str:
    s = raw.strip().strip("'\"")
    if worksheet is None:
        return s
    for i, c in enumerate(worksheet.columns):
        if s.lower() == f"C{i + 1}   {c.name}".lower():
            if allowed_kinds and c.kind not in allowed_kinds:
                raise ValueError(f"Column '{c.name}' is not eligible for this field.")
            return c.name
    from .variable_dialogs import resolve_variables
    tokens = resolve_variables(raw, worksheet, kinds=allowed_kinds or ("number", "text", "date"))
    if not tokens:
        raise ValueError(f"Column '{s}' not found in worksheet.")
    return worksheet.columns[tokens[0]].name


class SixpackTestsDialog(QDialog):
    """Tests for Special Causes in Capability Sixpack control charts."""

    def __init__(self, options: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Capability Sixpack: Tests")
        self.setModal(True)
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent or self)))
        self.setSizeGripEnabled(True)
        self.options = dict(options or {})

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        box = QGroupBox("Perform tests for special causes")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(8)

        self.chk_test1 = QCheckBox("1 point > 3.00 standard deviations from center line")
        self.chk_test1.setChecked(self.options.get("test1", True))
        box_layout.addWidget(self.chk_test1)

        self.chk_test2 = QCheckBox("9 points in a row on same side of center line")
        self.chk_test2.setChecked(self.options.get("test2", False))
        box_layout.addWidget(self.chk_test2)

        self.chk_test3 = QCheckBox("6 points in a row, all increasing or all decreasing")
        self.chk_test3.setChecked(self.options.get("test3", False))
        box_layout.addWidget(self.chk_test3)

        self.chk_test4 = QCheckBox("14 points in a row, alternating up and down")
        self.chk_test4.setChecked(self.options.get("test4", False))
        box_layout.addWidget(self.chk_test4)

        layout.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        clamp_dialog_to_screen(self, 420, 240, min_w=360, min_h=200)

    def _accept(self):
        self.options["test1"] = self.chk_test1.isChecked()
        self.options["test2"] = self.chk_test2.isChecked()
        self.options["test3"] = self.chk_test3.isChecked()
        self.options["test4"] = self.chk_test4.isChecked()
        self.accept()


class CapabilitySixpackDialog(QDialog):
    """Main dialog for Stat > Quality Tools > Capability Sixpack > Normal / Between/Within."""

    def __init__(self, worksheet=None, parent=None, analysis_mode: str = "normal"):
        super().__init__(parent)
        self.analysis_mode = analysis_mode
        title_mode = "Between/Within" if analysis_mode == "between_within" else "Normal Distribution"
        self.setWindowTitle(f"Capability Sixpack ({title_mode})")
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent or self)))
        self.setSizeGripEnabled(True)
        self.worksheet = worksheet
        self.columns: List[str] = []
        self._col_meta: List[tuple[int, str, str]] = []
        if worksheet and hasattr(worksheet, "columns"):
            self.columns = [c.name for c in worksheet.columns]
            self._col_meta = [(i, c.name, getattr(c, "kind", "number")) for i, c in enumerate(worksheet.columns)]

        self.selected_params: Optional[Dict[str, Any]] = None
        self._last_filter_kinds: Optional[tuple[str, ...]] = ("number",)
        from .variable_dialogs import default_confidence_percent
        self.options: Dict[str, Any] = {
            "tolerance_k": 6.0,
            "stats_type": "capability",
            "display_unit": "ppm",
            "confidence_level": default_confidence_percent(),
            "ci_type": "two_sided",
            "include_ci": False,
            "include_ccpk": False,
            "within_subgroup_method": "pooled",
            "unbiased_within": True,
            "unbiased_overall": False,
            "test1": True,
        }

        outer_layout = QVBoxLayout(self)
        outer_layout.setSpacing(8)
        main_layout = QHBoxLayout()
        main_layout.setSpacing(12)

        # Left Column List
        left_layout = QVBoxLayout()
        lbl_cols = QLabel("Columns:")
        left_layout.addWidget(lbl_cols)

        self.var_filter = QLineEdit()
        self.var_filter.setPlaceholderText("Filter variables…")
        self.var_filter.setClearButtonEnabled(True)
        self.var_filter.textChanged.connect(lambda _txt: self._populate_col_list(self._last_filter_kinds))
        left_layout.addWidget(self.var_filter)

        self.col_list = QListWidget()
        self.col_list.itemDoubleClicked.connect(self._insert_selected_column)
        left_layout.addWidget(self.col_list)

        btn_select = QPushButton("Select")
        btn_select.clicked.connect(self._insert_selected_column)
        left_layout.addWidget(btn_select)
        main_layout.addLayout(left_layout, 1)

        # Center Controls Layout
        center_layout = QVBoxLayout()
        center_layout.setSpacing(10)

        # 1. Data Arrangement Group
        arr_box = QGroupBox("Data arrangement")
        arr_layout = QVBoxLayout(arr_box)

        # Option A: Single column
        self.rb_single_col = QRadioButton("Data are in &one column:")
        self.rb_across_rows = QRadioButton("Subgroups across &rows of:")
        self.arr_group = QButtonGroup(self)
        self.arr_group.addButton(self.rb_single_col)
        self.arr_group.addButton(self.rb_across_rows)
        self.rb_single_col.setChecked(True)

        sc_grid = QGridLayout()
        self.edit_single_col = QLineEdit()
        self.rb_single_col.toggled.connect(self._update_arrangement_state)
        sc_grid.addWidget(self.rb_single_col, 0, 0)
        sc_grid.addWidget(self.edit_single_col, 0, 1)

        lbl_sub_size = QLabel("&Subgroup size or ID column:")
        self.edit_sub_size = QLineEdit("1")
        lbl_sub_size.setBuddy(self.edit_sub_size)
        sc_grid.addWidget(lbl_sub_size, 1, 0, Qt.AlignmentFlag.AlignRight)
        sc_grid.addWidget(self.edit_sub_size, 1, 1)
        arr_layout.addLayout(sc_grid)

        # Option B: Across rows
        ar_grid = QGridLayout()
        self.edit_across_rows = QLineEdit()
        ar_grid.addWidget(self.rb_across_rows, 0, 0)
        ar_grid.addWidget(self.edit_across_rows, 0, 1)
        arr_layout.addLayout(ar_grid)

        center_layout.addWidget(arr_box)

        # 2. Specification Limits Group
        spec_box = QGroupBox("Specification limits (at least 1 required)")
        spec_grid = QGridLayout(spec_box)

        lbl_lsl = QLabel("&Lower spec:")
        self.edit_lsl = QLineEdit()
        lbl_lsl.setBuddy(self.edit_lsl)
        self.chk_lsl_bound = QCheckBox("Bound")
        self.chk_lsl_bound.setToolTip("Treat as a natural physical boundary rather than a specification limit.")
        spec_grid.addWidget(lbl_lsl, 0, 0)
        spec_grid.addWidget(self.edit_lsl, 0, 1)
        spec_grid.addWidget(self.chk_lsl_bound, 0, 2)

        lbl_usl = QLabel("&Upper spec:")
        self.edit_usl = QLineEdit()
        lbl_usl.setBuddy(self.edit_usl)
        self.chk_usl_bound = QCheckBox("Bound")
        self.chk_usl_bound.setToolTip("Treat as a natural physical boundary rather than a specification limit.")
        spec_grid.addWidget(lbl_usl, 1, 0)
        spec_grid.addWidget(self.edit_usl, 1, 1)
        spec_grid.addWidget(self.chk_usl_bound, 1, 2)

        center_layout.addWidget(spec_box)

        # 3. Historical Parameters Group (Optional)
        hist_box = QGroupBox("Historical parameters (optional)")
        hist_grid = QGridLayout(hist_box)

        lbl_hmean = QLabel("Historical &mean:")
        self.edit_hmean = QLineEdit()
        lbl_hmean.setBuddy(self.edit_hmean)
        hist_grid.addWidget(lbl_hmean, 0, 0)
        hist_grid.addWidget(self.edit_hmean, 0, 1)

        lbl_hsd = QLabel("Historical &standard deviation:")
        self.edit_hsd = QLineEdit()
        lbl_hsd.setBuddy(self.edit_hsd)
        hist_grid.addWidget(lbl_hsd, 1, 0)
        hist_grid.addWidget(self.edit_hsd, 1, 1)

        center_layout.addWidget(hist_box)
        main_layout.addLayout(center_layout, 2)

        # Right Action Buttons
        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)

        btn_ok = QPushButton("OK")
        btn_ok.setDefault(True)
        btn_cancel = QPushButton("Cancel")
        btn_help = QPushButton("Help")

        btn_estimate = QPushButton("&Estimate...")
        btn_options = QPushButton("O&ptions...")
        btn_tests = QPushButton("&Tests...")

        btn_ok.clicked.connect(self._accept)
        btn_cancel.clicked.connect(self.reject)
        btn_help.clicked.connect(lambda: _show_context_help(self, self.windowTitle(), "Configure Capability Sixpack data arrangement, subgroup size/ID, and specification limits."))
        btn_estimate.clicked.connect(self._open_estimate)
        btn_options.clicked.connect(self._open_options)
        btn_tests.clicked.connect(self._open_tests)

        right_layout.addWidget(btn_ok)
        right_layout.addWidget(btn_cancel)
        right_layout.addWidget(btn_help)
        right_layout.addSpacing(15)
        right_layout.addWidget(btn_estimate)
        right_layout.addWidget(btn_options)
        right_layout.addWidget(btn_tests)
        right_layout.addStretch()

        main_layout.addLayout(right_layout)
        outer_layout.addLayout(main_layout, 1)
        self.error = AutoErrorLabel()
        outer_layout.addWidget(self.error)

        # Focus tracking
        self._last_focused_edit = self.edit_single_col
        self.edit_single_col.installEventFilter(self)
        self.edit_sub_size.installEventFilter(self)
        self.edit_across_rows.installEventFilter(self)
        self.edit_lsl.installEventFilter(self)
        self.edit_usl.installEventFilter(self)

        self._update_arrangement_state()
        clamp_dialog_to_screen(self, 680, 480, min_w=580, min_h=400)

    def _eligible_kinds_for(self, obj) -> Optional[tuple[str, ...]]:
        if obj in (self.edit_single_col, self.edit_across_rows):
            return ("number",)
        if obj is self.edit_sub_size:
            return ("number", "text")
        return None

    def _populate_col_list(self, kinds: Optional[tuple[str, ...]] = None):
        self._last_filter_kinds = kinds
        self.col_list.clear()
        needle = self.var_filter.text().strip().lower() if hasattr(self, "var_filter") else ""
        for i, name, kind in self._col_meta:
            if self.worksheet is not None and kinds is not None and kind not in kinds:
                continue
            if needle and needle not in name.lower() and needle not in f"c{i + 1}":
                continue
            item = QListWidgetItem(f"C{i + 1}   {name}")
            item.setToolTip(f"C{i + 1}: {name} ({kind})")
            item.setData(Qt.ItemDataRole.UserRole, (i, name, kind))
            self.col_list.addItem(item)

    def eventFilter(self, obj, event):
        if event.type() == event.Type.FocusIn:
            if obj in (self.edit_single_col, self.edit_sub_size, self.edit_across_rows):
                self._last_focused_edit = obj
                self._populate_col_list(self._eligible_kinds_for(obj))
            elif obj in (self.edit_lsl, self.edit_usl):
                self._populate_col_list(None)
        return super().eventFilter(obj, event)

    def _insert_selected_column(self):
        cur_item = self.col_list.currentItem()
        if not cur_item or not self._last_focused_edit:
            return
        meta = cur_item.data(Qt.ItemDataRole.UserRole)
        col_text = meta[1] if isinstance(meta, tuple) and len(meta) >= 2 else cur_item.text()
        if self._last_focused_edit == self.edit_across_rows:
            current = self.edit_across_rows.text().strip()
            self.edit_across_rows.setText(f"{current} '{col_text}'" if current else f"'{col_text}'")
        else:
            self._last_focused_edit.setText(col_text)

    def _update_arrangement_state(self):
        single = self.rb_single_col.isChecked()
        self.edit_single_col.setEnabled(single)
        self.edit_sub_size.setEnabled(single)
        self.edit_across_rows.setEnabled(not single)
        if single:
            self._last_focused_edit = self.edit_single_col
        else:
            self._last_focused_edit = self.edit_across_rows
        self._populate_col_list(self._eligible_kinds_for(self._last_focused_edit))

    def _open_options(self):
        dlg = CapabilityOptionsDialog(self.options, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.options.update(dlg.options)

    def _open_estimate(self):
        dlg = CapabilityEstimateDialog(self.options, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.options.update(dlg.options)

    def _open_tests(self):
        dlg = SixpackTestsDialog(self.options, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.options.update(dlg.options)

    def _accept(self):
        self.error.clear()
        single = self.rb_single_col.isChecked()
        raw_single = self.edit_single_col.text().strip()
        across_text = self.edit_across_rows.text().strip()
        raw_sub = self.edit_sub_size.text().strip()

        if single:
            if not raw_single:
                self.error.setText("Please select or enter a numeric data column.")
                return
            try:
                col_name = _resolve_sheet_col_name(self.worksheet, raw_single, allowed_kinds=("number",))
            except ValueError as exc:
                self.error.setText(str(exc))
                return
            if not raw_sub:
                self.error.setText("Please enter a subgroup size or subgroup indicator column.")
                return
            if raw_sub.isdigit():
                sub_size_text = raw_sub
                if int(sub_size_text) < 1:
                    self.error.setText("Subgroup size must be a positive integer.")
                    return
            else:
                try:
                    sub_size_text = _resolve_sheet_col_name(self.worksheet, raw_sub, allowed_kinds=("number", "text"))
                except ValueError as exc:
                    self.error.setText(str(exc))
                    return
            cols_across_list = []
        else:
            if not across_text:
                self.error.setText("Please enter columns across rows.")
                return
            import re
            tokens = re.findall(r"'([^']*)'|\"([^\"]*)\"|(\S+)", across_text)
            raw_tokens = [t[0] or t[1] or t[2] for t in tokens if (t[0] or t[1] or t[2])]
            try:
                cols_across_list = [
                    _resolve_sheet_col_name(self.worksheet, tok, allowed_kinds=("number",))
                    for tok in raw_tokens
                ]
            except ValueError as exc:
                self.error.setText(str(exc))
                return
            col_name = cols_across_list[0] if cols_across_list else "Data"
            sub_size_text = ""

        # Spec limits validation
        lsl_text = self.edit_lsl.text().strip()
        usl_text = self.edit_usl.text().strip()
        if not lsl_text and not usl_text:
            self.error.setText("At least one specification limit (Lower or Upper spec) is required.")
            return

        lsl_val = None
        if lsl_text:
            try:
                lsl_val = float(lsl_text)
            except ValueError:
                self.error.setText(f"Invalid Lower spec limit: '{lsl_text}'.")
                return

        usl_val = None
        if usl_text:
            try:
                usl_val = float(usl_text)
            except ValueError:
                self.error.setText(f"Invalid Upper spec limit: '{usl_text}'.")
                return

        if lsl_val is not None and usl_val is not None and lsl_val >= usl_val:
            self.error.setText("Lower specification limit must be strictly less than Upper specification limit.")
            return

        hmean_val = None
        if self.edit_hmean.text().strip():
            try:
                hmean_val = float(self.edit_hmean.text().strip())
            except ValueError:
                self.error.setText("Invalid Historical mean value.")
                return

        hsd_val = None
        if self.edit_hsd.text().strip():
            try:
                hsd_val = float(self.edit_hsd.text().strip())
                if hsd_val <= 0:
                    raise ValueError()
            except ValueError:
                self.error.setText("Historical standard deviation must be positive.")
                return

        self.selected_params = {
            "single_column": single,
            "analysis_mode": self.analysis_mode,
            "column_name": col_name,
            "subgroup_spec": sub_size_text if single else None,
            "cols_across": cols_across_list if not single else None,
            "lsl": lsl_val,
            "usl": usl_val,
            "lsl_bound": self.chk_lsl_bound.isChecked(),
            "usl_bound": self.chk_usl_bound.isChecked(),
            "historical_mean": hmean_val,
            "historical_stdev": hsd_val,
            "options": dict(self.options),
        }

        self.accept()

    def get_state(self) -> Dict[str, Any]:
        import copy
        return {
            "single": self.rb_single_col.isChecked(),
            "col": self.edit_single_col.text(),
            "sub": self.edit_sub_size.text(),
            "across": self.edit_across_rows.text(),
            "lsl": self.edit_lsl.text(),
            "usl": self.edit_usl.text(),
            "lsl_bound": self.chk_lsl_bound.isChecked(),
            "usl_bound": self.chk_usl_bound.isChecked(),
            "hmean": self.edit_hmean.text(),
            "hsd": self.edit_hsd.text(),
            "options": copy.deepcopy(self.options),
        }

    def set_state(self, state: Dict[str, Any]) -> None:
        import copy
        if not isinstance(state, dict):
            return
        if "single" in state:
            self.rb_single_col.setChecked(bool(state["single"]))
            self.rb_across_rows.setChecked(not bool(state["single"]))
        for attr, key in (
            ("edit_single_col", "col"),
            ("edit_sub_size", "sub"),
            ("edit_across_rows", "across"),
            ("edit_lsl", "lsl"),
            ("edit_usl", "usl"),
            ("edit_hmean", "hmean"),
            ("edit_hsd", "hsd"),
        ):
            if key in state:
                getattr(self, attr).setText(str(state[key]))
        if "lsl_bound" in state:
            self.chk_lsl_bound.setChecked(bool(state["lsl_bound"]))
        if "usl_bound" in state:
            self.chk_usl_bound.setChecked(bool(state["usl_bound"]))
        if isinstance(state.get("options"), dict):
            self.options.update(copy.deepcopy(state["options"]))



class CapabilitySixpackNonnormalDialog(QDialog):
    """Main dialog for Stat > Quality Tools > Capability Sixpack > Nonnormal..."""

    def __init__(self, worksheet=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Capability Sixpack (Nonnormal Distribution)")
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent or self)))
        self.setSizeGripEnabled(True)
        self.worksheet = worksheet
        self._col_meta: List[tuple[int, str, str]] = []
        self._last_filter_kinds: Optional[tuple[str, ...]] = ("number",)
        if worksheet and hasattr(worksheet, "columns"):
            self._col_meta = [(i, c.name, getattr(c, "kind", "number")) for i, c in enumerate(worksheet.columns)]

        self.selected_params: Optional[Dict[str, Any]] = None

        outer_layout = QVBoxLayout(self)
        outer_layout.setSpacing(8)
        main_layout = QHBoxLayout()
        main_layout.setSpacing(12)

        # Left Column List
        left_layout = QVBoxLayout()
        lbl_cols = QLabel("Columns:")
        left_layout.addWidget(lbl_cols)

        self.var_filter = QLineEdit()
        self.var_filter.setPlaceholderText("Filter variables…")
        self.var_filter.setClearButtonEnabled(True)
        self.var_filter.textChanged.connect(lambda _txt: self._populate_col_list(self._last_filter_kinds))
        left_layout.addWidget(self.var_filter)

        self.col_list = QListWidget()
        self.col_list.itemDoubleClicked.connect(self._insert_selected_column)
        left_layout.addWidget(self.col_list)

        btn_select = QPushButton("Select")
        btn_select.clicked.connect(self._insert_selected_column)
        left_layout.addWidget(btn_select)
        main_layout.addLayout(left_layout, 1)

        # Center Controls Layout
        center_layout = QVBoxLayout()
        center_layout.setSpacing(10)

        # Single column data
        box_data = QGroupBox("Data arrangement")
        form_data = QGridLayout(box_data)
        lbl_col = QLabel("Single column:")
        self.edit_col = QLineEdit()
        form_data.addWidget(lbl_col, 0, 0)
        form_data.addWidget(self.edit_col, 0, 1)

        lbl_sub = QLabel("Subgroup size:")
        self.edit_sub = QLineEdit("1")
        form_data.addWidget(lbl_sub, 1, 0)
        form_data.addWidget(self.edit_sub, 1, 1)
        center_layout.addWidget(box_data)

        # Distribution selection
        box_dist = QGroupBox("Fit Distribution")
        form_dist = QGridLayout(box_dist)
        lbl_d = QLabel("Distribution:")
        self.cbo_dist = QComboBox()
        self.cbo_dist.addItems(["Weibull", "Lognormal", "Exponential", "Gamma", "Normal"])
        form_dist.addWidget(lbl_d, 0, 0)
        form_dist.addWidget(self.cbo_dist, 0, 1)
        center_layout.addWidget(box_dist)

        # Spec Limits Group
        spec_box = QGroupBox("Specification limits")
        spec_grid = QGridLayout(spec_box)
        lbl_lsl = QLabel("Lower spec (LSL):")
        self.edit_lsl = QLineEdit()
        lbl_usl = QLabel("Upper spec (USL):")
        self.edit_usl = QLineEdit()
        lbl_tgt = QLabel("Target (optional):")
        self.edit_tgt = QLineEdit()

        spec_grid.addWidget(lbl_lsl, 0, 0)
        spec_grid.addWidget(self.edit_lsl, 0, 1)
        spec_grid.addWidget(lbl_usl, 1, 0)
        spec_grid.addWidget(self.edit_usl, 1, 1)
        spec_grid.addWidget(lbl_tgt, 2, 0)
        spec_grid.addWidget(self.edit_tgt, 2, 1)
        center_layout.addWidget(spec_box)

        main_layout.addLayout(center_layout, 2)

        # Action Buttons Layout (Right side)
        right_layout = QVBoxLayout()
        btn_ok = QPushButton("OK")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)

        right_layout.addWidget(btn_ok)
        right_layout.addWidget(btn_cancel)
        right_layout.addStretch()
        main_layout.addLayout(right_layout)
        outer_layout.addLayout(main_layout, 1)

        self.error = AutoErrorLabel()
        outer_layout.addWidget(self.error)

        self._last_focused_edit = self.edit_col
        self.edit_col.installEventFilter(self)
        self.edit_sub.installEventFilter(self)
        self._populate_col_list(("number",))
        clamp_dialog_to_screen(self, 620, 440, min_w=540, min_h=380)

    def _populate_col_list(self, kinds: Optional[tuple[str, ...]] = None):
        self._last_filter_kinds = kinds
        self.col_list.clear()
        needle = self.var_filter.text().strip().lower() if hasattr(self, "var_filter") else ""
        for i, name, kind in self._col_meta:
            if self.worksheet is not None and kinds is not None and kind not in kinds:
                continue
            if needle and needle not in name.lower() and needle not in f"c{i + 1}":
                continue
            item = QListWidgetItem(f"C{i + 1}   {name}")
            item.setToolTip(f"C{i + 1}: {name} ({kind})")
            item.setData(Qt.ItemDataRole.UserRole, (i, name, kind))
            self.col_list.addItem(item)

    def eventFilter(self, obj, event):
        if event.type() == event.Type.FocusIn and obj in (self.edit_col, self.edit_sub):
            self._last_focused_edit = obj
            kinds = ("number",) if obj is self.edit_col else ("number", "text")
            self._populate_col_list(kinds)
        return super().eventFilter(obj, event)

    def _insert_selected_column(self):
        item = self.col_list.currentItem()
        if not item:
            return
        meta = item.data(Qt.ItemDataRole.UserRole)
        col_text = meta[1] if isinstance(meta, tuple) and len(meta) >= 2 else item.text()
        if " " in col_text:
            col_text = f"'{col_text}'"
        target = getattr(self, "_last_focused_edit", self.edit_col) or self.edit_col
        target.setText(col_text)

    def _accept(self):
        self.error.clear()
        raw_col = self.edit_col.text().strip()
        if not raw_col:
            self.error.setText("Please specify a numeric data column.")
            return
        try:
            col_name = _resolve_sheet_col_name(self.worksheet, raw_col, allowed_kinds=("number",))
        except ValueError as exc:
            self.error.setText(str(exc))
            return

        lsl_val = None
        if self.edit_lsl.text().strip():
            try:
                lsl_val = float(self.edit_lsl.text().strip())
            except ValueError:
                self.error.setText("Invalid Lower Spec Limit.")
                return

        usl_val = None
        if self.edit_usl.text().strip():
            try:
                usl_val = float(self.edit_usl.text().strip())
            except ValueError:
                self.error.setText("Invalid Upper Spec Limit.")
                return

        if lsl_val is not None and usl_val is not None and lsl_val >= usl_val:
            self.error.setText("Lower specification limit must be strictly less than Upper specification limit.")
            return

        tgt_val = None
        if self.edit_tgt.text().strip():
            try:
                tgt_val = float(self.edit_tgt.text().strip())
            except ValueError:
                self.error.setText("Target must be a valid number.")
                return

        if lsl_val is None and usl_val is None:
            self.error.setText("At least one specification limit (LSL or USL) must be provided.")
            return

        raw_sub = self.edit_sub.text().strip() or "1"
        if raw_sub.isdigit():
            sub_spec = raw_sub
            if int(sub_spec) < 1:
                self.error.setText("Subgroup size must be a positive integer.")
                return
        else:
            try:
                sub_spec = _resolve_sheet_col_name(self.worksheet, raw_sub, allowed_kinds=("number", "text"))
            except ValueError as exc:
                self.error.setText(str(exc))
                return
        dist = self.cbo_dist.currentText().lower()

        self.selected_params = {
            "single_column": True,
            "column_name": col_name,
            "subgroup_spec": sub_spec,
            "distribution": dist,
            "lsl": lsl_val,
            "usl": usl_val,
            "target": tgt_val,
        }
        self.accept()

    def get_state(self) -> dict:
        return {
            "col": self.edit_col.text(),
            "sub": self.edit_sub.text(),
            "dist_idx": self.cbo_dist.currentIndex(),
            "lsl": self.edit_lsl.text(),
            "usl": self.edit_usl.text(),
            "target": self.edit_tgt.text(),
        }

    def set_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            return
        if "dist_idx" in state:
            self.cbo_dist.setCurrentIndex(int(state["dist_idx"]))
        for attr, key in (("edit_col", "col"), ("edit_sub", "sub"), ("edit_lsl", "lsl"), ("edit_usl", "usl"), ("edit_tgt", "target")):
            if key in state:
                getattr(self, attr).setText(str(state[key]))
