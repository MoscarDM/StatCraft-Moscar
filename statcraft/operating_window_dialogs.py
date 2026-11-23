"""Dialogs for 3D Operating Window analysis and Confirmation Experiments."""
import math
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from .model_plots import discover_models
from .optimizer import _merge_predictors
from .operating_window import operating_window_settings


def _fmt_num(val):
    if val is None:
        return ''
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return format(float(val), '.6g')
    return str(val)


def _footer(dialog, layout, callback):
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(callback)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return buttons


def _parse_optional_float(text):
    clean = (text or '').strip()
    if not clean:
        return None
    val = float(clean)
    if not math.isfinite(val):
        raise ValueError('Numeric bounds and drift tolerances must be finite.')
    return val


class OperatingWindowDialog(QDialog):
    """Configure multi-response 3D Operating Window, factor drifts, and design region options."""

    def __init__(self, window, family=None):
        super().__init__(window)
        self.window = window
        self.family = family
        self.worksheet = window.presenter.worksheet
        self.entry = None
        self.models = discover_models(self.worksheet, window.presenter.history, family=None, require_two_continuous=True)
        self._merged_predictors = []

        self.setWindowTitle('3D Operating Window')
        self.resize(760, 560)
        layout = QVBoxLayout(self)

        # 1. Response specifications table
        resp_box = QGroupBox('Response Specification Bounds')
        resp_layout = QVBoxLayout(resp_box)
        self.resp_table = QTableWidget(len(self.models), 6)
        self.resp_table.setHorizontalHeaderLabels(['Use', 'Response', 'Lower (LSL)', 'Upper (USL)', 'Target', 'Goal'])
        self.resp_table.verticalHeader().setVisible(False)
        self.resp_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._resp_rows = []

        for r_i, item in enumerate(self.models):
            bnd = item['bundle']
            obs_min = float(bnd['observed_min'])
            obs_max = float(bnd['observed_max'])
            mid = 0.5 * (obs_min + obs_max)

            use_chk = QCheckBox()
            use_chk.setChecked(r_i < 2)
            use_chk.toggled.connect(self._rebuild_predictors)
            self.resp_table.setCellWidget(r_i, 0, use_chk)

            name_it = QTableWidgetItem(f"{item['response_name']} ({item['model_title']})")
            name_it.setFlags(name_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.resp_table.setItem(r_i, 1, name_it)

            lo_default = _fmt_num(obs_min)
            hi_default = '' if r_i == 0 else _fmt_num(obs_max)
            self.resp_table.setItem(r_i, 2, QTableWidgetItem(lo_default))
            self.resp_table.setItem(r_i, 3, QTableWidgetItem(hi_default))
            self.resp_table.setItem(r_i, 4, QTableWidgetItem(_fmt_num(obs_max if r_i == 0 else mid)))

            goal_cb = QComboBox()
            for label, val in (('Maximize', 'maximize'), ('Target', 'target'), ('Minimize', 'minimize')):
                goal_cb.addItem(label, val)
            if r_i > 0:
                goal_cb.setCurrentIndex(1)
            self.resp_table.setCellWidget(r_i, 5, goal_cb)

            self._resp_rows.append(dict(model=item, use_chk=use_chk, goal_cb=goal_cb))

        resp_layout.addWidget(self.resp_table)
        layout.addWidget(resp_box)

        # 2. Axis & grid options
        axes_box = QGroupBox('Surface Axes & Evaluation Settings')
        axes_form = QFormLayout(axes_box)
        row_axes = QHBoxLayout()
        self.x_combo = QComboBox()
        self.y_combo = QComboBox()
        self.primary_combo = QComboBox()
        row_axes.addWidget(QLabel('X Axis:'))
        row_axes.addWidget(self.x_combo, 1)
        row_axes.addWidget(QLabel('Y Axis:'))
        row_axes.addWidget(self.y_combo, 1)
        axes_form.addRow(row_axes)

        row_opts = QHBoxLayout()
        self.grid_spin = QSpinBox()
        self.grid_spin.setRange(5, 45)
        self.grid_spin.setValue(21)
        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(50.1, 99.8)
        self.conf_spin.setDecimals(1)
        self.conf_spin.setValue(95.0)
        self.design_region_chk = QCheckBox('Stay within convex design hull')
        self.design_region_chk.setChecked(True)
        row_opts.addWidget(QLabel('Z Surface:'))
        row_opts.addWidget(self.primary_combo, 1)
        row_opts.addWidget(QLabel('Grid N:'))
        row_opts.addWidget(self.grid_spin)
        row_opts.addWidget(QLabel('Conf (%):'))
        row_opts.addWidget(self.conf_spin)
        row_opts.addWidget(self.design_region_chk)
        axes_form.addRow(row_opts)
        layout.addWidget(axes_box)

        # 3. Drift tolerances & hold values
        drift_box = QGroupBox('Factor Drift Tolerances (±) & Hold Values')
        drift_layout = QVBoxLayout(drift_box)
        self.pred_table = QTableWidget(0, 4)
        self.pred_table.setHorizontalHeaderLabels(['Predictor', 'Role / Range', 'Hold Value', 'Drift (±)'])
        self.pred_table.verticalHeader().setVisible(False)
        self.pred_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        drift_layout.addWidget(self.pred_table)
        layout.addWidget(drift_box)

        self.error = QLabel('')
        self.error.setStyleSheet('color: #be123c;')
        layout.addWidget(self.error)
        _footer(self, layout, self.validate)

        self.x_combo.currentIndexChanged.connect(self._sync_pred_rows_enabled)
        self.y_combo.currentIndexChanged.connect(self._sync_pred_rows_enabled)
        self._rebuild_predictors()
        if not self.models:
            self.error.setText('Fit at least one model with 2+ continuous predictors before launching 3D Operating Window.')

    def set_response_spec(self, row, included=True, lower='', upper='', target='', goal=None):
        """Programmatically configure one response row."""
        rec = self._resp_rows[row]
        rec['use_chk'].setChecked(bool(included))
        self.resp_table.item(row, 2).setText('' if lower is None else str(lower))
        self.resp_table.item(row, 3).setText('' if upper is None else str(upper))
        self.resp_table.item(row, 4).setText('' if target is None else str(target))
        if goal is not None:
            idx = rec['goal_cb'].findData(goal)
            if idx >= 0:
                rec['goal_cb'].setCurrentIndex(idx)

    def _active_items(self):
        return [r['model'] for r in self._resp_rows if r['use_chk'].isChecked()]

    def _rebuild_predictors(self):
        prev_x = self.x_combo.currentData()
        prev_y = self.y_combo.currentData()
        active = self._active_items()

        self.primary_combo.clear()
        for r_i, r_row in enumerate(self._resp_rows):
            if r_row['use_chk'].isChecked():
                self.primary_combo.addItem(r_row['model']['response_name'], r_i)

        self.x_combo.blockSignals(True)
        self.y_combo.blockSignals(True)
        self.x_combo.clear()
        self.y_combo.clear()
        self.pred_table.setRowCount(0)
        self._merged_predictors = []

        if active:
            try:
                merged = _merge_predictors([m['bundle'] for m in active], {'constraints': [], 'starting_values': []})
                self._merged_predictors = merged
                cont = [p for p in merged if p['role'] == 'covariate']
                for p in cont:
                    self.x_combo.addItem(p['name'], p['index'])
                    self.y_combo.addItem(p['name'], p['index'])
                if prev_x is not None and self.x_combo.findData(prev_x) >= 0:
                    self.x_combo.setCurrentIndex(self.x_combo.findData(prev_x))
                if prev_y is not None and self.y_combo.findData(prev_y) >= 0:
                    self.y_combo.setCurrentIndex(self.y_combo.findData(prev_y))
                elif self.y_combo.count() >= 2:
                    self.y_combo.setCurrentIndex(1)

                self.pred_table.setRowCount(len(merged))
                for p_i, p in enumerate(merged):
                    name_it = QTableWidgetItem(p['name'])
                    name_it.setFlags(name_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.pred_table.setItem(p_i, 0, name_it)

                    if p['role'] == 'factor':
                        rng_txt = f"Factor ({', '.join(map(str, p['levels']))})"
                        hold_default = str(p['levels'][0])
                    else:
                        rng_txt = f"[{_fmt_num(p['observed_min'])}, {_fmt_num(p['observed_max'])}]"
                        hold_default = _fmt_num(0.5 * (float(p['observed_min']) + float(p['observed_max'])))
                    rng_it = QTableWidgetItem(rng_txt)
                    rng_it.setFlags(rng_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.pred_table.setItem(p_i, 1, rng_it)
                    self.pred_table.setItem(p_i, 2, QTableWidgetItem(hold_default))
                    self.pred_table.setItem(p_i, 3, QTableWidgetItem('0' if p['role'] == 'covariate' else ''))
                self.error.clear()
            except ValueError as exc:
                self.error.setText(str(exc))

        self.x_combo.blockSignals(False)
        self.y_combo.blockSignals(False)
        self._sync_pred_rows_enabled()

    def _sync_pred_rows_enabled(self):
        x_idx = self.x_combo.currentData()
        y_idx = self.y_combo.currentData()
        for p_i, p in enumerate(self._merged_predictors):
            hold_it = self.pred_table.item(p_i, 2)
            drift_it = self.pred_table.item(p_i, 3)
            if hold_it is not None:
                if p['index'] in (x_idx, y_idx):
                    hold_it.setFlags(hold_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    hold_it.setFlags(hold_it.flags() | Qt.ItemFlag.ItemIsEditable)
            if drift_it is not None:
                if p['role'] == 'factor':
                    drift_it.setFlags(drift_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    drift_it.setFlags(drift_it.flags() | Qt.ItemFlag.ItemIsEditable)

    def validate(self):
        try:
            specs = []
            active_row_map = []
            for r_i, row_rec in enumerate(self._resp_rows):
                if not row_rec['use_chk'].isChecked():
                    continue
                lo = _parse_optional_float(self.resp_table.item(r_i, 2).text())
                hi = _parse_optional_float(self.resp_table.item(r_i, 3).text())
                tgt = _parse_optional_float(self.resp_table.item(r_i, 4).text())
                goal = row_rec['goal_cb'].currentData()
                specs.append(dict(
                    model_recipe=row_rec['model']['recipe'],
                    lower=lo,
                    upper=hi,
                    target=tgt,
                    goal=goal,
                ))
                active_row_map.append(r_i)
            if not specs:
                raise ValueError('Select at least one fitted response model.')

            x_idx = self.x_combo.currentData()
            y_idx = self.y_combo.currentData()
            if x_idx is None or y_idx is None or x_idx == y_idx:
                raise ValueError('Select two distinct continuous predictors for X Axis and Y Axis.')

            prim_orig_row = self.primary_combo.currentData()
            prim_pos = active_row_map.index(prim_orig_row) if prim_orig_row in active_row_map else 0

            drifts = []
            holds = []
            for p_i, p in enumerate(self._merged_predictors):
                idx = p['index']
                if p['role'] == 'covariate':
                    d_val = _parse_optional_float(self.pred_table.item(p_i, 3).text())
                    if d_val is not None and d_val > 0.0:
                        drifts.append({'index': idx, 'delta': d_val})
                if idx not in (x_idx, y_idx):
                    h_txt = (self.pred_table.item(p_i, 2).text() or '').strip()
                    if h_txt:
                        h_val = h_txt if p['role'] == 'factor' else float(h_txt)
                        holds.append({'index': idx, 'value': h_val})

            opts = operating_window_settings(dict(
                grid_size=int(self.grid_spin.value()),
                confidence=float(self.conf_spin.value()) / 100.0,
                primary_response_index=prim_pos,
                drifts=drifts,
                holds=holds,
                design_region_only=self.design_region_chk.isChecked(),
            ))
            entry = self.window.presenter.operating_window_3d(specs, x_idx, y_idx, options=opts)
            self.entry = entry
            self.window.refresh()
            self.window.show_result(entry)
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class OperatingWindowSensitivityDialog(QDialog):
    def __init__(self, window, baseline):
        super().__init__(window)
        self.window = window
        self.baseline = baseline
        self.entry = None
        self.setWindowTitle('Operating Window Sensitivity')
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.factor = QComboBox(self)
        self.drift = QLineEdit(self)
        self.baseline_drift = QLabel(self)
        for predictor in baseline['result']['predictors']:
            if predictor['role'] != 'factor':
                self.factor.addItem(predictor['name'], predictor)
        form.addRow('Factor:', self.factor)
        form.addRow('Baseline drift (±):', self.baseline_drift)
        form.addRow('Scenario drift (±):', self.drift)
        layout.addLayout(form)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        _footer(self, layout, self.validate)
        self.factor.currentIndexChanged.connect(self._update_drift)
        self._update_drift()

    def _update_drift(self):
        factor = self.factor.currentData()
        if factor is not None:
            value = str(factor['drift_delta'])
            self.baseline_drift.setText(value)
            self.drift.setText(value)

    def validate(self):
        try:
            factor = self.factor.currentData()
            if factor is None:
                raise ValueError('The baseline has no numeric factor to vary.')
            drift = _parse_optional_float(self.drift.text())
            if drift is None:
                raise ValueError('Enter a scenario drift tolerance.')
            self.entry = self.window.presenter.operating_window_sensitivity(self.baseline, factor['index'], drift)
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as exc:
            self.error.setText(str(exc))
            return
        self.window.refresh()
        self.window.show_result(self.entry, target_tab='Report')
        self.accept()


class ConfirmationPlanDialog(QDialog):
    """Create a randomized replicated confirmation run sheet from a 3D Operating Window."""

    def __init__(self, window, operating_window_entry=None):
        super().__init__(window)
        self.window = window
        self.entry = None
        self.plan_entry = None
        self.ow_entries = [
            e for e in window.presenter.history
            if isinstance(e, dict)
            and not e.get('source_unavailable')
            and e.get('result', {}).get('analysis') == 'operating_window_3d'
        ]

        self.setWindowTitle('Create Confirmation Run Sheet')
        self.resize(480, 340)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.ow_combo = QComboBox()
        for idx, item in enumerate(self.ow_entries):
            self.ow_combo.addItem(item.get('title', f'Operating Window {idx + 1}'), idx)
        if operating_window_entry is not None:
            for idx, item in enumerate(self.ow_entries):
                if item is operating_window_entry or item.get('entry_id') == operating_window_entry.get('entry_id'):
                    self.ow_combo.setCurrentIndex(idx)
                    break
        elif self.ow_combo.count() > 0:
            self.ow_combo.setCurrentIndex(self.ow_combo.count() - 1)
        form.addRow('Operating Window:', self.ow_combo)

        self.chk_robust = QCheckBox('Robust Setting (drift-maximized)')
        self.chk_robust.setChecked(True)
        self.chk_optimum = QCheckBox('Predicted Optimum (nominal peak)')
        self.chk_optimum.setChecked(False)
        self.chk_selected = QCheckBox('Selected Setting')
        self.chk_selected.setChecked(False)
        settings_box = QVBoxLayout()
        settings_box.addWidget(self.chk_robust)
        settings_box.addWidget(self.chk_optimum)
        settings_box.addWidget(self.chk_selected)
        form.addRow('Candidate Settings:', settings_box)

        self.rep_spin = QSpinBox()
        self.rep_spin.setRange(1, 100)
        self.rep_spin.setValue(3)
        form.addRow('Replicates (m):', self.rep_spin)

        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(50.1, 99.8)
        self.conf_spin.setDecimals(1)
        self.conf_spin.setValue(95.0)
        form.addRow('Confidence (%):', self.conf_spin)

        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 999999)
        self.seed_spin.setValue(42)
        form.addRow('Random Seed:', self.seed_spin)

        self.sheet_edit = QLineEdit('Confirmation_Runs')
        form.addRow('Worksheet Name:', self.sheet_edit)

        layout.addLayout(form)
        self.error = QLabel('')
        self.error.setStyleSheet('color: #be123c;')
        layout.addWidget(self.error)
        _footer(self, layout, self.validate)

        if not self.ow_entries:
            self.error.setText('Run a 3D Operating Window analysis first.')

    def validate(self):
        try:
            if not self.ow_entries:
                raise ValueError('Run a 3D Operating Window analysis first.')
            ow_idx = self.ow_combo.currentData()
            ow_entry = self.ow_entries[ow_idx]
            ow_res = ow_entry['result']

            keys = []
            if self.chk_robust.isChecked():
                keys.append('robust_setting')
            if self.chk_optimum.isChecked():
                keys.append('predicted_optimum')
            if self.chk_selected.isChecked():
                keys.append('selected_setting')
            if not keys:
                raise ValueError('Select at least one candidate setting to confirm.')

            try:
                src_ws = self.window.presenter.result_worksheet(ow_entry)
            except ValueError:
                src_ws = self.window.presenter.worksheet

            plan_entry = self.window.presenter.create_confirmation_plan(
                ow_res,
                setting_keys=keys,
                replicates=int(self.rep_spin.value()),
                seed=int(self.seed_spin.value()),
                confidence=float(self.conf_spin.value()) / 100.0,
                sheet_name=self.sheet_edit.text().strip() or 'Confirmation_Runs',
                source_worksheet=src_ws,
            )
            self.entry = plan_entry
            self.plan_entry = plan_entry
            self.window.refresh()
            self.window.show_result(plan_entry)
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class ConfirmationEvaluateDialog(QDialog):
    """Evaluate observed confirmation measurements aligned strictly by RunID."""

    def __init__(self, window, plan_entry=None):
        super().__init__(window)
        self.window = window
        self.entry = None
        self.plan_entries = [
            e for e in window.presenter.history
            if isinstance(e, dict)
            and not e.get('source_unavailable')
            and e.get('result', {}).get('analysis') == 'confirmation_plan'
        ]

        self.setWindowTitle('Evaluate Confirmation Results')
        self.resize(520, 360)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.plan_combo = QComboBox()
        for idx, item in enumerate(self.plan_entries):
            self.plan_combo.addItem(item.get('title', f'Confirmation Plan {idx + 1}'), idx)
        if plan_entry is not None:
            for idx, item in enumerate(self.plan_entries):
                if item is plan_entry or item.get('entry_id') == plan_entry.get('entry_id'):
                    self.plan_combo.setCurrentIndex(idx)
                    break
        elif self.plan_combo.count() > 0:
            self.plan_combo.setCurrentIndex(self.plan_combo.count() - 1)
        form.addRow('Confirmation Plan:', self.plan_combo)

        self.ws_combo = QComboBox()
        sheets = (
            list(window.presenter.native_project.worksheets)
            if window.presenter.native_project is not None
            else [window.presenter.worksheet]
        )
        self._sheets = sheets
        active_idx = 0
        for idx, ws in enumerate(sheets):
            self.ws_combo.addItem(ws.name, idx)
            if ws is window.presenter.worksheet:
                active_idx = idx
        self.ws_combo.setCurrentIndex(active_idx)
        form.addRow('Measurement Worksheet:', self.ws_combo)
        layout.addLayout(form)

        map_box = QGroupBox('Response Measurement Columns')
        map_layout = QVBoxLayout(map_box)
        self.map_table = QTableWidget(0, 2)
        self.map_table.setHorizontalHeaderLabels(['Planned Response', 'Measured Column'])
        self.map_table.verticalHeader().setVisible(False)
        self.map_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        map_layout.addWidget(self.map_table)
        layout.addWidget(map_box)

        self.error = QLabel('')
        self.error.setStyleSheet('color: #be123c;')
        layout.addWidget(self.error)
        _footer(self, layout, self.validate)

        self.plan_combo.currentIndexChanged.connect(self._rebuild_mapping)
        self.ws_combo.currentIndexChanged.connect(self._rebuild_mapping)
        self._rebuild_mapping()
        if not self.plan_entries:
            self.error.setText('Create a Confirmation Run Sheet first.')

    def _rebuild_mapping(self):
        self.map_table.setRowCount(0)
        self._map_combos = []
        if not self.plan_entries or not self._sheets:
            return
        plan = self.plan_entries[self.plan_combo.currentData()]['result']
        ws = self._sheets[self.ws_combo.currentData()]
        num_cols = [(i, c) for i, c in enumerate(ws.columns) if c.kind == 'number']
        resps = plan.get('responses', [])
        self.map_table.setRowCount(len(resps))
        for r_i, resp in enumerate(resps):
            r_name = resp['response_name']
            it = QTableWidgetItem(r_name)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.map_table.setItem(r_i, 0, it)

            cb = QComboBox()
            best_idx = 0
            for c_pos, (col_idx, col) in enumerate(num_cols):
                cb.addItem(f'C{col_idx + 1}  {col.name}', col_idx)
                cname = col.name.strip().casefold()
                if cname in (r_name.strip().casefold(), f'{r_name.strip()}_obs'.casefold()):
                    best_idx = c_pos
            if num_cols:
                cb.setCurrentIndex(best_idx)
            self.map_table.setCellWidget(r_i, 1, cb)
            self._map_combos.append((r_name, cb))

    def validate(self):
        try:
            if not self.plan_entries:
                raise ValueError('Create a Confirmation Run Sheet first.')
            plan_entry = self.plan_entries[self.plan_combo.currentData()]
            ws_idx = self.ws_combo.currentData()
            if self.window.presenter.native_project is not None:
                self.window.presenter.select_worksheet(ws_idx)

            col_map = {}
            for r_name, cb in self._map_combos:
                col_idx = cb.currentData()
                if col_idx is None:
                    raise ValueError(f"Select a numeric measurement column for '{r_name}'.")
                col_map[r_name] = int(col_idx)

            entry = self.window.presenter.evaluate_confirmation_runs(plan_entry['result'], response_column_map=col_map)
            self.entry = entry
            self.window.refresh()
            self.window.show_result(entry)
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
