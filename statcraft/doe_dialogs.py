"""Original Qt dialogs guided by recovered RT_DIALOG3599/3692 and children."""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .dialog_theme import AutoErrorLabel, clamp_dialog_to_screen, dialog_stylesheet, is_dark_active
from .model import finite_number
from .variable_dialogs import ProcedureDialog, format_variable_list, resolve_variables


def buttons(dialog, layout, callback=None):
    row = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    row.accepted.connect(callback or dialog.accept)
    row.rejected.connect(dialog.reject)
    layout.addWidget(row)
    return row


_FAMILY_SPECS = (
    ("default_two_level", "2-level factorial (default generators) (2–15 factors)", 2, 15),
    ("custom_two_level", "2-level factorial (specify generators) (2–15 factors)", 2, 15),
    ("split_plot", "2-level split-plot (hard-to-change factors) (2–8 factors)", 2, 8),
    ("plackett_burman", "Plackett–Burman design (2–47 factors)", 2, 47),
    ("general_factorial", "General full factorial design (1–8 factors)", 1, 8),
)


class CreateFactorialDialog(QDialog):
    """Compact gated Create Factorial Design workflow across 5 DOE families."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Create Factorial Design")
        self.setMinimumWidth(680)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent)))

        self.parameters = None
        self.replicates = 1
        self.subplot_replicates = 1
        self.centers = 0
        self.blocks = 1
        self.hard_count = 1
        self.randomize = True
        self.seed = None
        self.store_in_worksheet = True
        self.summary = True
        self.result_level = "summary_alias"
        self.alias_order = 2
        self.generators = {}
        self.generators_confirmed = False
        self.pb_runs = None
        self.general_block_on_replicates = False
        self.catalog_parameters = {}
        self.default_runs_by_factor = {}
        self._design_confirmed = False
        self._confirmed_signature = None

        from .fractional import _FACTOR_LETTERS

        def _factor_id(i: int) -> str:
            return _FACTOR_LETTERS[i] if i < len(_FACTOR_LETTERS) else f"F{i + 1}"

        self.factors = [
            {"id": _factor_id(i), "name": _factor_id(i), "kind": "number", "low": -1.0, "high": 1.0}
            for i in range(47)
        ]
        self.hard_factors = [i == 0 for i in range(8)]
        self.general_factors = [
            {"id": _factor_id(i), "name": _factor_id(i), "kind": "number", "levels": [1.0, 2.0]}
            for i in range(8)
        ]

        layout = QVBoxLayout(self)
        body = QHBoxLayout()

        left = QVBoxLayout()
        group = QGroupBox("Type of Design")
        types = QVBoxLayout(group)
        self.design_types = []
        for idx, (_key, label, _min_k, _max_k) in enumerate(_FAMILY_SPECS):
            radio = QRadioButton(label)
            radio.setChecked(idx == 0)
            types.addWidget(radio)
            self.design_types.append(radio)
        left.addWidget(group)

        form = QFormLayout()
        self.factor_count = QComboBox()
        self.factor_count.addItems([str(i) for i in range(2, 16)])
        self.factor_count.setCurrentText("3")
        form.addRow("Number of factors:", self.factor_count)
        left.addLayout(form)
        left.addStretch(1)
        body.addLayout(left, 3)

        right = QVBoxLayout()
        self.available_btn = QPushButton("Display Available Designs…")
        self.available_btn.setAutoDefault(False)
        self.available_btn.clicked.connect(self.available)
        right.addWidget(self.available_btn)

        paired = QGridLayout()
        self.designs_btn = QPushButton("Designs…")
        self.factors_btn = QPushButton("Factors…")
        self.options_btn = QPushButton("Options…")
        self.results_btn = QPushButton("Results…")
        for btn, cb, r, c in (
            (self.designs_btn, self.designs, 0, 0),
            (self.factors_btn, self.factor_settings, 0, 1),
            (self.options_btn, self.options, 1, 0),
            (self.results_btn, self.results, 1, 1),
        ):
            btn.setAutoDefault(False)
            btn.clicked.connect(cb)
            paired.addWidget(btn, r, c)
        right.addLayout(paired)
        right.addStretch(1)
        body.addLayout(right, 2)
        layout.addLayout(body)

        self.step_prompt = QLabel()
        self.step_prompt.setObjectName("secondary")
        self.step_prompt.setWordWrap(True)
        layout.addWidget(self.step_prompt)

        self.error = AutoErrorLabel()
        layout.addWidget(self.error)

        self.button_box = buttons(self, layout, self.validate)
        self.ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)

        for radio in self.design_types:
            radio.toggled.connect(self._on_family_or_count_changed)
        self.factor_count.currentTextChanged.connect(self._on_factor_count_changed)
        self._sync_factor_count_range()
        self._sync_gated_buttons()

    def _family_index(self) -> int:
        for i, radio in enumerate(self.design_types):
            if radio.isChecked():
                return i
        return 0

    def family_key(self) -> str:
        return _FAMILY_SPECS[self._family_index()][0]

    def catalog_kind(self):
        if self.design_types[3].isChecked():
            return "plackett_burman"
        if self.design_types[4].isChecked():
            return "general_factorial"
        return None

    def is_split_plot(self):
        return self.design_types[2].isChecked()

    def _has_fractional_generators(self) -> bool:
        fam = self.family_key()
        k = int(self.factor_count.currentText() or "3")
        if fam == "custom_two_level":
            return bool(self.generators)
        if fam == "default_two_level":
            from .fractional import default_designs
            choices = default_designs(k)
            selected_runs = self.default_runs_by_factor.get(k, choices[0][0])
            gens = next((g for runs, _, g in choices if runs == selected_runs), None)
            return bool(gens)
        return False

    def _current_signature(self) -> tuple:
        return (self.family_key(), int(self.factor_count.currentText() or "3"))

    def _sync_factor_count_range(self):
        _key, _label, min_k, max_k = _FAMILY_SPECS[self._family_index()]
        prev_txt = self.factor_count.currentText() or "3"
        try:
            prev_k = int(prev_txt)
        except ValueError:
            prev_k = 3
        target_k = max(min_k, min(max_k, prev_k))
        self.factor_count.blockSignals(True)
        self.factor_count.clear()
        self.factor_count.addItems([str(i) for i in range(min_k, max_k + 1)])
        self.factor_count.setCurrentText(str(target_k))
        self.factor_count.blockSignals(False)

    def _on_family_or_count_changed(self):
        self._sync_factor_count_range()
        self._invalidate_if_incompatible()

    def _on_factor_count_changed(self, _txt: str):
        self._invalidate_if_incompatible()

    def _invalidate_if_incompatible(self):
        self.error.hide()
        if self._confirmed_signature != self._current_signature():
            self._design_confirmed = False
        self._sync_gated_buttons()

    def _sync_gated_buttons(self):
        ready = bool(self._design_confirmed and self._confirmed_signature == self._current_signature())
        self.factors_btn.setEnabled(ready)
        self.options_btn.setEnabled(ready)
        self.results_btn.setEnabled(ready)
        if self.ok_button is not None:
            self.ok_button.setEnabled(ready)
        if not ready:
            self.step_prompt.setText(
                "Next step: click Designs… to choose a design configuration and enable Factors, Options, Results, and OK."
            )
        else:
            k = int(self.factor_count.currentText())
            fam = self.family_key()
            if fam == "default_two_level":
                runs = self.default_runs_by_factor.get(k, 2**k)
                total = runs * self.replicates + self.centers * self.blocks
                desc = f"2-level factorial ({runs} base runs × {self.replicates} rep + {self.centers * self.blocks} center = {total} runs, {self.blocks} block(s))"
            elif fam == "custom_two_level":
                p = len(self.generators)
                runs = 2 ** max(2, k - p)
                total = runs * self.replicates + self.centers * self.blocks
                desc = f"2-level custom fraction ({runs} base runs = {total} total runs, {self.blocks} block(s))"
            elif fam == "split_plot":
                total = (2**k) * self.replicates * self.subplot_replicates
                desc = f"2-level split-plot ({self.hard_count} hard-to-change, {self.replicates} whole-plot × {self.subplot_replicates} subplot reps = {total} runs)"
            elif fam == "plackett_burman":
                from .doe_catalog_designs import PB_RUNS
                base = self.pb_runs or next(r for r in PB_RUNS if r > k)
                total = base * self.replicates + self.centers * self.blocks
                desc = f"Plackett–Burman ({base} base runs × {self.replicates} rep + {self.centers * self.blocks} center = {total} runs)"
            else:
                base = 1
                for gf in self.general_factors[:k]:
                    base *= max(2, len(gf["levels"]))
                total = base * self.replicates
                blks = self.replicates if self.general_block_on_replicates else 1
                desc = f"General full factorial ({base} base × {self.replicates} rep = {total} runs, {blks} block(s))"
            self.step_prompt.setText(f"Configured: {desc}. Factors, Options, Results, and OK are enabled.")

    def catalog_selection_changed(self):
        self._sync_factor_count_range()
        self._invalidate_if_incompatible()

    def available(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Display Available Designs")
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)
        fam = self.family_key()
        k = int(self.factor_count.currentText())

        if fam in ("default_two_level", "custom_two_level"):
            from .fractional import default_designs, resolution_roman
            rows = [
                (fc, runs, resolution_roman(res))
                for fc in range(2, 16)
                for runs, res, _ in sorted(default_designs(fc), key=lambda d: d[0])
            ]
            table = QTableWidget(len(rows), 3, dialog)
            table.setHorizontalHeaderLabels(["Factors", "Corner runs / rep", "Unblocked resolution"])
            for r_i, (fc, runs, res) in enumerate(rows):
                for c_i, val in enumerate((fc, runs, res)):
                    table.setItem(r_i, c_i, QTableWidgetItem(str(val)))
        elif fam == "plackett_burman":
            from .doe_catalog_designs import PB_RUNS
            pb_rows = [(n, n - 1) for n in PB_RUNS]
            table = QTableWidget(len(pb_rows), 2, dialog)
            table.setHorizontalHeaderLabels(["Base runs", "Max factors"])
            for r_i, (runs, max_f) in enumerate(pb_rows):
                table.setItem(r_i, 0, QTableWidgetItem(str(runs)))
                table.setItem(r_i, 1, QTableWidgetItem(str(max_f)))
        elif fam == "split_plot":
            sp_rows = [(h, k - h, 2**k) for h in range(1, k)]
            table = QTableWidget(len(sp_rows), 3, dialog)
            table.setHorizontalHeaderLabels(["Hard factors", "Easy factors", "Base runs"])
            for r_i, vals in enumerate(sp_rows):
                for c_i, val in enumerate(vals):
                    table.setItem(r_i, c_i, QTableWidgetItem(str(val)))
        else:
            table = QTableWidget(8, 2, dialog)
            table.setHorizontalHeaderLabels(["Factors", "Max total runs"])
            for r_i in range(8):
                table.setItem(r_i, 0, QTableWidgetItem(str(r_i + 1)))
                table.setItem(r_i, 1, QTableWidgetItem("4096"))

        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        buttons(dialog, layout)
        dialog.exec()

    def designs(self):
        fam = self.family_key()
        k = int(self.factor_count.currentText())
        if fam in ("default_two_level", "custom_two_level"):
            accepted = self._designs_two_level(k, custom=(fam == "custom_two_level"))
        elif fam == "split_plot":
            accepted = self._designs_split_plot(k)
        elif fam == "plackett_burman":
            accepted = self._designs_plackett_burman(k)
        else:
            accepted = self._designs_general_factorial(k)
        if accepted:
            self._design_confirmed = True
            self._confirmed_signature = self._current_signature()
            self.error.hide()
            self._sync_gated_buttons()

    def _designs_two_level(self, k: int, custom: bool = False) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Create Factorial Design: Designs")
        dialog.setMinimumWidth(520)
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        layout = QVBoxLayout(dialog)

        table = QTableWidget(1, 4, dialog)
        table.setHorizontalHeaderLabels(["Design", "Corner runs", "Unblocked resolution", "2^(k-p)"])
        from .fractional import default_designs, resolution_roman
        choices = sorted(default_designs(k), key=lambda d: d[0]) if not custom else []

        def refresh_custom_row():
            values = ("Full factorial", str(2**k), "Full", f"2^{k}")
            if self.generators:
                try:
                    from .fractional import alias_structure
                    structure = alias_structure(self.generators, k)
                    p = len(structure["generators"])
                    values = (
                        "Regular fraction",
                        str(2 ** (k - p)),
                        resolution_roman(structure["resolution"]),
                        f"2^({k}-{p})",
                    )
                except (ValueError, TypeError):
                    values = ("Specify generators", "—", "—", "—")
            for col, val in enumerate(values):
                table.setItem(0, col, QTableWidgetItem(val))

        if choices:
            table.setRowCount(len(choices))
            for row, (runs, resolution, gens) in enumerate(choices):
                p = len(gens)
                for col, val in enumerate((
                    "Regular fraction" if p else "Full factorial",
                    runs,
                    resolution_roman(resolution),
                    f"2^({k}-{p})" if p else f"2^{k}",
                )):
                    table.setItem(row, col, QTableWidgetItem(str(val)))
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            saved_runs = self.default_runs_by_factor.get(k)
            target_row = next((i for i, d in enumerate(choices) if d[0] == saved_runs), 0)
            table.setCurrentCell(target_row, 0)
        else:
            refresh_custom_row()
            table.selectRow(0)

        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMaximumHeight(170)
        layout.addWidget(table)

        if custom:
            gen_btn = QPushButton("Generators…")
            gen_btn.setAutoDefault(False)
            gen_btn.clicked.connect(lambda: (self.generator_settings(dialog), refresh_custom_row(), update_blocks()))
            layout.addWidget(gen_btn)

        form = QFormLayout()
        centers = QSpinBox()
        centers.setRange(0, 20)
        centers.setValue(self.centers)
        reps = QSpinBox()
        reps.setRange(1, 20)
        reps.setValue(self.replicates)
        block = QComboBox()
        total_lbl = QLabel()
        total_lbl.setObjectName("secondary")

        def update_total():
            r = reps.value()
            selected = choices[table.currentRow()] if choices else None
            base_runs = selected[0] if selected else 2**k
            if custom and self.generators:
                try:
                    from .fractional import alias_structure
                    p = len(alias_structure(self.generators, k)["generators"])
                    base_runs = 2 ** (k - p)
                except Exception:
                    pass
            b = int(block.currentText() or "1")
            tot = base_runs * r + centers.value() * b
            total_lbl.setText(f"Total runs in design: {tot} ({base_runs * r} corner + {centers.value() * b} center)")

        def update_blocks():
            r = reps.value()
            selected = choices[table.currentRow()] if choices else None
            corner_runs = (selected[0] if selected else 2**k) * r
            if custom and self.generators:
                try:
                    from .fractional import alias_structure
                    p = len(alias_structure(self.generators, k)["generators"])
                    corner_runs = (2 ** (k - p)) * r
                except Exception:
                    pass
            options = [1]
            if r > 1:
                for d in range(2, r + 1):
                    if r % d == 0 and d not in options:
                        options.append(d)
            for p2 in (() if selected and selected[2] else (2, 4, 8, 16, 32)):
                if not custom and corner_runs % p2 == 0 and (corner_runs // p2) >= 2 and p2 not in options:
                    options.append(p2)
            options.sort()
            cur = block.currentText()
            block.clear()
            for opt in options:
                block.addItem(str(opt))
            if cur in [str(o) for o in options]:
                block.setCurrentText(cur)
            elif str(self.blocks) in [str(o) for o in options]:
                block.setCurrentText(str(self.blocks))
            elif r > 1 and str(r) in [str(o) for o in options]:
                block.setCurrentText(str(r))
            else:
                block.setCurrentIndex(0)
            update_total()

        reps.valueChanged.connect(lambda _: update_blocks())
        centers.valueChanged.connect(lambda _: update_total())
        block.currentTextChanged.connect(lambda _: update_total())
        if choices:
            table.currentCellChanged.connect(lambda *_: update_blocks())
        update_blocks()
        form.addRow("Number of center points per block:", centers)
        form.addRow("Number of replicates for corner points:", reps)
        form.addRow("Number of blocks:", block)
        layout.addLayout(form)
        layout.addWidget(total_lbl)

        err = AutoErrorLabel()
        layout.addWidget(err)

        def accept_designs():
            err.hide()
            if centers.value() > 0 and any(f["kind"] == "text" for f in self.factors[:k]):
                err.setText("Center points require all factors to be Numeric.")
                err.show()
                return
            if custom:
                try:
                    from .fractional import alias_structure
                    alias_structure(self.generators, k)
                except (ValueError, TypeError) as exc:
                    err.setText(str(exc))
                    err.show()
                    return
            dialog.accept()

        buttons(dialog, layout, accept_designs)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.centers = centers.value()
            self.replicates = reps.value()
            self.blocks = int(block.currentText())
            if choices:
                self.default_runs_by_factor[k] = choices[table.currentRow()][0]
            if custom:
                self.generators_confirmed = True
            return True
        return False

    def _designs_split_plot(self, k: int) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Create Split-Plot Factorial Design: Designs")
        dialog.setMinimumWidth(460)
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        hard_spin = QSpinBox()
        hard_spin.setRange(1, max(1, min(6, k - 1)))
        hard_spin.setValue(max(1, min(k - 1, self.hard_count)))

        wp_spin = QSpinBox()
        wp_spin.setRange(1, 20)
        wp_spin.setValue(self.replicates)

        sp_spin = QSpinBox()
        sp_spin.setRange(1, 20)
        sp_spin.setValue(self.subplot_replicates)

        summary_lbl = QLabel()
        summary_lbl.setObjectName("secondary")
        summary_lbl.setWordWrap(True)

        def update_summary():
            h = hard_spin.value()
            e = k - h
            wp_count = (2**h) * wp_spin.value()
            sp_per_wp = (2**e) * sp_spin.value()
            tot = wp_count * sp_per_wp
            summary_lbl.setText(
                f"Whole plots: {wp_count} ({h} hard factor(s)) × {sp_per_wp} subplot runs/WP = {tot} total runs"
            )

        for sb in (hard_spin, wp_spin, sp_spin):
            sb.valueChanged.connect(lambda _: update_summary())
        update_summary()

        form.addRow("Number of hard-to-change factors:", hard_spin)
        form.addRow("Number of whole-plot replicates:", wp_spin)
        form.addRow("Number of subplot replicates:", sp_spin)
        layout.addLayout(form)
        layout.addWidget(summary_lbl)

        err = AutoErrorLabel()
        layout.addWidget(err)

        def accept_sp():
            tot = (2**k) * wp_spin.value() * sp_spin.value()
            if tot > 4096:
                err.setText("Split-plot design exceeds 4096-run limit.")
                err.show()
                return
            dialog.accept()

        buttons(dialog, layout, accept_sp)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.hard_count = hard_spin.value()
            self.replicates = wp_spin.value()
            self.subplot_replicates = sp_spin.value()
            self.centers = 0
            self.blocks = 1
            for i in range(k):
                self.hard_factors[i] = i < self.hard_count
            return True
        return False

    def _designs_plackett_burman(self, k: int) -> bool:
        from .doe_catalog_designs import PB_RUNS
        dialog = QDialog(self)
        dialog.setWindowTitle("Create Plackett–Burman Design: Designs")
        dialog.setMinimumWidth(460)
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        runs_combo = QComboBox()
        compatible = [r for r in PB_RUNS if r > k]
        for r in compatible:
            runs_combo.addItem(f"{r} runs", r)
        if self.pb_runs in compatible:
            runs_combo.setCurrentIndex(runs_combo.findData(self.pb_runs))

        reps = QSpinBox()
        reps.setRange(1, 20)
        reps.setValue(self.replicates)

        centers = QSpinBox()
        centers.setRange(0, 20)
        centers.setValue(self.centers)

        block = QComboBox()
        total_lbl = QLabel()
        total_lbl.setObjectName("secondary")

        def update_blocks():
            r = reps.value()
            opts = [1] if r == 1 else [1, r]
            cur = block.currentText()
            block.clear()
            for o in opts:
                block.addItem(str(o))
            block.setCurrentText(cur if cur in [str(o) for o in opts] else "1")
            update_total()

        def update_total():
            base = runs_combo.currentData() or compatible[0]
            b = int(block.currentText() or "1")
            tot = base * reps.value() + centers.value() * b
            total_lbl.setText(f"Total runs in design: {tot}")

        reps.valueChanged.connect(lambda _: update_blocks())
        centers.valueChanged.connect(lambda _: update_total())
        runs_combo.currentIndexChanged.connect(lambda _: update_total())
        block.currentTextChanged.connect(lambda _: update_total())
        update_blocks()

        form.addRow("Number of base runs:", runs_combo)
        form.addRow("Number of replicates:", reps)
        form.addRow("Number of center points per block:", centers)
        form.addRow("Number of blocks:", block)
        layout.addLayout(form)
        layout.addWidget(total_lbl)

        err = AutoErrorLabel()
        layout.addWidget(err)

        def accept_pb():
            if centers.value() > 0 and any(f["kind"] == "text" for f in self.factors[:k]):
                err.setText("Center points require all factors to be Numeric.")
                err.show()
                return
            base = runs_combo.currentData()
            b = int(block.currentText() or "1")
            if base * reps.value() + centers.value() * b > 4096:
                err.setText("Design exceeds 4096-run limit.")
                err.show()
                return
            dialog.accept()

        buttons(dialog, layout, accept_pb)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.pb_runs = int(runs_combo.currentData())
            self.replicates = reps.value()
            self.centers = centers.value()
            self.blocks = int(block.currentText())
            return True
        return False

    def _designs_general_factorial(self, k: int) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Create General Full Factorial Design: Designs")
        dialog.setMinimumWidth(480)
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        layout = QVBoxLayout(dialog)

        table = QTableWidget(k, 3, dialog)
        table.setHorizontalHeaderLabels(["Factor", "Name", "Number of levels"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        level_spins = []
        for i in range(k):
            gf = self.general_factors[i]
            id_item = QTableWidgetItem(gf["id"])
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(i, 0, id_item)
            table.setItem(i, 1, QTableWidgetItem(gf["name"]))
            sb = QSpinBox()
            sb.setRange(2, 20)
            sb.setValue(max(2, len(gf["levels"])))
            level_spins.append(sb)
            table.setCellWidget(i, 2, sb)
        layout.addWidget(table)

        form = QFormLayout()
        reps = QSpinBox()
        reps.setRange(1, 20)
        reps.setValue(self.replicates)
        block_rep = QCheckBox("Block on replicates")
        block_rep.setChecked(self.general_block_on_replicates)
        total_lbl = QLabel()
        total_lbl.setObjectName("secondary")

        def update_total():
            base = 1
            for sb in level_spins:
                base *= sb.value()
            tot = base * reps.value()
            blks = reps.value() if block_rep.isChecked() else 1
            total_lbl.setText(f"Total runs in design: {tot} ({blks} block(s))")

        for sb in level_spins:
            sb.valueChanged.connect(lambda _: update_total())
        reps.valueChanged.connect(lambda _: update_total())
        block_rep.toggled.connect(lambda _: update_total())
        update_total()

        form.addRow("Number of replicates:", reps)
        form.addRow("", block_rep)
        layout.addLayout(form)
        layout.addWidget(total_lbl)

        err = AutoErrorLabel()
        layout.addWidget(err)

        def accept_gf():
            names = [
                (table.item(i, 1).text() if table.item(i, 1) else "").strip()
                for i in range(k)
            ]
            if any(not n for n in names) or len({n.casefold() for n in names}) != k:
                err.setText("Factor names must be non-empty and unique.")
                err.show()
                return
            base = 1
            for sb in level_spins:
                base *= sb.value()
            if base * reps.value() > 4096:
                err.setText("Design exceeds 4096-run limit.")
                err.show()
                return
            dialog.accept()

        buttons(dialog, layout, accept_gf)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.replicates = reps.value()
            self.general_block_on_replicates = block_rep.isChecked()
            self.centers = 0
            self.blocks = self.replicates if self.general_block_on_replicates else 1
            for i in range(k):
                gf = self.general_factors[i]
                gf["name"] = table.item(i, 1).text().strip()
                target_n = level_spins[i].value()
                if len(gf["levels"]) != target_n:
                    if gf["kind"] == "text":
                        gf["levels"] = [f"Level {j + 1}" for j in range(target_n)]
                    else:
                        gf["levels"] = [float(j + 1) for j in range(target_n)]
            return True
        return False

    def generator_settings(self, parent=None):
        dialog = QDialog(parent or self)
        dialog.setWindowTitle("Create Factorial Design: Generators")
        dialog.setMinimumWidth(560)
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        layout = QVBoxLayout(dialog)
        k = int(self.factor_count.currentText())
        layout.addWidget(
            QLabel(
                "Enter products of base-factor letters, for example D = ABC.\n"
                "Leave base factors blank. Use a leading minus for the alternate fraction."
            )
        )
        table = QTableWidget(k, 3, dialog)
        self.generator_table = table
        table.setHorizontalHeaderLabels(["Factor", "Name", "Generator"])
        from .fractional import _FACTOR_LETTERS
        for row in range(k):
            letter = _FACTOR_LETTERS[row]
            for col, val in enumerate((letter, self.factors[row]["name"], self.generators.get(letter, ""))):
                item = QTableWidgetItem(val)
                if col < 2:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, col, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        error = AutoErrorLabel()
        layout.addWidget(error)

        def accept():
            dialog.setFocus()
            QApplication.processEvents()
            try:
                values = {
                    _FACTOR_LETTERS[r]: table.item(r, 2).text().strip()
                    for r in range(k)
                    if table.item(r, 2).text().strip()
                }
                from .fractional import alias_structure
                structure = alias_structure(values, k)
            except (ValueError, TypeError) as exc:
                error.setText(str(exc))
                return
            self.generators = structure["generators"]
            dialog.accept()

        buttons(dialog, layout, accept)
        dialog.exec()

    def factor_settings(self):
        fam = self.family_key()
        k = int(self.factor_count.currentText())
        if fam == "general_factorial":
            self._factors_general(k)
            return
        split_plot = self.is_split_plot()
        dialog = QDialog(self)
        dialog.setWindowTitle("Create Factorial Design: Factors")
        dialog.setMinimumWidth(680)
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        layout = QVBoxLayout(dialog)

        headers = ["Factor", "Name", "Type", "Low", "High"]
        if split_plot:
            headers.append("Hard to change")
        table = QTableWidget(k, len(headers), dialog)
        self.factor_table = table
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)

        for row in range(k):
            f = self.factors[row]
            id_item = QTableWidgetItem(f["id"])
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, id_item)
            table.setItem(row, 1, QTableWidgetItem(f["name"]))

            type_combo = QComboBox()
            type_combo.addItem("Numeric", "number")
            type_combo.addItem("Text", "text")
            type_combo.setCurrentIndex(type_combo.findData(f.get("kind", "number")))
            table.setCellWidget(row, 2, type_combo)

            low_item = QTableWidgetItem(str(f["low"]))
            high_item = QTableWidgetItem(str(f["high"]))
            table.setItem(row, 3, low_item)
            table.setItem(row, 4, high_item)

            def _on_type_changed(_idx, r=row, tc=type_combo):
                if tc.currentData() == "text":
                    li = table.item(r, 3)
                    hi = table.item(r, 4)
                    if li and li.text().strip() in ("-1", "-1.0"):
                        li.setText("Low")
                    if hi and hi.text().strip() in ("1", "1.0"):
                        hi.setText("High")
                else:
                    li = table.item(r, 3)
                    hi = table.item(r, 4)
                    if li and li.text().strip() == "Low":
                        li.setText("-1")
                    if hi and hi.text().strip() == "High":
                        hi.setText("1")

            type_combo.currentIndexChanged.connect(_on_type_changed)

            if split_plot:
                hc = QComboBox()
                hc.addItems(["Yes (Whole-Plot)", "No (Subplot)"])
                hc.setCurrentIndex(0 if self.hard_factors[row] else 1)
                table.setCellWidget(row, 5, hc)

        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        error = AutoErrorLabel()
        layout.addWidget(error)

        def accept():
            dialog.setFocus()
            QApplication.processEvents()
            try:
                updated = []
                for r in range(k):
                    name = table.item(r, 1).text().strip()
                    kind = table.cellWidget(r, 2).currentData()
                    raw_l = table.item(r, 3).text().strip()
                    raw_h = table.item(r, 4).text().strip()
                    if kind == "text":
                        if not raw_l or not raw_h or raw_l == raw_h:
                            raise ValueError(f"Text factor '{name}' requires two distinct non-empty levels.")
                        updated.append({"id": self.factors[r]["id"], "name": name, "kind": "text", "low": raw_l, "high": raw_h})
                    else:
                        low_v = finite_number(float(raw_l))
                        high_v = finite_number(float(raw_h))
                        updated.append({"id": self.factors[r]["id"], "name": name, "kind": "number", "low": low_v, "high": high_v})
                if self.centers > 0 and any(u["kind"] == "text" for u in updated):
                    raise ValueError(
                        "Center points require all factors to be Numeric. Set center points to 0 in Designs… or keep Numeric factors."
                    )
                if split_plot:
                    hard_flags = [table.cellWidget(r, 5).currentIndex() == 0 for r in range(k)]
                    hard = [f for f, flag in zip(updated, hard_flags) if flag]
                    easy = [f for f, flag in zip(updated, hard_flags) if not flag]
                    from .doe_split_plot import create_split_plot_design
                    create_split_plot_design(
                        hard, easy, replicates=self.replicates, subplot_replicates=self.subplot_replicates,
                        seed=self.seed, randomize=False,
                    )
                elif fam == "plackett_burman":
                    from .doe_catalog_designs import create_design
                    pb_f = [{"name": u["name"], "kind": u["kind"], "levels": [u["low"], u["high"]]} for u in updated]
                    create_design("plackett_burman", pb_f, replicates=self.replicates, centers=self.centers,
                                  blocks=self.blocks, randomize=False, seed=self.seed or 1,
                                  options={"runs": self.pb_runs} if self.pb_runs else {})
                else:
                    from .doe import create_factorial
                    create_factorial(updated[: min(len(updated), 8)], centers=min(1, self.centers) if all(u["kind"] == "number" for u in updated) else 0, randomize=False)
            except (ValueError, TypeError) as exc:
                error.setText(str(exc))
                return
            self.factors[:k] = updated
            if split_plot:
                self.hard_factors[:k] = [table.cellWidget(r, 5).currentIndex() == 0 for r in range(k)]
                self.hard_count = sum(1 for fl in self.hard_factors[:k] if fl)
            dialog.accept()

        buttons(dialog, layout, accept)
        dialog.exec()

    def _factors_general(self, k: int):
        dialog = QDialog(self)
        dialog.setWindowTitle("Create General Full Factorial Design: Factors")
        dialog.setMinimumWidth(640)
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        layout = QVBoxLayout(dialog)

        table = QTableWidget(k, 4, dialog)
        self.factor_table = table
        table.setHorizontalHeaderLabels(["Factor", "Name", "Type", "Levels (comma-separated)"])
        table.verticalHeader().setVisible(False)
        for row in range(k):
            gf = self.general_factors[row]
            id_item = QTableWidgetItem(gf["id"])
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, id_item)
            table.setItem(row, 1, QTableWidgetItem(gf["name"]))
            tc = QComboBox()
            tc.addItem("Numeric", "number")
            tc.addItem("Text", "text")
            tc.setCurrentIndex(tc.findData(gf["kind"]))
            table.setCellWidget(row, 2, tc)
            table.setItem(row, 3, QTableWidgetItem(", ".join(str(x) for x in gf["levels"])))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)

        error = AutoErrorLabel()
        layout.addWidget(error)

        def accept():
            dialog.setFocus()
            QApplication.processEvents()
            try:
                parsed = []
                for r in range(k):
                    name = table.item(r, 1).text().strip()
                    kind = table.cellWidget(r, 2).currentData()
                    raw_tokens = [tok.strip() for tok in table.item(r, 3).text().split(",") if tok.strip()]
                    if kind == "number":
                        levels = [finite_number(float(t)) for t in raw_tokens]
                    else:
                        levels = raw_tokens
                    parsed.append({
                        "id": self.general_factors[r]["id"],
                        "name": name,
                        "kind": kind,
                        "levels": levels,
                    })
                from .doe_catalog_designs import create_design
                create_design(
                    "general_factorial",
                    [{"name": p["name"], "kind": p["kind"], "levels": p["levels"]} for p in parsed],
                    replicates=self.replicates,
                    blocks=self.blocks,
                    randomize=False,
                    seed=self.seed or 1,
                )
            except (ValueError, TypeError) as exc:
                error.setText(str(exc))
                return
            self.general_factors[:k] = parsed
            dialog.accept()

        buttons(dialog, layout, accept)
        dialog.exec()

    def options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Create Factorial Design: Options")
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        layout = QVBoxLayout(dialog)

        randomize = QCheckBox("Randomize runs")
        randomize.setChecked(self.randomize)
        layout.addWidget(randomize)

        form = QFormLayout()
        seed = QLineEdit("" if self.seed is None else str(self.seed))
        seed.setMinimumWidth(200)
        seed.setPlaceholderText("Leave blank for automatic")
        form.addRow("Base for random data generator:", seed)
        layout.addLayout(form)

        store = QCheckBox("Store design in worksheet")
        store.setChecked(self.store_in_worksheet)
        layout.addWidget(store)

        error = AutoErrorLabel()
        layout.addWidget(error)

        def accept():
            txt = seed.text().strip()
            if txt == "":
                val = None
            else:
                try:
                    val = int(txt)
                    if not -(2**63) <= val < 2**63:
                        raise ValueError("Seed is outside the supported range.")
                except ValueError as exc:
                    error.setText(str(exc))
                    return
            self.seed = val
            self.randomize = randomize.isChecked()
            self.store_in_worksheet = store.isChecked()
            dialog.accept()

        buttons(dialog, layout, accept)
        dialog.exec()

    def results(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Create Factorial Design: Results")
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        layout = QVBoxLayout(dialog)

        group = QGroupBox("Output Detail")
        grp_layout = QVBoxLayout(group)
        choices = [
            ("none", "Do not display results"),
            ("summary", "Design summary table"),
            ("summary_alias", "Summary table + alias table"),
            ("full", "Summary table + alias table + design table"),
            ("full_defining", "Summary table + alias table + design table + defining relation"),
        ]
        radios = {}
        is_fractional_two = self._has_fractional_generators()
        for key, label in choices:
            rb = QRadioButton(label)
            rb.setChecked(self.result_level == key)
            if key == "full_defining":
                rb.setEnabled(is_fractional_two)
            grp_layout.addWidget(rb)
            radios[key] = rb
        if self.result_level == "full_defining" and not is_fractional_two:
            radios["full"].setChecked(True)
        layout.addWidget(group)

        alias_row = QHBoxLayout()
        alias_row.addWidget(QLabel("Maximum interaction order in alias table:"))
        order_combo = QComboBox()
        order_combo.addItems(["1", "2", "3"])
        order_combo.setCurrentText(str(self.alias_order))
        alias_row.addWidget(order_combo)
        alias_row.addStretch(1)
        layout.addLayout(alias_row)

        def _sync_alias_enabled():
            wants_alias = any(radios[k].isChecked() for k in ("summary_alias", "full", "full_defining"))
            order_combo.setEnabled(wants_alias and self.family_key() in ("default_two_level", "custom_two_level"))

        for rb in radios.values():
            rb.toggled.connect(_sync_alias_enabled)
        _sync_alias_enabled()

        buttons(dialog, layout)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.result_level = next(k for k, rb in radios.items() if rb.isChecked())
            self.summary = self.result_level != "none"
            self.alias_order = int(order_combo.currentText())

    def validate(self):
        self.error.hide()
        try:
            if not self._design_confirmed or self._confirmed_signature != self._current_signature():
                raise ValueError("Choose a design configuration in Designs… first.")
            fam = self.family_key()
            k = int(self.factor_count.currentText())
            seed_val = self.seed

            if fam == "general_factorial":
                gf_list = [
                    {"name": gf["name"], "kind": gf["kind"], "levels": list(gf["levels"])}
                    for gf in self.general_factors[:k]
                ]
                blks = self.replicates if self.general_block_on_replicates else 1
                params = {
                    "kind": "general_factorial",
                    "factors": gf_list,
                    "replicates": self.replicates,
                    "centers": 0,
                    "blocks": blks,
                    "randomize": self.randomize,
                    "seed": seed_val,
                    "options": {},
                    "name": "General factorial design",
                    "store_in_worksheet": self.store_in_worksheet,
                    "result_level": self.result_level,
                    "alias_order": self.alias_order,
                }
                from .doe_planner import build_plan
                build_plan(**params)
                self.parameters = params
                self.accept()
                return

            if fam == "plackett_burman":
                from .doe_catalog_designs import PB_RUNS
                base_runs = self.pb_runs or next(r for r in PB_RUNS if r > k)
                pb_factors = [
                    {"name": f["name"], "kind": f["kind"], "levels": [f["low"], f["high"]]}
                    for f in self.factors[:k]
                ]
                params = {
                    "kind": "plackett_burman",
                    "factors": pb_factors,
                    "replicates": self.replicates,
                    "centers": self.centers,
                    "blocks": self.blocks,
                    "randomize": self.randomize,
                    "seed": seed_val,
                    "options": {"runs": base_runs},
                    "name": "Plackett-Burman design",
                    "store_in_worksheet": self.store_in_worksheet,
                    "result_level": self.result_level,
                    "alias_order": self.alias_order,
                }
                from .doe_planner import build_plan
                build_plan(**params)
                self.parameters = params
                self.accept()
                return

            if fam == "split_plot":
                selected = [
                    {"name": f["name"], "kind": f["kind"], "low": f["low"], "high": f["high"]}
                    for f in self.factors[:k]
                ]
                flags = self.hard_factors[:k]
                hard = [dict(f) for f, fl in zip(selected, flags) if fl]
                easy = [dict(f) for f, fl in zip(selected, flags) if not fl]
                from .doe_split_plot import create_split_plot_design
                create_split_plot_design(
                    hard,
                    easy,
                    replicates=self.replicates,
                    subplot_replicates=self.subplot_replicates,
                    seed=seed_val,
                    randomize=self.randomize,
                )
                self.parameters = {
                    "hard_factors": hard,
                    "easy_factors": easy,
                    "replicates": self.replicates,
                    "subplot_replicates": self.subplot_replicates,
                    "seed": seed_val,
                    "randomize": self.randomize,
                    "store_in_worksheet": self.store_in_worksheet,
                    "result_level": self.result_level,
                }
                self.accept()
                return

            selected_factors = [
                {"name": f["name"], "kind": f["kind"], "low": f["low"], "high": f["high"]}
                for f in self.factors[:k]
            ]
            if self.centers > 0 and any(f["kind"] == "text" for f in selected_factors):
                raise ValueError("Center points require all factors to be Numeric.")
            params = {
                "factors": selected_factors,
                "replicates": self.replicates,
                "centers": self.centers,
                "blocks": self.blocks,
                "randomize": self.randomize,
                "seed": seed_val,
                "store_in_worksheet": self.store_in_worksheet,
                "result_level": self.result_level,
                "alias_order": self.alias_order,
            }
            if fam == "custom_two_level":
                generators = dict(self.generators)
            else:
                from .fractional import default_designs
                choices = default_designs(k)
                selected_runs = self.default_runs_by_factor.get(k, choices[0][0])
                generators = next(g for runs, _, g in choices if runs == selected_runs)
                if generators and self.replicates % self.blocks:
                    raise ValueError(
                        "For a default fraction, choose a block count that divides the number of replicates."
                    )
            if generators or fam == "custom_two_level":
                from .fractional import create_fractional
                params["generators"] = dict(generators)
                create_fractional(
                    selected_factors,
                    generators,
                    replicates=self.replicates,
                    centers=self.centers,
                    randomize=self.randomize,
                    seed=seed_val,
                    blocks=self.blocks,
                )
            else:
                from .doe import create_factorial
                create_factorial(
                    selected_factors,
                    replicates=self.replicates,
                    centers=self.centers,
                    randomize=self.randomize,
                    seed=seed_val,
                    blocks=self.blocks,
                )
            self.parameters = params
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.accept()


class AnalyzeFactorialDialog(QDialog):
    def __init__(self, parent, worksheet):
        super().__init__(parent)
        self.setWindowTitle("Analyze Factorial Design")
        self.setMinimumWidth(760)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(dialog_stylesheet(is_dark_active(parent)))
        self.worksheet = worksheet
        self.parameters = None
        self.max_order = 2
        self.confidence = 0.95
        self.selected_terms = None
        self.include_blocks = None
        doe_meta = worksheet.metadata.get("doe", {}) if isinstance(worksheet.metadata, dict) else {}
        if doe_meta.get("schema") == "statcraft-regular-fractional-v1":
            self.max_order = 1
        self.plot_residuals = True
        self.show_factor_coding = True
        factors = doe_meta.get("factors", [])
        self.factor_indices = [
            f["column_index"]
            for f in factors
            if isinstance(f, dict) and type(f.get("column_index")) is int
        ]
        layout = QVBoxLayout(self)
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.var_filter = QLineEdit()
        self.var_filter.setPlaceholderText("Filter variables…")
        self.var_filter.setClearButtonEnabled(True)
        self.var_filter.textChanged.connect(self._populate_available)
        left.addWidget(self.var_filter)
        self.available = QListWidget()
        self._populate_available()
        left.addWidget(self.available)
        select = QPushButton("Select")
        select.setAutoDefault(False)
        select.clicked.connect(self.transfer)
        self.available.itemDoubleClicked.connect(lambda item: self.transfer())
        left.addWidget(select)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Responses:"))
        self.response = QLineEdit()
        right.addWidget(self.response)
        grid = QGridLayout()
        for i, (title, callback) in enumerate((
            ("Terms…", self.terms),
            ("Covariates…", None),
            ("Options…", self.options),
            ("Stepwise…", None),
            ("Graphs…", self.graphs),
            ("Results…", self.results),
            ("Storage…", None),
        )):
            button = QPushButton(title)
            button.setAutoDefault(False)
            button.setEnabled(callback is not None)
            if callback:
                button.clicked.connect(callback)
            grid.addWidget(button, i // 4, i % 4)
        right.addLayout(grid)
        self.terms_note = QLabel()
        self.terms_note.setWordWrap(True)
        right.addWidget(self.terms_note)
        right.addStretch()
        body.addLayout(right, 2)
        layout.addLayout(body)
        self.update_terms_note()
        self.error = AutoErrorLabel()
        layout.addWidget(self.error)
        buttons(self, layout, self.validate)
        clamp_dialog_to_screen(self, 760, 440, min_w=640, min_h=380)

    def _populate_available(self):
        self.available.clear()
        needle = self.var_filter.text().strip().lower() if hasattr(self, "var_filter") else ""
        for i, column in enumerate(self.worksheet.columns):
            if column.kind != "number":
                continue
            if needle and needle not in column.name.lower() and needle not in f"c{i + 1}":
                continue
            item = QListWidgetItem("C" + str(i + 1) + "   " + column.name)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.available.addItem(item)

    def transfer(self):
        item = self.available.currentItem()
        if item:
            self.response.setText("C" + str(item.data(Qt.ItemDataRole.UserRole) + 1))
            self.response.setFocus()

    def update_terms_note(self):
        names = [
            self.worksheet.columns[i].name
            for i in self.factor_indices
            if 0 <= i < len(self.worksheet.columns)
        ]
        model = (
            ("Hierarchical terms through order " + str(self.max_order))
            if self.selected_terms is None
            else str(len(self.selected_terms)) + " selected model terms"
        )
        if self.include_blocks:
            model += " + Blocks"
        self.terms_note.setText("Factors: " + (", ".join(names) or "Select factors in Terms…") + "\n" + model)

    def terms(self):
        from .doe_terms_dialog import FactorialTermsDialog
        dialog = FactorialTermsDialog(
            self,
            self.worksheet,
            self.factor_indices,
            self.max_order,
            self.selected_terms,
            self.include_blocks,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.factor_indices = dialog.factor_indices
            self.max_order = dialog.max_order
            self.selected_terms = dialog.selected_terms
            self.include_blocks = dialog.include_blocks.isChecked()
            self.update_terms_note()

    def options(self):
        dialog = ProcedureDialog(
            self,
            "Analyze Factorial Design: Options",
            self.worksheet,
            [],
            [{"key": "confidence", "label": "Confidence level (0–1)", "numeric": True, "default": self.confidence}],
            "Coded-unit least squares with an intercept. No weighting, stepwise selection or Box-Cox transformation.",
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.confidence = dialog.parameters["confidence"]

    def graphs(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Analyze Factorial Design: Graphs")
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        dialog.setSizeGripEnabled(True)
        layout = QVBoxLayout(dialog)
        plot = QCheckBox("Residual plots")
        plot.setChecked(self.plot_residuals)
        layout.addWidget(plot)
        buttons(dialog, layout)
        clamp_dialog_to_screen(dialog, 360, 160, min_w=320, min_h=140)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.plot_residuals = plot.isChecked()

    def results(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Analyze Factorial Design: Results")
        dialog.setStyleSheet(dialog_stylesheet(is_dark_active(self)))
        dialog.setSizeGripEnabled(True)
        layout = QVBoxLayout(dialog)
        coding = QCheckBox("Factor coding table")
        coding.setChecked(self.show_factor_coding)
        layout.addWidget(coding)
        layout.addWidget(QLabel("Model summary, ANOVA, coefficients and effects are included."))
        buttons(dialog, layout)
        clamp_dialog_to_screen(dialog, 420, 180, min_w=360, min_h=150)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.show_factor_coding = coding.isChecked()

    def validate(self):
        try:
            responses = resolve_variables(self.response.text(), self.worksheet)
            if len(responses) != 1:
                raise ValueError("Select one response column.")
            parameters = dict(
                response_index=responses[0],
                factor_indices=self.factor_indices,
                max_order=self.max_order,
                confidence=self.confidence,
            )
            if self.include_blocks is not None:
                parameters["include_blocks"] = self.include_blocks
            if self.selected_terms is not None:
                parameters["selected_terms"] = self.selected_terms
            from .doe import analyze_factorial
            analyze_factorial(self.worksheet, **parameters)
            self.parameters = dict(
                **parameters,
                plot_residuals=self.plot_residuals,
                show_factor_coding=self.show_factor_coding,
            )
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
