"""Traceability and batch workflow replay for standard Normal Process Capability."""
from __future__ import annotations

import copy
import math
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from .engine import normalize_numeric
from .imr_engine import parse_subgroup_omission


def _col_unit(col) -> str | None:
    return col.metadata.get('unit') or col.metadata.get('units')


def _normalize_capability_recipe(source, params: dict[str, Any]) -> dict[str, Any]:
    if 'settings' in params:
        settings = copy.deepcopy(params['settings'])
        settings.pop('_source_bindings', None)
        return settings
    idx = params['index']
    col = source.columns[idx]
    return {
        'single_column': True,
        'column_index': idx,
        'column_name': col.name,
        'subgroup_spec': 1,
        'lsl': params.get('lsl'),
        'usl': params.get('usl'),
        'target': params.get('target'),
        'options': {},
    }


def _find_col(sheet, col_ref, fallback_index=None):
    if isinstance(col_ref, int) and 0 <= col_ref < len(sheet.columns):
        return col_ref, sheet.columns[col_ref]
    for ci, col in enumerate(sheet.columns):
        if col.name == col_ref:
            return ci, col
    if fallback_index is not None and 0 <= fallback_index < len(sheet.columns):
        return fallback_index, sheet.columns[fallback_index]
    return None, None


def build_capability_trace(sheet, settings: dict[str, Any], result: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any]:
    """Build exact row, subgroup, missing, excluded, and out-of-spec provenance for Normal Capability."""
    single = bool(settings.get('single_column', True))
    excl_rows = sorted(parse_subgroup_omission(settings.get('exclude_rows')))
    excl_set = set(excl_rows)
    lsl = result.get('lsl')
    usl = result.get('usl')

    trace_rows: list[list[Any]] = []
    missing_rows: list[int] = []
    sub_col_name: str | None = None
    cols_across: list[str] = []
    sub_spec_val: Any = settings.get('subgroup_spec', 1)

    if single:
        _, col = _find_col(sheet, settings.get('column_name'), settings.get('column_index'))
        raw_vals = col.numeric_values(True) if col is not None else []
        sub_col = None
        if isinstance(sub_spec_val, str):
            try:
                sub_size = max(1, int(sub_spec_val))
            except ValueError:
                sub_size = 1
                _, sub_col = _find_col(sheet, sub_spec_val, settings.get('subgroup_col_index'))
                if sub_col is not None:
                    sub_col_name = sub_col.name
        elif sub_spec_val is None:
            sub_size = 1
        else:
            sub_size = max(1, int(sub_spec_val))

        if sub_col is not None:
            sg_id = 0
            current_id = None
            started = False
            for r, (v, g) in enumerate(zip(raw_vals, sub_col.values), 1):
                if r in excl_set:
                    continue
                if v is None or not math.isfinite(float(v)):
                    missing_rows.append(r)
                    continue
                fv = float(v)
                if not started or g != current_id:
                    sg_id += 1
                    current_id = g
                    started = True
                trace_rows.append([r, sg_id, fv, col.name])
        else:
            clean_idx = 0
            for r, v in enumerate(raw_vals, 1):
                if r in excl_set:
                    continue
                if v is None or not math.isfinite(float(v)):
                    missing_rows.append(r)
                    continue
                fv = float(v)
                sg_id = (clean_idx + 1) if sub_size <= 1 else ((clean_idx // sub_size) + 1)
                clean_idx += 1
                trace_rows.append([r, sg_id, fv, col.name])
    else:
        ca_indices = settings.get('cols_across_indices')
        cols = []
        if ca_indices:
            cols = [sheet.columns[i] for i in ca_indices if 0 <= i < len(sheet.columns)]
        else:
            for cn in settings.get('cols_across', []):
                _, c = _find_col(sheet, cn)
                if c is not None:
                    cols.append(c)
        cols_across = [c.name for c in cols]
        sub_spec_val = len(cols) or 1
        n_rows = max((len(c.values) for c in cols), default=0)
        sg_id = 0
        for r in range(n_rows):
            ws_row = r + 1
            if ws_row in excl_set:
                continue
            row_items: list[list[Any]] = []
            row_has_missing = False
            for c in cols:
                raw_v = c.values[r] if r < len(c.values) else None
                nv = normalize_numeric(raw_v)
                if nv is None or not math.isfinite(float(nv)):
                    row_has_missing = True
                else:
                    row_items.append([ws_row, 0, float(nv), c.name])
            if row_items:
                sg_id += 1
                for item in row_items:
                    item[1] = sg_id
                trace_rows.extend(row_items)
            if row_has_missing:
                missing_rows.append(ws_row)

    max_sg_size = max((len(g) for g in result.get('subgroups', [])), default=1)
    within_method = (
        opts.get('estimate_method_eq1', 'amr')
        if max_sg_size <= 1
        else opts.get('estimate_method_gt1', 'pooled')
    )

    oos_below_rows = [[item[0], item[2]] for item in trace_rows if lsl is not None and item[2] < lsl]
    oos_above_rows = [[item[0], item[2]] for item in trace_rows if usl is not None and item[2] > usl]

    return {
        'arrangement': 'single_column' if single else 'cols_across',
        'variable_name': result.get('variable_name', ''),
        'subgroup_spec': sub_spec_val,
        'subgroup_col_name': sub_col_name,
        'cols_across': cols_across,
        'rows': trace_rows,
        'excluded_rows': excl_rows,
        'missing_rows': sorted(missing_rows),
        'oos_below_rows': oos_below_rows,
        'oos_above_rows': oos_above_rows,
        'estimation': {
            'within_method': within_method,
            'unbiased_within': bool(opts.get('unbiased_within', True)),
            'unbiased_overall': bool(opts.get('unbiased_overall', False)),
            'moving_range_len': int(opts.get('moving_range_len', 2)),
            'historical_mean': settings.get('historical_mean'),
            'historical_stdev': settings.get('historical_stdev'),
            'lsl': lsl,
            'usl': usl,
            'target': result.get('target'),
            'tolerance_k': float(result.get('tolerance_k', 6.0)),
        },
    }


def capability_trace_summary(
    result: dict[str, Any],
    focus: str = 'overview',
    subgroup: int | None = None,
) -> dict[str, Any]:
    """Resolve saved Normal Capability statistics and observations to source worksheet provenance."""
    if not isinstance(result, dict) or result.get('analysis') != 'capability':
        raise ValueError('Select a saved Normal Capability analysis.')
    if result.get('analysis_mode', 'normal') != 'normal':
        raise ValueError('Traceability supports standard Normal Capability results.')
    if focus not in ('overview', 'oos', 'subgroup'):
        raise ValueError("Trace focus must be 'overview', 'oos', or 'subgroup'.")

    sg_count = int(result.get('subgroup_count', 0))
    if focus == 'subgroup':
        if type(subgroup) is not int or not 1 <= subgroup <= max(1, sg_count):
            raise ValueError(f'Subgroup number must be between 1 and {sg_count}.')

    trace = result.get('capability_trace')
    legacy_missing = not isinstance(trace, dict)
    all_rows = list(trace.get('rows', [])) if not legacy_missing else []
    excluded_rows = list(trace.get('excluded_rows', [])) if not legacy_missing else []
    missing_rows = list(trace.get('missing_rows', [])) if not legacy_missing else []
    oos_below = list(trace.get('oos_below_rows', [])) if not legacy_missing else []
    oos_above = list(trace.get('oos_above_rows', [])) if not legacy_missing else []
    estimation = dict(trace.get('estimation', {})) if not legacy_missing else {
        'within_method': '*',
        'unbiased_within': '*',
        'unbiased_overall': '*',
        'moving_range_len': '*',
        'lsl': result.get('lsl'),
        'usl': result.get('usl'),
        'target': result.get('target'),
        'tolerance_k': result.get('tolerance_k'),
    }

    if focus == 'oos':
        lsl = result.get('lsl')
        usl = result.get('usl')
        rows = [
            item for item in all_rows
            if (lsl is not None and item[2] < lsl) or (usl is not None and item[2] > usl)
        ]
    elif focus == 'subgroup':
        rows = [item for item in all_rows if int(item[1]) == subgroup]
    else:
        rows = all_rows

    within_perf = result.get('within_perf', {})
    overall_perf = result.get('overall_perf', {})
    return {
        'focus': focus,
        'subgroup': subgroup,
        'variable_name': result.get('variable_name', ''),
        'arrangement': trace.get('arrangement', 'unknown') if not legacy_missing else 'legacy',
        'subgroup_spec': trace.get('subgroup_spec') if not legacy_missing else None,
        'subgroup_col_name': trace.get('subgroup_col_name') if not legacy_missing else None,
        'cols_across': list(trace.get('cols_across', [])) if not legacy_missing else [],
        'sample_n': int(result.get('sample_n', 0)),
        'subgroup_count': sg_count,
        'mean': result.get('mean'),
        'stdev_within': result.get('stdev_within'),
        'stdev_overall': result.get('stdev_overall'),
        'cp': result.get('cp'),
        'cpk': result.get('cpk'),
        'pp': result.get('pp'),
        'ppk': result.get('ppk'),
        'obs_total': within_perf.get('observed_total'),
        'exp_within': within_perf.get('expected_total'),
        'exp_overall': overall_perf.get('expected_total'),
        'display_unit': result.get('display_unit', 'ppm'),
        'rows': rows,
        'all_rows_count': len(all_rows),
        'excluded_rows': excluded_rows,
        'missing_rows': missing_rows,
        'oos_below_rows': oos_below,
        'oos_above_rows': oos_above,
        'estimation': estimation,
        'legacy_trace_missing': legacy_missing,
    }


def _fmt_num(val) -> str:
    if val is None:
        return '*'
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return f'{val:.6g}'
    return str(val)


class CapabilityTraceDialog(QDialog):
    """Inspect source rows, omissions, OOS observations, and capability settings."""

    def __init__(self, parent, entry: dict[str, Any], stale):
        super().__init__(parent)
        self.setWindowTitle('Trace Capability Result')
        self.resize(660, 540)
        self.result = entry['result']
        sg_count = max(1, int(self.result.get('subgroup_count', 1)))

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Saved inputs from {entry.get('worksheet_name', 'worksheet')} · {self.result['variable_name']}"))
        if stale is True:
            layout.addWidget(QLabel('The current worksheet differs from the saved analysis.'))

        form = QFormLayout()
        self.focus = QComboBox()
        self.focus.addItem('Overview & Source Rows', 'overview')
        self.focus.addItem('Out-of-Spec Observations', 'oos')
        self.focus.addItem('By Subgroup', 'subgroup')
        self.subgroup = QSpinBox()
        self.subgroup.setRange(1, sg_count)
        self.subgroup.setEnabled(False)
        form.addRow('Trace view', self.focus)
        form.addRow('Subgroup', self.subgroup)
        layout.addLayout(form)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.focus.currentIndexChanged.connect(self._on_focus_changed)
        self.subgroup.valueChanged.connect(self.update_trace)
        self.update_trace()

    def _on_focus_changed(self):
        self.subgroup.setEnabled(self.focus.currentData() == 'subgroup')
        self.update_trace()

    def update_trace(self):
        focus = self.focus.currentData()
        sg = int(self.subgroup.value()) if focus == 'subgroup' else None
        info = capability_trace_summary(self.result, focus=focus, subgroup=sg)
        est = info['estimation']
        unit_lbl = '%' if str(info.get('display_unit', 'ppm')).lower() == 'percent' else 'PPM'
        lines = [
            f"Variable: {info['variable_name']} · Arrangement: {info['arrangement']}",
            f"Sample N: {info['sample_n']} · Subgroups: {info['subgroup_count']}",
            f"Mean: {_fmt_num(info['mean'])} · Within StDev: {_fmt_num(info['stdev_within'])} · Overall StDev: {_fmt_num(info['stdev_overall'])}",
            f"Cp={_fmt_num(info['cp'])} · Cpk={_fmt_num(info['cpk'])} · Pp={_fmt_num(info['pp'])} · Ppk={_fmt_num(info['ppk'])}",
            f"Defect rate ({unit_lbl}): Observed={_fmt_num(info['obs_total'])} · Exp Within={_fmt_num(info['exp_within'])} · Exp Overall={_fmt_num(info['exp_overall'])}",
            '',
            f"Specs: LSL={_fmt_num(est.get('lsl'))} · Target={_fmt_num(est.get('target'))} · USL={_fmt_num(est.get('usl'))} · Tolerance K={_fmt_num(est.get('tolerance_k'))}",
            f"Within estimator: {est.get('within_method')} · Unbiased within: {est.get('unbiased_within')} · Unbiased overall: {est.get('unbiased_overall')}",
            f"Excluded rows: {info['excluded_rows'] or 'None'} · Missing/non-numeric rows: {info['missing_rows'] or 'None'}",
            f"Out of spec: Below LSL={len(info['oos_below_rows'])} row(s), Above USL={len(info['oos_above_rows'])} row(s)",
        ]
        if info['legacy_trace_missing']:
            lines.extend(['', 'Row provenance unavailable for this legacy saved result; rerun on source worksheet to capture row links.'])
        elif info['rows']:
            lines.extend(['', f"Showing {len(info['rows'])} row(s):"])
            for ws_row, sg_id, val, col_name in info['rows']:
                flags = []
                if est.get('lsl') is not None and val < est['lsl']:
                    flags.append('< LSL')
                if est.get('usl') is not None and val > est['usl']:
                    flags.append('> USL')
                flag_txt = f" [{', '.join(flags)}]" if flags else ''
                lines.append(f"Row {ws_row} · SG {sg_id} · {col_name} = {val:g}{flag_txt}")
        else:
            lines.extend(['', 'No observations match the selected filter.'])
        self.details.setPlainText('\n'.join(lines))


def _capability_summary(entry: dict[str, Any]) -> dict[str, Any]:
    res = entry['result']
    scale = 10_000.0 if str(res.get('display_unit', 'ppm')).lower() == 'percent' else 1.0
    return {
        'entry_id': entry.get('entry_id'),
        'title': entry['title'],
        'worksheet': entry.get('worksheet_name', ''),
        'variable': res.get('variable_name', ''),
        'sample_n': int(res.get('sample_n', 0)),
        'subgroup_count': int(res.get('subgroup_count', 0)),
        'mean': float(res['mean']),
        'stdev_within': float(res['stdev_within']),
        'stdev_overall': float(res['stdev_overall']),
        'cp': res.get('cp'),
        'cpk': res.get('cpk'),
        'pp': res.get('pp'),
        'ppk': res.get('ppk'),
        'exp_overall_ppm': float(res['overall_perf']['expected_total']) * scale,
        'obs_total_ppm': float(res['within_perf']['observed_total']) * scale,
    }


def _validate_positive_opt(value, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f'{name} must be a positive finite number.')
    return float(value)


def _validate_nonneg_opt(value, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f'{name} must be a non-negative finite number.')
    return float(value)


def approve(
    presenter,
    entry: dict[str, Any],
    min_ppk: float | None = 1.33,
    min_cpk: float | None = None,
    max_ppm_total: float | None = None,
) -> dict[str, Any]:
    """Save an approved Normal Capability replay template on a fresh result."""
    if not isinstance(entry, dict) or entry.get('recipe', {}).get('action') != 'normal_capability':
        raise ValueError('Select a saved Normal Capability analysis.')
    res = entry.get('result', {})
    if res.get('analysis') != 'capability' or res.get('analysis_mode', 'normal') != 'normal':
        raise ValueError('Batch replay supports standard Normal Capability analyses.')
    if presenter.result_stale(entry) is not False:
        raise ValueError('Rerun the Normal Capability analysis before approving it as a baseline.')

    req_ppk = _validate_positive_opt(min_ppk, 'Minimum Ppk')
    req_cpk = _validate_positive_opt(min_cpk, 'Minimum Cpk')
    req_ppm = _validate_nonneg_opt(max_ppm_total, 'Maximum Expected PPM')
    if req_ppk is None and req_cpk is None and req_ppm is None:
        raise ValueError('Specify at least one acceptance criterion (Min Ppk, Min Cpk, or Max PPM).')

    source = presenter.result_worksheet(entry)
    settings = _normalize_capability_recipe(source, entry['recipe']['parameters'])
    single = bool(settings.get('single_column', True))

    has_subgroup_col = False
    subgroup_col_name = None
    cols_across: list[str] = []
    if single:
        _, col = _find_col(source, settings.get('column_name'), settings.get('column_index'))
        if col is None:
            raise ValueError('The saved capability measurement column is unavailable.')
        columns = [col.name]
        units = [_col_unit(col)]
        sub_spec = settings.get('subgroup_spec', 1)
        if isinstance(sub_spec, str):
            try:
                int(sub_spec)
            except ValueError:
                _, scol = _find_col(source, sub_spec, settings.get('subgroup_col_index'))
                subgroup_col_name = scol.name if scol is not None else sub_spec
                has_subgroup_col = True
    else:
        ca_indices = settings.get('cols_across_indices')
        cols = (
            [source.columns[i] for i in ca_indices]
            if ca_indices is not None
            else [_find_col(source, cn)[1] for cn in settings.get('cols_across', [])]
        )
        if not cols or any(c is None for c in cols):
            raise ValueError('The saved capability subgroup columns are unavailable.')
        cols_across = [c.name for c in cols]
        columns = list(cols_across)
        units = [_col_unit(c) for c in cols]

    # Preserve existing comparison when re-approving a replayed result.
    comparison = res.get('workflow_comparison')
    previous = res.get('workflow_replay')
    if comparison and previous:
        comparison.setdefault('baseline', copy.deepcopy(previous['baseline']))
        comparison.setdefault('criteria', copy.deepcopy(previous['criteria']))

    excl_rows = sorted(parse_subgroup_omission(settings.get('exclude_rows')))
    template = {
        'baseline': _capability_summary(entry),
        'single_column': single,
        'has_subgroup_col': has_subgroup_col,
        'subgroup_col_name': subgroup_col_name,
        'subgroup_spec': settings.get('subgroup_spec', 1),
        'columns': columns,
        'cols_across': cols_across,
        'units': units,
        'lsl': settings.get('lsl'),
        'usl': settings.get('usl'),
        'target': res.get('target'),
        'historical_mean': settings.get('historical_mean'),
        'historical_stdev': settings.get('historical_stdev'),
        'exclude_rows': excl_rows,
        'options': copy.deepcopy(settings.get('options', {})),
        'criteria': {
            'min_ppk': req_ppk,
            'min_cpk': req_cpk,
            'max_ppm_total': req_ppm,
        },
    }
    res['workflow_replay'] = template
    presenter._results_dirty = True
    return template


def preview(
    worksheet,
    template: dict[str, Any],
    column_index: int | None = None,
    subgroup_col_index: int | None = None,
    cols_across_indices: list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """Validate mapped batch columns, unit metadata, exclusions, and observation count before replay."""
    sheet = worksheet.worksheet if hasattr(worksheet, 'worksheet') else worksheet
    excl_rows = sorted(parse_subgroup_omission(template.get('exclude_rows')))
    excl_set = set(excl_rows)
    excluded_in_range = [r for r in excl_rows if 1 <= r <= sheet.row_count]
    excluded_out_of_range = [r for r in excl_rows if r > sheet.row_count]

    if template['single_column']:
        if type(column_index) is not int or not 0 <= column_index < len(sheet.columns):
            raise ValueError('Select a batch measurement column.')
        col = sheet.columns[column_index]
        if col.kind != 'number':
            raise ValueError('Choose a numeric measurement column.')
        unit = _col_unit(col)
        expected_unit = template['units'][0]
        if unit != expected_unit:
            raise ValueError(
                f"Batch unit {unit or '(unspecified)'} differs from baseline unit {expected_unit or '(unspecified)'}."
            )
        raw_vals = col.numeric_values(True)
        if template['has_subgroup_col']:
            if (
                type(subgroup_col_index) is not int
                or not 0 <= subgroup_col_index < len(sheet.columns)
                or subgroup_col_index == column_index
            ):
                raise ValueError('Select a distinct subgroup column for the batch.')
            sub_col = sheet.columns[subgroup_col_index]
            if len(sub_col.values) != len(raw_vals):
                raise ValueError('Batch subgroup column length must match measurement column length.')
            sg_desc = f"Subgroup column: {template['subgroup_col_name']} → C{subgroup_col_index + 1} {sub_col.name}"
        else:
            sg_desc = f"Subgroup size: {template.get('subgroup_spec', 1)}"

        valid_n = sum(
            1
            for r, v in enumerate(raw_vals, 1)
            if r not in excl_set and v is not None and math.isfinite(float(v))
        )
        mapped_columns = [f'C{column_index + 1} {col.name}']
        mapping_desc = f"{template['columns'][0]} → C{column_index + 1} {col.name}\n{sg_desc}"
        units_desc = unit or 'Unspecified'
    else:
        expected_cols = template['cols_across']
        if not cols_across_indices or len(cols_across_indices) != len(expected_cols):
            raise ValueError(f'Select {len(expected_cols)} numeric subgroup columns for this baseline.')
        if (
            len(set(cols_across_indices)) != len(cols_across_indices)
            or any(type(i) is not int or not 0 <= i < len(sheet.columns) for i in cols_across_indices)
        ):
            raise ValueError('Select distinct valid columns from the current worksheet.')
        mapped_lines = []
        mapped_columns = []
        unit_labels = []
        cols = []
        for base_name, expected_unit, idx in zip(expected_cols, template['units'], cols_across_indices):
            c = sheet.columns[idx]
            if c.kind != 'number':
                raise ValueError(f"Column '{c.name}' must be numeric.")
            unit = _col_unit(c)
            if unit != expected_unit:
                raise ValueError(
                    f"Batch unit {unit or '(unspecified)'} for {c.name} differs from baseline unit {expected_unit or '(unspecified)'}."
                )
            cols.append(c)
            mapped_columns.append(f'C{idx + 1} {c.name}')
            mapped_lines.append(f'{base_name} → C{idx + 1} {c.name}')
            unit_labels.append(unit or 'Unspecified')

        n_rows = max((len(c.values) for c in cols), default=0)
        valid_n = 0
        for r in range(n_rows):
            if (r + 1) in excl_set:
                continue
            for c in cols:
                nv = normalize_numeric(c.values[r] if r < len(c.values) else None)
                if nv is not None and math.isfinite(float(nv)):
                    valid_n += 1
        mapping_desc = 'Columns: ' + ', '.join(mapped_lines)
        units_desc = ', '.join(unit_labels)

    if valid_n < 2:
        raise ValueError('At least 2 valid non-excluded numeric observations are required to replay capability.')

    crit = template['criteria']
    crit_parts = []
    if crit.get('min_ppk') is not None:
        crit_parts.append(f"Ppk >= {crit['min_ppk']:g}")
    if crit.get('min_cpk') is not None:
        crit_parts.append(f"Cpk >= {crit['min_cpk']:g}")
    if crit.get('max_ppm_total') is not None:
        crit_parts.append(f"Expected PPM <= {crit['max_ppm_total']:g}")

    lines = [
        mapping_desc,
        f'Units: {units_desc} · Valid observations: {valid_n}',
        f"Specs: LSL={_fmt_num(template.get('lsl'))}, Target={_fmt_num(template.get('target'))}, USL={_fmt_num(template.get('usl'))}",
        f"Excluded rows: {excl_rows or 'None'}",
        f"Acceptance criteria: {'; '.join(crit_parts)}",
    ]
    if excluded_out_of_range:
        lines.append(
            f"Note: Saved excluded row(s) {excluded_out_of_range} exceed batch row count ({sheet.row_count})."
        )
    return {
        'ready': True,
        'valid_n': valid_n,
        'excluded_in_range': excluded_in_range,
        'excluded_out_of_range': excluded_out_of_range,
        'mapped_columns': mapped_columns,
        'units': units_desc,
        'preview_text': '\n'.join(lines),
    }


def _opt_delta(new_val: float | None, old_val: float | None) -> float | None:
    if new_val is None or old_val is None:
        return None
    return float(new_val) - float(old_val)


def replay(
    presenter,
    template: dict[str, Any],
    column_index: int | None = None,
    subgroup_col_index: int | None = None,
    cols_across_indices: list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """Replay an approved Normal Capability template on the current worksheet."""
    info = preview(
        presenter.worksheet,
        template,
        column_index=column_index,
        subgroup_col_index=subgroup_col_index,
        cols_across_indices=cols_across_indices,
    )
    sheet = presenter.worksheet
    opts = copy.deepcopy(template.get('options', {}))
    settings: dict[str, Any] = {
        'single_column': bool(template['single_column']),
        'lsl': template.get('lsl'),
        'usl': template.get('usl'),
        'target': template.get('target'),
        'historical_mean': template.get('historical_mean'),
        'historical_stdev': template.get('historical_stdev'),
        'exclude_rows': list(template.get('exclude_rows', [])),
        'options': opts,
        'analysis_mode': 'normal',
    }
    if template['single_column']:
        settings['column_name'] = sheet.columns[column_index].name  # type: ignore[index]
        settings['column_index'] = column_index
        if template['has_subgroup_col']:
            settings['subgroup_spec'] = sheet.columns[subgroup_col_index].name  # type: ignore[index]
            settings['subgroup_col_index'] = subgroup_col_index
        else:
            settings['subgroup_spec'] = template.get('subgroup_spec', 1)
    else:
        settings['cols_across'] = [sheet.columns[i].name for i in cols_across_indices]  # type: ignore[union-attr]
        settings['cols_across_indices'] = list(cols_across_indices)  # type: ignore[arg-type]

    entry = presenter.normal_capability(settings=settings)
    batch = _capability_summary(entry)
    baseline = copy.deepcopy(template['baseline'])
    crit = copy.deepcopy(template['criteria'])

    checks = {}
    all_pass = True
    if crit.get('min_ppk') is not None:
        ok = batch['ppk'] is not None and float(batch['ppk']) >= float(crit['min_ppk'])
        checks['min_ppk'] = ok
        all_pass = all_pass and ok
    if crit.get('min_cpk') is not None:
        ok = batch['cpk'] is not None and float(batch['cpk']) >= float(crit['min_cpk'])
        checks['min_cpk'] = ok
        all_pass = all_pass and ok
    if crit.get('max_ppm_total') is not None:
        ok = float(batch['exp_overall_ppm']) <= float(crit['max_ppm_total'])
        checks['max_ppm_total'] = ok
        all_pass = all_pass and ok

    deltas = {
        'mean': _opt_delta(batch['mean'], baseline['mean']),
        'stdev_within': _opt_delta(batch['stdev_within'], baseline['stdev_within']),
        'stdev_overall': _opt_delta(batch['stdev_overall'], baseline['stdev_overall']),
        'cpk': _opt_delta(batch['cpk'], baseline['cpk']),
        'ppk': _opt_delta(batch['ppk'], baseline['ppk']),
        'exp_overall_ppm': _opt_delta(batch['exp_overall_ppm'], baseline['exp_overall_ppm']),
    }

    entry['result']['workflow_replay'] = copy.deepcopy(template)
    entry['result']['workflow_comparison'] = {
        'mapping': info['preview_text'],
        'status': 'Pass' if all_pass else 'Fail',
        'criteria': crit,
        'criteria_results': checks,
        'baseline': baseline,
        'replay': batch,
        'deltas': deltas,
        'baseline_title': baseline.get('title', ''),
        'baseline_worksheet': baseline.get('worksheet', ''),
    }
    presenter._results_dirty = True
    return entry


def comparison_text(result: dict[str, Any]) -> str:
    """Format concise Normal Capability replay comparison block for Report & text export."""
    template = result.get('workflow_replay')
    comp = result.get('workflow_comparison')
    if not template or not comp or result.get('analysis') != 'capability':
        return ''
    baseline = comp.get('baseline', template['baseline'])
    batch = comp['replay']
    deltas = comp.get('deltas', {})

    def _row(label: str, key: str) -> str:
        b = _fmt_num(baseline.get(key))
        n = _fmt_num(batch.get(key))
        d = deltas.get(key)
        d_txt = f' ({d:+g})' if d is not None else ''
        return f'{label}: {b} -> {n}{d_txt}'

    lines = [
        'Workflow Replay (Normal Capability)',
        comp['mapping'],
        '',
        f"Approved baseline: {baseline['worksheet']} / {baseline['variable']}",
        f"Batch: {batch['worksheet']} / {batch['variable']} (N={baseline['sample_n']} -> {batch['sample_n']})",
        _row('Mean', 'mean'),
        _row('StDev (Within)', 'stdev_within'),
        _row('StDev (Overall)', 'stdev_overall'),
        _row('Cpk', 'cpk'),
        _row('Ppk', 'ppk'),
        _row('Expected Overall PPM', 'exp_overall_ppm'),
        f"Acceptance: {comp['status']}",
    ]
    return '\n'.join(lines)


class ApproveCapabilityReplayDialog(QDialog):
    """Configure capability acceptance thresholds before saving a replay baseline."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Approve Capability Replay Baseline')
        self.resize(440, 220)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.use_ppk = QCheckBox('Require Minimum Ppk')
        self.use_ppk.setChecked(True)
        self.min_ppk = QDoubleSpinBox()
        self.min_ppk.setRange(0.01, 20.0)
        self.min_ppk.setDecimals(2)
        self.min_ppk.setSingleStep(0.05)
        self.min_ppk.setValue(1.33)
        form.addRow(self.use_ppk, self.min_ppk)

        self.use_cpk = QCheckBox('Require Minimum Cpk')
        self.use_cpk.setChecked(False)
        self.min_cpk = QDoubleSpinBox()
        self.min_cpk.setRange(0.01, 20.0)
        self.min_cpk.setDecimals(2)
        self.min_cpk.setSingleStep(0.05)
        self.min_cpk.setValue(1.33)
        self.min_cpk.setEnabled(False)
        form.addRow(self.use_cpk, self.min_cpk)

        self.use_ppm = QCheckBox('Require Max Expected PPM')
        self.use_ppm.setChecked(False)
        self.max_ppm = QDoubleSpinBox()
        self.max_ppm.setRange(0.0, 1_000_000.0)
        self.max_ppm.setDecimals(1)
        self.max_ppm.setSingleStep(10.0)
        self.max_ppm.setValue(63.3)
        self.max_ppm.setEnabled(False)
        form.addRow(self.use_ppm, self.max_ppm)

        layout.addLayout(form)
        self.error = QLabel()
        self.error.setStyleSheet('color: #be123c;')
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.use_ppk.toggled.connect(self.min_ppk.setEnabled)
        self.use_cpk.toggled.connect(self.min_cpk.setEnabled)
        self.use_ppm.toggled.connect(self.max_ppm.setEnabled)

    def _accept_checked(self):
        if not (self.use_ppk.isChecked() or self.use_cpk.isChecked() or self.use_ppm.isChecked()):
            self.error.setText('Enable at least one acceptance threshold.')
            return
        self.accept()

    def thresholds(self) -> tuple[float | None, float | None, float | None]:
        return (
            float(self.min_ppk.value()) if self.use_ppk.isChecked() else None,
            float(self.min_cpk.value()) if self.use_cpk.isChecked() else None,
            float(self.max_ppm.value()) if self.use_ppm.isChecked() else None,
        )


class CapabilityReplayDialog(QDialog):
    """Map active worksheet columns onto an approved Normal Capability replay template."""

    def __init__(self, window, baseline_entry: dict[str, Any]):
        super().__init__(window)
        self.window = window
        self.template = baseline_entry['result']['workflow_replay']
        self.saved_entry = None
        self.setWindowTitle('Replay Capability on Current Worksheet')
        self.resize(540, 380)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        sheet = window.presenter.worksheet

        self.col_combo = None
        self.sub_combo = None
        self.across_combos: list[QComboBox] = []

        if self.template['single_column']:
            self.col_combo = QComboBox()
            for idx, col in enumerate(sheet.columns):
                if col.kind == 'number':
                    self.col_combo.addItem(f'C{idx + 1} {col.name}', idx)
                    if col.name == self.template['columns'][0]:
                        self.col_combo.setCurrentIndex(self.col_combo.count() - 1)
            form.addRow('Batch measurement', self.col_combo)
            if self.template['has_subgroup_col']:
                self.sub_combo = QComboBox()
                target_sub = self.template.get('subgroup_col_name') or ''
                selected_idx = self.col_combo.currentData()
                matched = False
                fallback_pos = None
                for idx, col in enumerate(sheet.columns):
                    self.sub_combo.addItem(f'C{idx + 1} {col.name}', idx)
                    pos = self.sub_combo.count() - 1
                    if col.name == target_sub:
                        self.sub_combo.setCurrentIndex(pos)
                        matched = True
                    elif idx != selected_idx:
                        if fallback_pos is None or (col.kind == 'text' and sheet.columns[self.sub_combo.itemData(fallback_pos)].kind != 'text'):
                            fallback_pos = pos
                if not matched and fallback_pos is not None:
                    self.sub_combo.setCurrentIndex(fallback_pos)
                form.addRow('Subgroup column', self.sub_combo)
        else:
            num_cols = [(idx, col) for idx, col in enumerate(sheet.columns) if col.kind == 'number']
            for pos, base_name in enumerate(self.template['cols_across']):
                combo = QComboBox()
                matched = False
                for idx, col in num_cols:
                    combo.addItem(f'C{idx + 1} {col.name}', idx)
                    if col.name == base_name:
                        combo.setCurrentIndex(combo.count() - 1)
                        matched = True
                if not matched and pos < combo.count():
                    combo.setCurrentIndex(pos)
                form.addRow(f'Column ({base_name})', combo)
                self.across_combos.append(combo)

        layout.addLayout(form)
        self.preview_label = QLabel()
        self.preview_label.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        self.error = QLabel()
        self.error.setStyleSheet('color: #be123c;')
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept_replay)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        if self.col_combo is not None:
            self.col_combo.currentIndexChanged.connect(self.update_preview)
        if self.sub_combo is not None:
            self.sub_combo.currentIndexChanged.connect(self.update_preview)
        for combo in self.across_combos:
            combo.currentIndexChanged.connect(self.update_preview)
        self.update_preview()

    def _selection_kwargs(self) -> dict[str, Any]:
        if self.template['single_column']:
            return {
                'column_index': self.col_combo.currentData() if self.col_combo else None,
                'subgroup_col_index': self.sub_combo.currentData() if self.sub_combo else None,
                'cols_across_indices': None,
            }
        return {
            'column_index': None,
            'subgroup_col_index': None,
            'cols_across_indices': [combo.currentData() for combo in self.across_combos if combo.currentData() is not None],
        }

    def update_preview(self):
        try:
            info = preview(self.window.presenter.worksheet, self.template, **self._selection_kwargs())
        except ValueError as exc:
            self.preview_label.clear()
            self.error.setText(str(exc))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        else:
            self.error.clear()
            self.preview_label.setText(info['preview_text'])
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def accept_replay(self):
        try:
            self.saved_entry = replay(self.window.presenter, self.template, **self._selection_kwargs())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()
