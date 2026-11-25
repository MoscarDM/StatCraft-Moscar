"""Dialogs for native StatCraft One-Sample t test."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox, QListWidget, QListWidgetItem,
    QStackedWidget, QWidget, QMessageBox, QGroupBox, QDialogButtonBox
)
from .dialog_theme import AutoErrorLabel, clamp_dialog_to_screen, dialog_stylesheet, is_dark_active
from .model import Worksheet
from .one_sample_t_engine import one_sample_t_settings
from .variable_dialogs import resolve_variables


def _show_context_help(dialog: QDialog, title: str, text: str) -> None:
    target = dialog.parent()
    while target is not None and not hasattr(target, "context_help"):
        target = target.parent() if callable(getattr(target, "parent", None)) else None
    if target is not None and hasattr(target, "context_help"):
        target.context_help(title)
        return
    QMessageBox.information(dialog, title, text)


class OneSampleTOptionsDialog(QDialog):
    """Options child dialog matching 1SAMPLETOPTIONS.MDF."""

    def __init__(self, options: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("One-Sample t: Options")
        self.setModal(True)
        self.options = dict(options)
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent or self)))
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)
        grid = QGridLayout()

        grid.addWidget(QLabel("Confidence level:"), 0, 0)
        self.conf_edit = QLineEdit(str(self.options.get("confidence_level", 95.0)))
        self.conf_edit.setMaximumWidth(90)
        grid.addWidget(self.conf_edit, 0, 1)

        grid.addWidget(QLabel("Alternative hypothesis:"), 1, 0)
        self.alt_combo = QComboBox()
        self.alt_combo.addItems([
            "Mean < hypothesized mean",
            "Mean ≠ hypothesized mean",
            "Mean > hypothesized mean",
        ])
        fm = self.alt_combo.fontMetrics()
        needed_w = max(fm.horizontalAdvance(self.alt_combo.itemText(i)) for i in range(self.alt_combo.count())) + 44
        self.alt_combo.setMinimumWidth(max(240, needed_w))
        alt_val = self.options.get("alternative", "not_equal")
        if alt_val == "less_than":
            self.alt_combo.setCurrentIndex(0)
        elif alt_val == "greater_than":
            self.alt_combo.setCurrentIndex(2)
        else:
            self.alt_combo.setCurrentIndex(1)
        grid.addWidget(self.alt_combo, 1, 1)

        layout.addLayout(grid)
        layout.addStretch()

        self.error = AutoErrorLabel()
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        clamp_dialog_to_screen(self, max(450, needed_w + 185), 270, min_w=420, min_h=240)

    def _accept(self):
        self.error.clear()
        try:
            c = float(self.conf_edit.text().strip())
            if not (0.0 < c < 100.0):
                raise ValueError
            self.options["confidence_level"] = c
        except ValueError:
            self.error.setText("Confidence level must be a number between 0 and 100.")
            return

        idx = self.alt_combo.currentIndex()
        if idx == 0:
            self.options["alternative"] = "less_than"
        elif idx == 2:
            self.options["alternative"] = "greater_than"
        else:
            self.options["alternative"] = "not_equal"

        self.accept()


class OneSampleTGraphsDialog(QDialog):
    """Graphs child dialog matching 1SAMPLETGRAPHS.MDF."""

    def __init__(self, graphs: Dict[str, bool], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("One-Sample t: Graphs")
        self.setModal(True)
        self.graphs = dict(graphs)
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent or self)))
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)

        self.hist_cb = QCheckBox("&Histogram")
        self.hist_cb.setChecked(bool(self.graphs.get("histogram", True)))
        layout.addWidget(self.hist_cb)

        self.ivp_cb = QCheckBox("&Individual value plot")
        self.ivp_cb.setChecked(bool(self.graphs.get("individual_value_plot", True)))
        layout.addWidget(self.ivp_cb)

        self.box_cb = QCheckBox("&Boxplot")
        self.box_cb.setChecked(bool(self.graphs.get("boxplot", True)))
        layout.addWidget(self.box_cb)

        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        clamp_dialog_to_screen(self, 380, 260, min_w=340, min_h=220)

    def _accept(self):
        self.graphs["histogram"] = self.hist_cb.isChecked()
        self.graphs["individual_value_plot"] = self.ivp_cb.isChecked()
        self.graphs["boxplot"] = self.box_cb.isChecked()
        self.accept()


class OneSampleTDialog(QDialog):
    """Main One-Sample t dialog matching 1SAMPLET.MDF (MenuID 41322)."""

    def __init__(self, worksheet: Optional[Worksheet] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("One-Sample t for the Mean")
        self.worksheet = worksheet
        self.active_edit: Optional[QLineEdit] = None
        self.result_payload: Optional[Dict[str, Any]] = None

        self.settings = one_sample_t_settings()
        from .variable_dialogs import default_confidence_percent
        self.settings["confidence_level"] = default_confidence_percent()
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent or self)))
        self.setSizeGripEnabled(True)
        self._build_ui()
        clamp_dialog_to_screen(self, 600, 440, min_w=540, min_h=380)

    def _populate_var_list(self):
        self.var_list.clear()
        if not self.worksheet:
            return
        needle = self.var_filter.text().strip().lower() if hasattr(self, "var_filter") else ""
        for idx, col in enumerate(self.worksheet.columns):
            if col.kind != "number":
                continue
            if needle and needle not in col.name.lower() and needle not in f"c{idx + 1}":
                continue
            item = QListWidgetItem(f"C{idx+1}   {col.name}")
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self.var_list.addItem(item)

    def _build_ui(self):
        main_layout = QHBoxLayout(self)

        # Left: Filter, Variable List & Select
        left_box = QVBoxLayout()
        self.var_filter = QLineEdit()
        self.var_filter.setPlaceholderText("Filter variables…")
        self.var_filter.setClearButtonEnabled(True)
        self.var_filter.textChanged.connect(self._populate_var_list)
        left_box.addWidget(self.var_filter)

        self.var_list = QListWidget()
        self._populate_var_list()
        self.var_list.itemDoubleClicked.connect(self._on_var_double_clicked)
        left_box.addWidget(self.var_list)

        self.select_btn = QPushButton("&Select")
        self.select_btn.clicked.connect(self._on_select_clicked)
        left_box.addWidget(self.select_btn)
        main_layout.addLayout(left_box, 1)

        # Right: Data Layout, Fields, Subdialog Buttons, Actions
        right_box = QVBoxLayout()

        self.combo_data = QComboBox()
        self.combo_data.addItems([
            "One or more samples, each in a column",
            "Summarized data",
        ])
        self.combo_data.currentIndexChanged.connect(self._on_data_format_changed)
        right_box.addWidget(self.combo_data)

        # Stacked pages for data inputs
        self.stack = QStackedWidget()

        # Page 0: Raw Column(s)
        page_raw = QWidget()
        raw_layout = QVBoxLayout(page_raw)
        raw_layout.addWidget(QLabel("Sample columns:"))
        self.sample_cols_edit = QLineEdit()
        self.sample_cols_edit.installEventFilter(self)
        raw_layout.addWidget(self.sample_cols_edit)
        raw_layout.addStretch()
        self.stack.addWidget(page_raw)

        # Page 1: Summarized Data
        page_sum = QWidget()
        sum_layout = QGridLayout(page_sum)

        sum_layout.addWidget(QLabel("Sample size:"), 0, 0)
        self.size_edit = QLineEdit("10")
        self.size_edit.installEventFilter(self)
        sum_layout.addWidget(self.size_edit, 0, 1)

        sum_layout.addWidget(QLabel("Sample mean:"), 1, 0)
        self.mean_edit = QLineEdit("0.0")
        self.mean_edit.installEventFilter(self)
        sum_layout.addWidget(self.mean_edit, 1, 1)

        sum_layout.addWidget(QLabel("Standard deviation:"), 2, 0)
        self.sd_edit = QLineEdit("1.0")
        self.sd_edit.installEventFilter(self)
        sum_layout.addWidget(self.sd_edit, 2, 1)

        self.stack.addWidget(page_sum)
        right_box.addWidget(self.stack)

        # Hypothesis test group
        test_group = QGroupBox()
        test_layout = QVBoxLayout(test_group)
        self.test_cb = QCheckBox("&Perform hypothesis test")
        self.test_cb.setChecked(True)
        self.test_cb.toggled.connect(self._on_test_toggled)
        test_layout.addWidget(self.test_cb)

        hyp_h = QHBoxLayout()
        self.hyp_lbl = QLabel("Hypothesized mean:")
        hyp_h.addWidget(self.hyp_lbl)
        self.hyp_edit = QLineEdit("0.0")
        self.hyp_edit.installEventFilter(self)
        self.hyp_edit.setMaximumWidth(100)
        hyp_h.addWidget(self.hyp_edit)
        hyp_h.addStretch()
        test_layout.addLayout(hyp_h)

        right_box.addWidget(test_group)
        right_box.addStretch()

        # Subdialog Buttons (Options, Graphs)
        sub_btns = QHBoxLayout()
        self.opts_btn = QPushButton("Optio&ns...")
        self.opts_btn.clicked.connect(self._on_options)
        self.graphs_btn = QPushButton("&Graphs...")
        self.graphs_btn.clicked.connect(self._on_graphs)
        sub_btns.addWidget(self.opts_btn)
        sub_btns.addWidget(self.graphs_btn)
        sub_btns.addStretch()
        right_box.addLayout(sub_btns)

        self.error = AutoErrorLabel()
        right_box.addWidget(self.error)

        # Action Buttons (OK, Cancel, Help)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Help
        )
        self.ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setDefault(True)
        self.cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.help_btn = buttons.button(QDialogButtonBox.StandardButton.Help)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        buttons.helpRequested.connect(lambda: _show_context_help(self, "One-Sample t", "Select one or more numeric columns or enter summarized data."))
        right_box.addWidget(buttons)

        main_layout.addLayout(right_box, 2)

        # Set default active edit
        self.active_edit = self.sample_cols_edit

    def eventFilter(self, obj, event):
        if event.type() == event.Type.FocusIn and isinstance(obj, QLineEdit):
            self.active_edit = obj
        return super().eventFilter(obj, event)

    def _on_data_format_changed(self, index: int):
        self.stack.setCurrentIndex(index)
        # In StatCraft, Graphs button is disabled when summarized data is selected
        is_raw = index == 0
        self.graphs_btn.setEnabled(is_raw)
        self.var_filter.setEnabled(is_raw)
        self.var_list.setEnabled(is_raw)
        self.select_btn.setEnabled(is_raw)
        if is_raw:
            self.active_edit = self.sample_cols_edit
        else:
            self.active_edit = self.size_edit

    def _on_test_toggled(self, checked: bool):
        self.hyp_lbl.setEnabled(checked)
        self.hyp_edit.setEnabled(checked)

    def _on_var_double_clicked(self, item):
        self._insert_var_text(item.text().split()[0])

    def _on_select_clicked(self):
        item = self.var_list.currentItem()
        if item:
            self._insert_var_text(item.text().split()[0])

    def _insert_var_text(self, var_id: str):
        if self.active_edit:
            cur = self.active_edit.text().strip()
            if self.active_edit == self.sample_cols_edit:
                # Can append multiple columns
                if cur:
                    self.active_edit.setText(f"{cur} {var_id}")
                else:
                    self.active_edit.setText(var_id)
            else:
                self.active_edit.setText(var_id)

    def _on_options(self):
        dlg = OneSampleTOptionsDialog(self.settings, self)
        if dlg.exec():
            self.settings.update(dlg.options)

    def _on_graphs(self):
        dlg = OneSampleTGraphsDialog(self.settings["graphs"], self)
        if dlg.exec():
            self.settings["graphs"] = dlg.graphs

    def _on_ok(self):
        self.error.clear()
        idx = self.combo_data.currentIndex()
        perform_test = self.test_cb.isChecked()
        hyp_mean = 0.0
        if perform_test:
            try:
                hyp_mean = float(self.hyp_edit.text().strip())
            except ValueError:
                self.error.setText("Hypothesized mean must be a valid number.")
                return

        if idx == 0:  # Raw Columns
            cols_text = self.sample_cols_edit.text().strip()
            if not cols_text:
                self.error.setText("Please specify at least one sample column.")
                return
            if self.worksheet is not None:
                try:
                    cols = resolve_variables(cols_text, self.worksheet, kinds=("number",))
                except ValueError as exc:
                    self.error.setText(str(exc))
                    return
                if not cols:
                    self.error.setText("Please specify at least one valid numeric sample column.")
                    return
            else:
                col_tokens = cols_text.split()
                cols: List[Any] = []
                for tok in col_tokens:
                    if tok.upper().startswith("C") and tok[1:].isdigit():
                        cols.append(int(tok[1:]) - 1)
                    else:
                        cols.append(tok)

            self.settings["data_format"] = 0
            self.settings["sample_cols"] = cols
            self.settings["perform_test"] = perform_test
            self.settings["hypothesized_mean"] = hyp_mean
        else:  # Summarized
            try:
                n = int(self.size_edit.text().strip())
                if n < 2:
                    raise ValueError
                m = float(self.mean_edit.text().strip())
                s = float(self.sd_edit.text().strip())
                if s < 0:
                    raise ValueError
            except ValueError:
                self.error.setText("Please enter valid summarized values (Sample size >= 2, StDev >= 0).")
                return

            self.settings["data_format"] = 2
            self.settings["summarized"] = {"n": n, "mean": m, "sd": s}
            self.settings["perform_test"] = perform_test
            self.settings["hypothesized_mean"] = hyp_mean
            self.settings["graphs"] = {"histogram": False, "individual_value_plot": False, "boxplot": False}

        self.result_payload = dict(self.settings)
        self.accept()

    def get_state(self) -> dict:
        import copy
        return {
            "data_idx": self.combo_data.currentIndex(),
            "sample_cols": self.sample_cols_edit.text(),
            "size": self.size_edit.text(),
            "mean": self.mean_edit.text(),
            "sd": self.sd_edit.text(),
            "perform_test": self.test_cb.isChecked(),
            "hyp": self.hyp_edit.text(),
            "settings": copy.deepcopy(self.settings),
        }

    def set_state(self, state: dict) -> None:
        import copy
        if not isinstance(state, dict):
            return
        if "data_idx" in state:
            self.combo_data.setCurrentIndex(int(state["data_idx"]))
        if "perform_test" in state:
            self.test_cb.setChecked(bool(state["perform_test"]))
        for attr, key in (("sample_cols_edit", "sample_cols"), ("size_edit", "size"), ("mean_edit", "mean"), ("sd_edit", "sd"), ("hyp_edit", "hyp")):
            if key in state:
                getattr(self, attr).setText(str(state[key]))
        if isinstance(state.get("settings"), dict):
            self.settings.update(copy.deepcopy(state["settings"]))
