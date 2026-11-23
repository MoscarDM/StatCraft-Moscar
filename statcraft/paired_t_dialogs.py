"""Dialogs for native StatCraft Paired t test."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox, QListWidget, QListWidgetItem,
    QStackedWidget, QWidget, QMessageBox, QGroupBox, QDialogButtonBox
)
from .dialog_theme import AutoErrorLabel, clamp_dialog_to_screen, dialog_stylesheet, is_dark_active, subtle_label_style
from .model import Worksheet
from .paired_t_engine import paired_t_settings
from .variable_dialogs import resolve_variables


def _show_context_help(dialog: QDialog, title: str, text: str) -> None:
    target = dialog.parent()
    while target is not None and not hasattr(target, "context_help"):
        target = target.parent() if callable(getattr(target, "parent", None)) else None
    if target is not None and hasattr(target, "context_help"):
        target.context_help(title)
        return
    QMessageBox.information(dialog, title, text)


class PairedTOptionsDialog(QDialog):
    """Options child dialog matching PAIREDTOPTIONS.MDF."""

    def __init__(self, options: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Paired t: Options")
        self.setModal(True)
        self.options = dict(options)
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent or self)))
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)

        diff_lbl = QLabel("Difference = mean of (sample 1 - sample 2)")
        diff_lbl.setStyleSheet(subtle_label_style(is_dark_active(parent or self), bold=True, font_size="9pt"))
        layout.addWidget(diff_lbl)

        grid = QGridLayout()

        grid.addWidget(QLabel("Confidence level:"), 0, 0)
        self.conf_edit = QLineEdit(str(self.options.get("confidence_level", 95.0)))
        self.conf_edit.setMaximumWidth(90)
        grid.addWidget(self.conf_edit, 0, 1)

        grid.addWidget(QLabel("Hypothesized difference:"), 1, 0)
        self.hyp_edit = QLineEdit(str(self.options.get("hypothesized_difference", 0.0)))
        self.hyp_edit.setMaximumWidth(90)
        grid.addWidget(self.hyp_edit, 1, 1)

        grid.addWidget(QLabel("Alternative hypothesis:"), 2, 0)
        self.alt_combo = QComboBox()
        self.alt_combo.addItems([
            "Difference < hypothesized difference",
            "Difference ≠ hypothesized difference",
            "Difference > hypothesized difference",
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
        grid.addWidget(self.alt_combo, 2, 1)

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
        clamp_dialog_to_screen(self, max(460, needed_w + 185), 290, min_w=420, min_h=250)

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

        try:
            h = float(self.hyp_edit.text().strip())
            self.options["hypothesized_difference"] = h
        except ValueError:
            self.error.setText("Hypothesized difference must be a valid number.")
            return

        idx = self.alt_combo.currentIndex()
        if idx == 0:
            self.options["alternative"] = "less_than"
        elif idx == 2:
            self.options["alternative"] = "greater_than"
        else:
            self.options["alternative"] = "not_equal"

        self.accept()


class PairedTGraphsDialog(QDialog):
    """Graphs child dialog matching PAIREDTGRAPHS.MDF."""

    def __init__(self, graphs: Dict[str, bool], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Paired t: Graphs")
        self.setModal(True)
        self.graphs = dict(graphs)
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent or self)))
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)

        self.hist_cb = QCheckBox("&Histogram of differences")
        self.hist_cb.setChecked(bool(self.graphs.get("histogram", True)))
        layout.addWidget(self.hist_cb)

        self.ivp_cb = QCheckBox("&Individual value plot of differences")
        self.ivp_cb.setChecked(bool(self.graphs.get("individual_value_plot", True)))
        layout.addWidget(self.ivp_cb)

        self.box_cb = QCheckBox("&Boxplot of differences")
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


class PairedTDialog(QDialog):
    """Main Paired t dialog matching PAIREDT.MDF (MenuID 41324)."""

    def __init__(self, worksheet: Optional[Worksheet] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Paired t for the Mean")
        self.worksheet = worksheet
        self.active_edit: Optional[QLineEdit] = None
        self.result_payload: Optional[Dict[str, Any]] = None

        self.settings = paired_t_settings()
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
            "Each sample is in a column",
            "Summarized data (differences)",
        ])
        self.combo_data.currentIndexChanged.connect(self._on_data_format_changed)
        right_box.addWidget(self.combo_data)

        # Stacked pages
        self.stack = QStackedWidget()

        # Page 0: Unstacked (Sample 1 and Sample 2)
        page_unstacked = QWidget()
        unstack_layout = QGridLayout(page_unstacked)

        unstack_layout.addWidget(QLabel("Sample 1:"), 0, 0)
        self.sample1_edit = QLineEdit()
        self.sample1_edit.installEventFilter(self)
        unstack_layout.addWidget(self.sample1_edit, 0, 1)

        unstack_layout.addWidget(QLabel("Sample 2:"), 1, 0)
        self.sample2_edit = QLineEdit()
        self.sample2_edit.installEventFilter(self)
        unstack_layout.addWidget(self.sample2_edit, 1, 1)

        self.stack.addWidget(page_unstacked)

        # Page 1: Summarized (Differences)
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

        self.diff_cue = QLabel("Difference = mean of (Sample 1 − Sample 2)")
        self.diff_cue.setStyleSheet(subtle_label_style(is_dark_active(self.parent() or self), bold=True, font_size="8.5pt"))
        right_box.addWidget(self.diff_cue)

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
        buttons.helpRequested.connect(lambda: _show_context_help(self, "Paired t", "Select two paired numeric columns or enter summarized differences."))
        right_box.addWidget(buttons)

        main_layout.addLayout(right_box, 2)

        self.active_edit = self.sample1_edit

    def eventFilter(self, obj, event):
        if event.type() == event.Type.FocusIn and isinstance(obj, QLineEdit):
            self.active_edit = obj
        return super().eventFilter(obj, event)

    def _on_data_format_changed(self, index: int):
        self.stack.setCurrentIndex(index)
        # Graphs button is disabled when summarized data is selected
        is_raw = index == 0
        self.graphs_btn.setEnabled(is_raw)
        self.var_filter.setEnabled(is_raw)
        self.var_list.setEnabled(is_raw)
        self.select_btn.setEnabled(is_raw)
        if is_raw:
            self.active_edit = self.sample1_edit
        else:
            self.active_edit = self.size_edit

    def _on_var_double_clicked(self, item):
        self._insert_var_text(item.text().split()[0])

    def _on_select_clicked(self):
        item = self.var_list.currentItem()
        if item:
            self._insert_var_text(item.text().split()[0])

    def _insert_var_text(self, var_id: str):
        if self.active_edit:
            self.active_edit.setText(var_id)
            if self.active_edit == self.sample1_edit:
                self.sample2_edit.setFocus()

    def _on_options(self):
        dlg = PairedTOptionsDialog(self.settings, self)
        if dlg.exec():
            self.settings.update(dlg.options)

    def _on_graphs(self):
        dlg = PairedTGraphsDialog(self.settings["graphs"], self)
        if dlg.exec():
            self.settings["graphs"] = dlg.graphs

    def _on_ok(self):
        self.error.clear()
        idx = self.combo_data.currentIndex()
        if idx == 0:  # Each sample is in a column
            s1_text = self.sample1_edit.text().strip()
            s2_text = self.sample2_edit.text().strip()
            if not s1_text or not s2_text:
                self.error.setText("Please specify both Sample 1 and Sample 2 columns.")
                return

            if self.worksheet is not None:
                try:
                    c1s = resolve_variables(s1_text, self.worksheet, kinds=("number",))
                    c2s = resolve_variables(s2_text, self.worksheet, kinds=("number",))
                except ValueError as exc:
                    self.error.setText(str(exc))
                    return
                if len(c1s) != 1 or len(c2s) != 1:
                    self.error.setText("Specify one numeric column each for Sample 1 and Sample 2.")
                    return
                col1, col2 = c1s[0], c2s[0]
            else:
                def parse_col(txt):
                    if txt.upper().startswith("C") and txt[1:].isdigit():
                        return int(txt[1:]) - 1
                    return txt

                col1 = parse_col(s1_text)
                col2 = parse_col(s2_text)
            if col1 == col2:
                self.error.setText("Sample 1 and Sample 2 must be different columns.")
                return

            self.settings["data_format"] = 1
            self.settings["sample1_col"] = col1
            self.settings["sample2_col"] = col2
        else:  # Summarized data
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
            self.settings["graphs"] = {"histogram": False, "individual_value_plot": False, "boxplot": False}

        self.result_payload = dict(self.settings)
        self.accept()

    def get_state(self) -> dict:
        import copy
        return {
            "data_idx": self.combo_data.currentIndex(),
            "sample1": self.sample1_edit.text(),
            "sample2": self.sample2_edit.text(),
            "size": self.size_edit.text(),
            "mean": self.mean_edit.text(),
            "sd": self.sd_edit.text(),
            "settings": copy.deepcopy(self.settings),
        }

    def set_state(self, state: dict) -> None:
        import copy
        if not isinstance(state, dict):
            return
        if "data_idx" in state:
            self.combo_data.setCurrentIndex(int(state["data_idx"]))
        for attr, key in (("sample1_edit", "sample1"), ("sample2_edit", "sample2"), ("size_edit", "size"), ("mean_edit", "mean"), ("sd_edit", "sd")):
            if key in state:
                getattr(self, attr).setText(str(state[key]))
        if isinstance(state.get("settings"), dict):
            self.settings.update(copy.deepcopy(state["settings"]))
