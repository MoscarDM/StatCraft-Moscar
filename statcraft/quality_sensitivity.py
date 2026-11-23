"""Sensitivity branching for I-MR Control Charts and Normal Process Capability."""
from __future__ import annotations

import copy
import math
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .capability_nonnormal_engine import run_nonnormal_capability
from .imr_engine import parse_subgroup_omission, run_imr_chart
from .r_verification import _extract_subgroup_rows
from .subgroup_control import fit_subgroups


_DIST_CANDIDATES = ('weibull', 'lognormal', 'gamma', 'exponential', 'box_cox')
_DIST_LABELS = {
    'auto_best': 'Auto-select best fit (min AD)',
    'weibull': 'Weibull',
    'lognormal': 'Lognormal',
    'gamma': 'Gamma',
    'exponential': 'Exponential',
    'box_cox': 'Box-Cox Transformation',
}


def _parse_row_spec(spec: Any, max_rows: int) -> list[int]:
    if spec is None or spec == '' or spec == set() or spec == []:
        return []
    if isinstance(spec, (set, list, tuple)):
        rows: set[int] = set()
        for item in spec:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ValueError(f'Invalid row number: {item!r}')
            val = int(item)
            if val < 1 or val > max_rows:
                raise ValueError(f'Row {val} is outside worksheet range 1..{max_rows}.')
            rows.add(val)
        return sorted(rows)
    if not isinstance(spec, str):
        raise ValueError('Row specification must be text or a list of integers.')

    rows = set()
    tokens = spec.replace(',', ' ').split()
    for tok in tokens:
        sep = ':' if ':' in tok else ('-' if '-' in tok and not tok.startswith('-') else None)
        if sep is not None:
            parts = tok.split(sep)
            if len(parts) != 2:
                raise ValueError(f"Invalid row range '{tok}'.")
            try:
                start, end = int(parts[0]), int(parts[1])
            except ValueError as exc:
                raise ValueError(f"Invalid row range '{tok}'.") from exc
            if start < 1 or end < 1 or start > max_rows or end > max_rows:
                raise ValueError(f"Row range '{tok}' is outside 1..{max_rows}.")
            lo, hi = min(start, end), max(start, end)
            rows.update(range(lo, hi + 1))
        else:
            try:
                val = int(tok)
            except ValueError as exc:
                raise ValueError(f"Invalid row number '{tok}'.") from exc
            if val < 1 or val > max_rows:
                raise ValueError(f'Row {val} is outside worksheet range 1..{max_rows}.')
            rows.add(val)
    return sorted(rows)


def _cell_key(value: Any) -> str:
    return '<Missing>' if value is None or value == '' else str(value)


def _resolve_exclusion_rows(
    sheet,
    n_rows: int,
    batch_col_index: int | None = None,
    batch_values: list[str] | tuple[str, ...] | set[str] | None = None,
    exclude_rows_spec: Any = None,
) -> tuple[list[int], str]:
    rows: set[int] = set()
    parts: list[str] = []

    if batch_col_index is not None:
        if batch_col_index < 0 or batch_col_index >= len(sheet.columns):
            raise ValueError('Selected batch column is unavailable.')
        col = sheet.columns[batch_col_index]
        targets = {_cell_key(v) for v in (batch_values or [])}
        if targets:
            matched = [
                idx for idx in range(1, min(n_rows, len(col.values)) + 1)
                if _cell_key(col.values[idx - 1]) in targets
            ]
            if not matched:
                raise ValueError(f"No rows match selected {col.name} value(s).")
            rows.update(matched)
            parts.append(f"{col.name} in ({', '.join(sorted(targets))})")

    explicit = _parse_row_spec(exclude_rows_spec, n_rows)
    if explicit:
        rows.update(explicit)
        parts.append('rows ' + ', '.join(map(str, explicit[:6])) + ('…' if len(explicit) > 6 else ''))

    if not rows:
        raise ValueError('Select at least one flagged batch value or row range to exclude.')
    return sorted(rows), '; '.join(parts)


def _imr_signal_sets(result: dict[str, Any]) -> tuple[list[int], list[int]]:
    individual = result.get('test_failures') or {}
    i_rows = sorted({int(r) for r in individual.keys()} | {int(r) for r in result.get('i_signals', [])})
    mr_rows = sorted({int(r) for r in result.get('mr_signals', [])})
    return i_rows, mr_rows


def _imr_summary(result: dict[str, Any]) -> dict[str, Any]:
    i_rows, mr_rows = _imr_signal_sets(result)
    return {
        'count': int(result['count']),
        'i_center': float(result['i_center']),
        'within_stdev': float(result['within_stdev']),
        'i_lcl': result.get('i_lcl'),
        'i_ucl': result.get('i_ucl'),
        'mr_center': float(result['mr_center']),
        'mr_ucl': result.get('mr_ucl'),
        'i_signal_rows': i_rows,
        'mr_signal_rows': mr_rows,
        'i_signals': len(i_rows),
        'mr_signals': len(mr_rows),
        'total_signals': len(i_rows) + len(mr_rows),
        'in_control': (len(i_rows) + len(mr_rows)) == 0,
    }


def _run_on_source_worksheet(presenter, source_sheet, fn):
    previous = presenter.worksheet
    project = presenter.native_project
    previous_index = project.active_index if project else None
    try:
        presenter.worksheet = source_sheet
        if project is not None:
            project.active_index = next(i for i, sheet in enumerate(project.worksheets) if sheet is source_sheet)
        return fn()
    finally:
        presenter.worksheet = previous
        if project is not None and previous_index is not None:
            project.active_index = previous_index


def run_imr_sensitivity(
    presenter,
    baseline: dict[str, Any],
    mode: str,
    *,
    start_row: int | None = None,
    end_row: int | None = None,
    batch_col_index: int | None = None,
    batch_values: list[str] | tuple[str, ...] | set[str] | None = None,
    exclude_rows_spec: Any = None,
    treatment: str = 'exclude_rows',
) -> dict[str, Any]:
    """Branch a saved I-MR result by baseline period or flagged-batch/row exclusion."""
    if not isinstance(baseline, dict) or baseline.get('recipe', {}).get('action') != 'imr_chart':
        raise ValueError('Select a saved I-MR Chart as the sensitivity baseline.')
    if presenter.result_stale(baseline) is not False:
        raise ValueError('Rerun the baseline I-MR chart on its source worksheet first.')

    source = presenter.result_worksheet(baseline)
    orig_result = baseline['result']
    var_idx = baseline['recipe']['parameters']['settings']['variables'][0]
    col = source.columns[var_idx]
    n_rows = len(col.values)
    scenario_opts = copy.deepcopy(orig_result.get('options', {}))

    if mode == 'baseline_period':
        if not isinstance(start_row, int) or not isinstance(end_row, int) or isinstance(start_row, bool) or isinstance(end_row, bool):
            raise ValueError('Enter integer start and end row numbers for the baseline period.')
        if start_row < 1 or end_row > n_rows or start_row >= end_row:
            raise ValueError(f'Baseline period must satisfy 1 <= start < end <= {n_rows}.')
        period_opts = copy.deepcopy(scenario_opts)
        for key in ('historical_mean', 'historical_sigma', 'omit_subgroups', 'exclude_rows'):
            period_opts.pop(key, None)
        period_vals = col.values[start_row - 1 : end_row]
        period_res = run_imr_chart(period_vals, options=period_opts, variable_name=col.name)
        if period_res['within_stdev'] <= 0:
            raise ValueError('The selected baseline period has zero within-subgroup variation.')
        if (
            math.isclose(period_res['i_center'], orig_result['i_center'], rel_tol=1e-12, abs_tol=1e-12)
            and math.isclose(period_res['within_stdev'], orig_result['within_stdev'], rel_tol=1e-12, abs_tol=1e-12)
        ):
            raise ValueError('The selected baseline period produces the same center and sigma as the baseline.')
        scenario_opts['historical_mean'] = period_res['i_center']
        scenario_opts['historical_sigma'] = period_res['within_stdev']
        desc = (
            f"Baseline period rows {start_row}..{end_row} "
            f"(Mean={period_res['i_center']:.6g}, Sigma={period_res['within_stdev']:.6g})"
        )
        title = f"Sensitivity (Baseline {start_row}:{end_row}): I-MR of {col.name}"
        kind = 'imr_baseline_period'
        extra_params = {'start_row': start_row, 'end_row': end_row}
    elif mode == 'exclusion':
        if treatment not in ('exclude_rows', 'omit_estimation'):
            raise ValueError("Exclusion treatment must be 'exclude_rows' or 'omit_estimation'.")
        excl_rows, excl_desc = _resolve_exclusion_rows(
            source, n_rows, batch_col_index, batch_values, exclude_rows_spec,
        )
        if treatment == 'omit_estimation':
            existing = parse_subgroup_omission(scenario_opts.get('omit_subgroups', set()))
            merged = sorted(existing | set(excl_rows))
            if merged == sorted(existing):
                raise ValueError('Selected rows are already omitted from limit estimation.')
            scenario_opts['omit_subgroups'] = merged
            action_label = 'Omit from estimation'
        else:
            existing = parse_subgroup_omission(scenario_opts.get('exclude_rows', set()))
            merged = sorted(existing | set(excl_rows))
            if merged == sorted(existing):
                raise ValueError('Selected rows are already excluded.')
            scenario_opts['exclude_rows'] = merged
            action_label = 'Exclude rows'
        desc = f"{action_label}: {excl_desc}"
        title = f"Sensitivity ({excl_desc}): I-MR of {col.name}"
        kind = 'imr_exclusion'
        extra_params = {'treatment': treatment, 'rows': excl_rows, 'filter': excl_desc}
    else:
        raise ValueError(f'Unsupported I-MR sensitivity mode: {mode}')

    entry = _run_on_source_worksheet(
        presenter,
        source,
        lambda: presenter.imr_chart({'variables': [var_idx], 'options': scenario_opts}),
    )
    base_sum = _imr_summary(orig_result)
    scen_sum = _imr_summary(entry['result'])

    i_base, i_scen = set(base_sum['i_signal_rows']), set(scen_sum['i_signal_rows'])
    mr_base, mr_scen = set(base_sum['mr_signal_rows']), set(scen_sum['mr_signal_rows'])
    sigma_rel = abs(scen_sum['within_stdev'] - base_sum['within_stdev']) / max(abs(base_sum['within_stdev']), 1e-12)

    conclusions = [
        {
            'criterion': 'Overall Control Status',
            'baseline': 'In Control' if base_sum['in_control'] else f"Out of Control ({base_sum['total_signals']})",
            'scenario': 'In Control' if scen_sum['in_control'] else f"Out of Control ({scen_sum['total_signals']})",
            'status': 'Held' if base_sum['in_control'] == scen_sum['in_control'] else 'Changed',
        },
        {
            'criterion': 'Individuals Signal Rows',
            'baseline': ', '.join(map(str, base_sum['i_signal_rows'])) or 'None',
            'scenario': ', '.join(map(str, scen_sum['i_signal_rows'])) or 'None',
            'status': 'Held' if i_base == i_scen else 'Changed',
        },
        {
            'criterion': 'Moving Range Signal Rows',
            'baseline': ', '.join(map(str, base_sum['mr_signal_rows'])) or 'None',
            'scenario': ', '.join(map(str, scen_sum['mr_signal_rows'])) or 'None',
            'status': 'Held' if mr_base == mr_scen else 'Changed',
        },
        {
            'criterion': 'Within Sigma Stability (<=5%)',
            'baseline': f"{base_sum['within_stdev']:.6g}",
            'scenario': f"{scen_sum['within_stdev']:.6g} ({(scen_sum['within_stdev'] - base_sum['within_stdev']) / max(abs(base_sum['within_stdev']), 1e-12):+.1%})",
            'status': 'Held' if sigma_rel <= 0.05 else 'Changed',
        },
    ]

    entry['title'] = title
    entry['result']['title'] = title
    entry['result']['sensitivity'] = {
        'kind': kind,
        'baseline_title': baseline['title'],
        'baseline_id': baseline.get('entry_id'),
        'scenario_description': desc,
        'parameters': extra_params,
        'baseline_summary': base_sum,
        'scenario_summary': scen_sum,
        'signal_changes': {
            'i_held': sorted(i_base & i_scen),
            'i_added': sorted(i_scen - i_base),
            'i_cleared': sorted(i_base - i_scen),
            'mr_held': sorted(mr_base & mr_scen),
            'mr_added': sorted(mr_scen - mr_base),
            'mr_cleared': sorted(mr_base - mr_scen),
        },
        'conclusions': conclusions,
    }
    presenter._results_dirty = True
    return entry


def _subgroup_disp_label(chart_type: str) -> str:
    return 'Range' if chart_type in ('xbar_r', 'xbar', 'r') else 'StDev'


def _subgroup_signal_sets(result: dict[str, Any]) -> tuple[list[int], list[int]]:
    xbar_sgs = sorted({int(sg) for sg in (result.get('test_failures') or {}).keys()})
    disp_sgs = sorted({int(sg) for sg in (result.get('disp_signals') or [])})
    return xbar_sgs, disp_sgs


def _subgroup_summary(result: dict[str, Any]) -> dict[str, Any]:
    xbar_sgs, disp_sgs = _subgroup_signal_sets(result)
    disp_center = result.get('disp_center')
    return {
        'chart_type': result.get('chart_type', 'xbar_r'),
        'k_subgroups': int(result['k_subgroups']),
        'xbar_center': float(result['xbar_center']),
        'within_stdev': float(result['within_stdev']),
        'disp_center': float(disp_center) if disp_center is not None else None,
        'xbar_signal_subgroups': xbar_sgs,
        'disp_signal_subgroups': disp_sgs,
        'xbar_signals': len(xbar_sgs),
        'disp_signals': len(disp_sgs),
        'total_signals': len(xbar_sgs) + len(disp_sgs),
        'in_control': (len(xbar_sgs) + len(disp_sgs)) == 0,
    }


def _subgroup_period_values(
    source,
    params: dict[str, Any],
    orig_result: dict[str, Any],
    start_sg: int,
    end_sg: int,
) -> list[list[float | None]]:
    trace = orig_result.get('subgroup_trace') or []
    if len(trace) >= end_sg:
        return [
            [None if item[1] is None else float(item[1]) for item in sg_meta.get('rows', [])]
            for sg_meta in trace[start_sg - 1 : end_sg]
        ]
    extracted = _extract_subgroup_rows(source, params)
    return [
        [None if val is None else float(val) for _, val in items]
        for _, _, items in extracted[start_sg - 1 : end_sg]
    ]


def run_subgroup_sensitivity(
    presenter,
    baseline: dict[str, Any],
    mode: str,
    *,
    start_subgroup: int | None = None,
    end_subgroup: int | None = None,
    batch_col_index: int | None = None,
    batch_values: list[str] | tuple[str, ...] | set[str] | None = None,
    exclude_rows_spec: Any = None,
    exclude_subgroups_spec: Any = None,
    treatment: str = 'exclude_rows',
) -> dict[str, Any]:
    """Branch a saved Subgroup Control Chart (Xbar-R / Xbar-S) by baseline period or exclusion."""
    if not isinstance(baseline, dict) or baseline.get('recipe', {}).get('action') != 'subgroup_control_chart':
        raise ValueError('Select a saved Subgroup Control Chart as the sensitivity baseline.')
    if presenter.result_stale(baseline) is not False:
        raise ValueError('Rerun the baseline subgroup chart on its source worksheet first.')

    source = presenter.result_worksheet(baseline)
    orig_result = baseline['result']
    params = baseline['recipe']['parameters']
    chart_type = params.get('chart_type', orig_result.get('chart_type', 'xbar_r'))
    k_subgroups = int(orig_result.get('k_subgroups', 0))
    n_rows = source.row_count
    scenario_opts = copy.deepcopy(orig_result.get('options', {}))
    disp_label = _subgroup_disp_label(chart_type)

    if mode == 'baseline_period':
        if (
            not isinstance(start_subgroup, int)
            or not isinstance(end_subgroup, int)
            or isinstance(start_subgroup, bool)
            or isinstance(end_subgroup, bool)
        ):
            raise ValueError('Enter integer start and end subgroup numbers for the baseline period.')
        if start_subgroup < 1 or end_subgroup > k_subgroups or start_subgroup >= end_subgroup:
            raise ValueError(f'Baseline subgroup period must satisfy 1 <= start < end <= {k_subgroups}.')
        period_opts = copy.deepcopy(scenario_opts)
        for key in ('historical_mean', 'historical_sigma', 'omit_subgroups', 'exclude_rows'):
            period_opts.pop(key, None)
        period_groups = _subgroup_period_values(source, params, orig_result, start_subgroup, end_subgroup)
        period_res = fit_subgroups(period_groups, chart_type=chart_type, options=period_opts)
        if period_res['within_stdev'] <= 0:
            raise ValueError('The selected baseline subgroup period has zero within-subgroup variation.')
        if (
            math.isclose(period_res['xbar_center'], orig_result['xbar_center'], rel_tol=1e-12, abs_tol=1e-12)
            and math.isclose(period_res['within_stdev'], orig_result['within_stdev'], rel_tol=1e-12, abs_tol=1e-12)
        ):
            raise ValueError('The selected baseline subgroup period produces the same center and sigma as the baseline.')
        scenario_opts['historical_mean'] = period_res['xbar_center']
        scenario_opts['historical_sigma'] = period_res['within_stdev']
        desc = (
            f"Baseline subgroups {start_subgroup}..{end_subgroup} "
            f"(Xbar={period_res['xbar_center']:.6g}, Sigma={period_res['within_stdev']:.6g})"
        )
        title = f"Sensitivity (Baseline {start_subgroup}:{end_subgroup}): {orig_result['chart_type'].upper()} of {orig_result['variable_name']}"
        kind = 'subgroup_baseline_period'
        extra_params = {'start_subgroup': start_subgroup, 'end_subgroup': end_subgroup}
    elif mode == 'exclusion':
        if treatment not in ('exclude_rows', 'omit_estimation'):
            raise ValueError("Exclusion treatment must be 'exclude_rows' or 'omit_estimation'.")
        if treatment == 'omit_estimation':
            sg_targets: set[int] = set()
            desc_parts: list[str] = []
            if batch_col_index is not None and batch_values:
                matched_rows, batch_desc = _resolve_exclusion_rows(
                    source, n_rows, batch_col_index, batch_values, None,
                )
                matched_set = set(matched_rows)
                trace_list = orig_result.get('subgroup_trace') or []
                for sg_meta in trace_list:
                    sg_ws_rows = {int(item[0]) for item in sg_meta.get('rows', []) if item}
                    if sg_ws_rows & matched_set:
                        sg_targets.add(int(sg_meta['subgroup']))
                if not sg_targets:
                    raise ValueError('No subgroups match the selected flagged batch value(s).')
                desc_parts.append(batch_desc)
            if exclude_subgroups_spec not in (None, '', [], set()):
                explicit_sgs = _parse_row_spec(exclude_subgroups_spec, k_subgroups)
                sg_targets.update(explicit_sgs)
                desc_parts.append('subgroups ' + ', '.join(map(str, explicit_sgs[:6])) + ('…' if len(explicit_sgs) > 6 else ''))
            if exclude_rows_spec not in (None, '', [], set()):
                explicit_rows, rows_desc = _resolve_exclusion_rows(
                    source, n_rows, None, None, exclude_rows_spec,
                )
                explicit_row_set = set(explicit_rows)
                trace_list = orig_result.get('subgroup_trace') or []
                mapped = {
                    int(sg_meta['subgroup'])
                    for sg_meta in trace_list
                    if {int(item[0]) for item in sg_meta.get('rows', []) if item} & explicit_row_set
                }
                if not mapped:
                    raise ValueError('No subgroups correspond to the specified worksheet rows.')
                sg_targets.update(mapped)
                desc_parts.append(rows_desc)
            if not sg_targets:
                raise ValueError('Select at least one flagged batch value or subgroup index to omit.')
            existing = parse_subgroup_omission(scenario_opts.get('omit_subgroups', set()))
            merged = sorted(existing | sg_targets)
            if merged == sorted(existing):
                raise ValueError('Selected subgroups are already omitted from limit estimation.')
            scenario_opts['omit_subgroups'] = merged
            excl_desc = '; '.join(desc_parts)
            desc = f"Omit subgroups from estimation: {excl_desc}"
            extra_params = {'treatment': treatment, 'subgroups': sorted(sg_targets), 'filter': excl_desc}
        else:
            excl_rows, excl_desc = _resolve_exclusion_rows(
                source, n_rows, batch_col_index, batch_values, exclude_rows_spec,
            )
            existing = parse_subgroup_omission(scenario_opts.get('exclude_rows', set()))
            merged = sorted(existing | set(excl_rows))
            if merged == sorted(existing):
                raise ValueError('Selected rows are already excluded.')
            scenario_opts['exclude_rows'] = merged
            desc = f"Exclude rows: {excl_desc}"
            extra_params = {'treatment': treatment, 'rows': excl_rows, 'filter': excl_desc}
        title = f"Sensitivity ({excl_desc}): {orig_result['chart_type'].upper()} of {orig_result['variable_name']}"
        kind = 'subgroup_exclusion'
    else:
        raise ValueError(f'Unsupported subgroup sensitivity mode: {mode}')

    entry = _run_on_source_worksheet(
        presenter,
        source,
        lambda: presenter.subgroup_control_chart(
            chart_type=chart_type,
            stacked=bool(params.get('stacked', True)),
            response_index=params.get('response_index'),
            factor_index=params.get('factor_index'),
            indices=params.get('indices'),
            subgroup_size=params.get('subgroup_size'),
            options=scenario_opts,
        ),
    )
    base_sum = _subgroup_summary(orig_result)
    scen_sum = _subgroup_summary(entry['result'])

    xbar_base, xbar_scen = set(base_sum['xbar_signal_subgroups']), set(scen_sum['xbar_signal_subgroups'])
    disp_base, disp_scen = set(base_sum['disp_signal_subgroups']), set(scen_sum['disp_signal_subgroups'])
    sigma_rel = abs(scen_sum['within_stdev'] - base_sum['within_stdev']) / max(abs(base_sum['within_stdev']), 1e-12)

    conclusions = [
        {
            'criterion': 'Overall Control Status',
            'baseline': 'In Control' if base_sum['in_control'] else f"Out of Control ({base_sum['total_signals']})",
            'scenario': 'In Control' if scen_sum['in_control'] else f"Out of Control ({scen_sum['total_signals']})",
            'status': 'Held' if base_sum['in_control'] == scen_sum['in_control'] else 'Changed',
        },
        {
            'criterion': 'Xbar Signal Subgroups',
            'baseline': ', '.join(map(str, base_sum['xbar_signal_subgroups'])) or 'None',
            'scenario': ', '.join(map(str, scen_sum['xbar_signal_subgroups'])) or 'None',
            'status': 'Held' if xbar_base == xbar_scen else 'Changed',
        },
        {
            'criterion': f'{disp_label} Signal Subgroups',
            'baseline': ', '.join(map(str, base_sum['disp_signal_subgroups'])) or 'None',
            'scenario': ', '.join(map(str, scen_sum['disp_signal_subgroups'])) or 'None',
            'status': 'Held' if disp_base == disp_scen else 'Changed',
        },
        {
            'criterion': 'Within Sigma Stability (<=5%)',
            'baseline': f"{base_sum['within_stdev']:.6g}",
            'scenario': f"{scen_sum['within_stdev']:.6g} ({(scen_sum['within_stdev'] - base_sum['within_stdev']) / max(abs(base_sum['within_stdev']), 1e-12):+.1%})",
            'status': 'Held' if sigma_rel <= 0.05 else 'Changed',
        },
    ]

    entry['title'] = title
    entry['result']['title'] = title
    entry['result']['sensitivity'] = {
        'kind': kind,
        'baseline_title': baseline['title'],
        'baseline_id': baseline.get('entry_id'),
        'scenario_description': desc,
        'parameters': extra_params,
        'baseline_summary': base_sum,
        'scenario_summary': scen_sum,
        'signal_changes': {
            'xbar_held': sorted(xbar_base & xbar_scen),
            'xbar_added': sorted(xbar_scen - xbar_base),
            'xbar_cleared': sorted(xbar_base - xbar_scen),
            'disp_held': sorted(disp_base & disp_scen),
            'disp_added': sorted(disp_scen - disp_base),
            'disp_cleared': sorted(disp_base - disp_scen),
        },
        'conclusions': conclusions,
    }
    presenter._results_dirty = True
    return entry


def _attribute_signal_set(result: dict[str, Any]) -> set[int]:
    sgs: set[int] = set()
    for sg_key, rules in (result.get('test_failures') or {}).items():
        if rules:
            sgs.add(int(sg_key))
    if not sgs and result.get('signals'):
        sgs.update(int(sg) for sg in result.get('signals', []))
    return sgs


def _attribute_summary(result: dict[str, Any]) -> dict[str, Any]:
    sig_rows = sorted(_attribute_signal_set(result))
    raw_t1 = [int(k) for k, rules in (result.get('test_failures') or {}).items() if 1 in (rules or [])]
    t1_count = len(raw_t1) if raw_t1 else len(result.get('signals', []))
    return {
        'chart_type': str(result.get('chart_type', result.get('chart', 'P'))).upper().strip().replace('′', "'"),
        'n_rows': int(result.get('n_rows', len(result.get('observations') or []))),
        'n_subgroups': int(result.get('n_subgroups', 0)),
        'center': float(result['center']),
        'sigma_z': float(result.get('sigma_z', 1.0)),
        'total_signals': len(sig_rows),
        'test1_signals': t1_count,
        'signal_rows': sig_rows,
        'in_control': len(sig_rows) == 0,
    }


def run_attribute_sensitivity(
    presenter,
    baseline: dict[str, Any],
    mode: str,
    *,
    start_row: int | None = None,
    end_row: int | None = None,
    batch_col_index: int | None = None,
    batch_values: list[str] | tuple[str, ...] | set[str] | None = None,
    exclude_rows_spec: Any = None,
    treatment: str = 'exclude_rows',
) -> dict[str, Any]:
    """Branch a saved Attribute Control Chart by baseline period or flagged-batch/row exclusion."""
    if (
        not isinstance(baseline, dict)
        or baseline.get('recipe', {}).get('action') != 'attribute_control_chart'
        or baseline.get('result', {}).get('analysis') != 'attribute_control'
    ):
        raise ValueError('Select a saved Attribute Control Chart as the sensitivity baseline.')
    if presenter.result_stale(baseline) is not False:
        raise ValueError('Rerun the baseline attribute chart on its source worksheet first.')

    source = presenter.result_worksheet(baseline)
    orig_result = baseline['result']
    settings = copy.deepcopy(baseline['recipe']['parameters']['settings'])
    settings.pop('_source_bindings', None)

    chart_type = str(orig_result.get('chart_type', settings.get('chart_type', 'P'))).upper().strip().replace('′', "'")
    n_rows = int(orig_result.get('n_rows', len(orig_result.get('observations') or [])))
    scenario_opts = copy.deepcopy(orig_result.get('options') or settings.get('options') or {})

    if mode == 'baseline_period':
        if (
            not isinstance(start_row, int)
            or not isinstance(end_row, int)
            or isinstance(start_row, bool)
            or isinstance(end_row, bool)
        ):
            raise ValueError('Enter integer start and end subgroup numbers for the baseline period.')
        if start_row < 1 or end_row > n_rows or start_row >= end_row:
            raise ValueError(f'Baseline period must satisfy 1 <= start < end <= {n_rows}.')
        if start_row == 1 and end_row == n_rows:
            raise ValueError('Baseline period must be a proper subset of subgroups (select fewer than all rows).')

        excl_existing = parse_subgroup_omission(scenario_opts.get('exclude_rows', set()))
        counts = orig_result.get('counts') or []
        sizes = orig_result.get('subgroup_sizes') or []
        period_complete = sum(
            1
            for r in range(start_row, end_row + 1)
            if r not in excl_existing
            and r - 1 < len(counts)
            and r - 1 < len(sizes)
            and counts[r - 1] is not None
            and sizes[r - 1] is not None
        )
        if period_complete < 2:
            raise ValueError('The selected baseline period must contain at least 2 complete estimation subgroups.')

        outside = {r for r in range(1, n_rows + 1) if not (start_row <= r <= end_row)}
        existing_omit = parse_subgroup_omission(scenario_opts.get('omit_subgroups', set()))
        scenario_opts['omit_subgroups'] = sorted(existing_omit | outside)
        scenario_opts.pop('historical_p', None)
        scenario_opts.pop('historical_mean', None)

        desc = f'Baseline period subgroups {start_row}..{end_row}'
        title = f"Sensitivity (Baseline {start_row}:{end_row}): {chart_type} Chart of {orig_result['variable_name']}"
        kind = 'attribute_baseline_period'
        extra_params = {'start_row': start_row, 'end_row': end_row}
    elif mode == 'exclusion':
        if treatment not in ('exclude_rows', 'omit_estimation'):
            raise ValueError("Exclusion treatment must be 'exclude_rows' or 'omit_estimation'.")
        excl_rows, excl_desc = _resolve_exclusion_rows(
            source, n_rows, batch_col_index, batch_values, exclude_rows_spec,
        )
        if treatment == 'omit_estimation':
            existing = parse_subgroup_omission(scenario_opts.get('omit_subgroups', set()))
            merged = sorted(existing | set(excl_rows))
            if merged == sorted(existing):
                raise ValueError('Selected subgroups are already omitted from limit estimation.')
            scenario_opts['omit_subgroups'] = merged
            action_label = 'Omit subgroups from estimation'
        else:
            existing = parse_subgroup_omission(scenario_opts.get('exclude_rows', set()))
            merged = sorted(existing | set(excl_rows))
            if merged == sorted(existing):
                raise ValueError('Selected rows are already excluded.')
            scenario_opts['exclude_rows'] = merged
            action_label = 'Exclude rows'
        desc = f'{action_label}: {excl_desc}'
        title = f"Sensitivity ({excl_desc}): {chart_type} Chart of {orig_result['variable_name']}"
        kind = 'attribute_exclusion'
        extra_params = {'treatment': treatment, 'rows': excl_rows, 'filter': excl_desc}
    else:
        raise ValueError(f'Unsupported attribute sensitivity mode: {mode}')

    settings['options'] = scenario_opts
    entry = _run_on_source_worksheet(
        presenter,
        source,
        lambda: presenter.attribute_control_chart(settings=settings),
    )
    base_sum = _attribute_summary(orig_result)
    scen_sum = _attribute_summary(entry['result'])

    sig_base, sig_scen = set(base_sum['signal_rows']), set(scen_sum['signal_rows'])
    c_base, c_scen = base_sum['center'], scen_sum['center']
    c_diff = abs(c_scen - c_base)
    c_rel = c_diff / max(abs(c_base), 1e-12)
    c_held = (c_diff <= 1e-6) or (c_rel <= 0.05)
    center_lbl = 'Center (p)' if chart_type in ('P', "P'", 'NP') else 'Center (Mean)'

    conclusions = [
        {
            'criterion': 'Overall Control Status',
            'baseline': 'In Control' if base_sum['in_control'] else f"Out of Control ({base_sum['total_signals']})",
            'scenario': 'In Control' if scen_sum['in_control'] else f"Out of Control ({scen_sum['total_signals']})",
            'status': 'Held' if base_sum['in_control'] == scen_sum['in_control'] else 'Changed',
        },
        {
            'criterion': 'Special-Cause Signal Subgroups',
            'baseline': ', '.join(map(str, base_sum['signal_rows'])) or 'None',
            'scenario': ', '.join(map(str, scen_sum['signal_rows'])) or 'None',
            'status': 'Held' if sig_base == sig_scen else 'Changed',
        },
        {
            'criterion': f'{center_lbl} Stability (<=5%)',
            'baseline': f'{c_base:.6g}',
            'scenario': f'{c_scen:.6g} ({(c_scen - c_base) / max(abs(c_base), 1e-12):+.1%})',
            'status': 'Held' if c_held else 'Changed',
        },
    ]
    if chart_type in ("P'", "U'"):
        sz_base, sz_scen = base_sum['sigma_z'], scen_sum['sigma_z']
        sz_rel = abs(sz_scen - sz_base) / max(abs(sz_base), 1e-12)
        conclusions.append({
            'criterion': 'Laney Sigma Z Stability (<=5%)',
            'baseline': f'{sz_base:.6g}',
            'scenario': f'{sz_scen:.6g} ({(sz_scen - sz_base) / max(abs(sz_base), 1e-12):+.1%})',
            'status': 'Held' if (abs(sz_scen - sz_base) <= 1e-6 or sz_rel <= 0.05) else 'Changed',
        })

    entry['title'] = title
    entry['result']['title'] = title
    entry['result']['sensitivity'] = {
        'kind': kind,
        'baseline_title': baseline['title'],
        'baseline_id': baseline.get('entry_id'),
        'scenario_description': desc,
        'parameters': extra_params,
        'baseline_summary': base_sum,
        'scenario_summary': scen_sum,
        'signal_changes': {
            'held': sorted(sig_base & sig_scen),
            'added': sorted(sig_scen - sig_base),
            'cleared': sorted(sig_base - sig_scen),
        },
        'conclusions': conclusions,
    }
    presenter._results_dirty = True
    return entry


def _normalize_capability_settings(source, params: dict[str, Any]) -> dict[str, Any]:
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


def _normal_cap_summary(res: dict[str, Any], ppk_threshold: float) -> dict[str, Any]:
    scale = 10_000.0 if str(res.get('display_unit', 'ppm')).lower() == 'percent' else 1.0
    ppk = res.get('ppk')
    return {
        'method': 'normal',
        'n': int(res['sample_n']),
        'cpk': res.get('cpk'),
        'ppk': ppk,
        'exp_within_ppm': float(res['within_perf']['expected_total']) * scale,
        'exp_overall_ppm': float(res['overall_perf']['expected_total']) * scale,
        'obs_total_ppm': float(res['within_perf']['observed_total']) * scale,
        'z_bench': res['overall_perf'].get('z_bench'),
        'capable': ppk is not None and float(ppk) >= ppk_threshold,
    }


def _nonnormal_cap_summary(res: dict[str, Any], ppk_threshold: float) -> dict[str, Any]:
    ppk = res['indices'].get('ppk')
    return {
        'method': str(res['method']),
        'n': int(res['n_total']),
        'cpk': None,
        'ppk': ppk,
        'ad_stat': res.get('fit_info', {}).get('ad_stat'),
        'exp_overall_ppm': float(res['expected_ppm']['total']),
        'obs_total_ppm': float(res['observed_ppm']['total']),
        'z_bench': res['benchmark_z'].get('z_bench'),
        'capable': ppk is not None and float(ppk) >= ppk_threshold,
    }


def _ppm_held(base_ppm: float, scen_ppm: float) -> bool:
    if base_ppm <= 1.0 and scen_ppm <= 1.0:
        return True
    return abs(scen_ppm - base_ppm) / max(abs(base_ppm), 1.0) <= 0.15


def run_capability_sensitivity(
    presenter,
    baseline: dict[str, Any],
    mode: str,
    *,
    distribution: str = 'auto_best',
    ppk_threshold: float = 1.33,
    batch_col_index: int | None = None,
    batch_values: list[str] | tuple[str, ...] | set[str] | None = None,
    exclude_rows_spec: Any = None,
) -> dict[str, Any]:
    """Branch a saved Normal Capability analysis by fitted distribution or batch/row exclusion."""
    if not isinstance(baseline, dict) or baseline.get('recipe', {}).get('action') != 'normal_capability':
        raise ValueError('Select a saved Normal Capability analysis as the sensitivity baseline.')
    orig_res = baseline['result']
    if orig_res.get('analysis_mode', 'normal') != 'normal':
        raise ValueError('Sensitivity analysis supports standard Normal Capability baselines.')
    if presenter.result_stale(baseline) is not False:
        raise ValueError('Rerun the baseline Normal Capability analysis on its source worksheet first.')
    if isinstance(ppk_threshold, bool) or not isinstance(ppk_threshold, (int, float)) or not math.isfinite(ppk_threshold) or ppk_threshold <= 0:
        raise ValueError('Ppk acceptance threshold must be a positive finite number.')

    source = presenter.result_worksheet(baseline)
    base_settings = _normalize_capability_settings(source, baseline['recipe']['parameters'])
    base_sum = _normal_cap_summary(orig_res, float(ppk_threshold))

    if mode == 'distribution':
        allowed = ('auto_best', *_DIST_CANDIDATES)
        if distribution not in allowed:
            raise ValueError(f"Unsupported distribution choice '{distribution}'.")

        obs = list(orig_res['observations'])
        lsl = orig_res.get('lsl')
        usl = orig_res.get('usl')
        target = orig_res.get('target')
        tol_k = float(orig_res.get('tolerance_k', 6.0))
        naming = orig_res.get('naming_convention', 'classical')

        candidate_fits = []
        chosen = distribution
        if distribution == 'auto_best':
            first_error = None
            for cand in _DIST_CANDIDATES:
                try:
                    trial = run_nonnormal_capability(
                        values=obs,
                        dist_or_transform=cand,
                        lsl=lsl,
                        usl=usl,
                        target=target,
                        tolerance_k=tol_k,
                        naming_convention=naming,
                    )
                    candidate_fits.append({
                        'distribution': cand,
                        'ad_stat': trial.get('fit_info', {}).get('ad_stat'),
                        'ppk': trial['indices'].get('ppk'),
                        'exp_total_ppm': trial['expected_ppm']['total'],
                    })
                except ValueError as exc:
                    if first_error is None:
                        first_error = str(exc)
            if not candidate_fits:
                raise ValueError(first_error or 'No candidate distribution could fit these observations.')
            candidate_fits.sort(
                key=lambda item: float('inf') if item['ad_stat'] is None else float(item['ad_stat'])
            )
            chosen = candidate_fits[0]['distribution']

        nn_settings = {
            'single_column': base_settings.get('single_column', True),
            'dist_or_transform': chosen,
            'lsl': lsl,
            'usl': usl,
            'target': target,
            'tolerance_k': tol_k,
            'naming_convention': naming,
        }
        if nn_settings['single_column']:
            nn_settings['column_index'] = base_settings.get('column_index')
            nn_settings['column_name'] = base_settings.get('column_name')
        else:
            nn_settings['cols_across_indices'] = base_settings.get('cols_across_indices')
            nn_settings['cols_across'] = base_settings.get('cols_across')
        if base_settings.get('exclude_rows'):
            nn_settings['exclude_rows'] = copy.deepcopy(base_settings['exclude_rows'])

        entry = _run_on_source_worksheet(
            presenter,
            source,
            lambda: presenter.capability_nonnormal(settings=nn_settings),
        )
        scen_sum = _nonnormal_cap_summary(entry['result'], float(ppk_threshold))
        chosen_label = _DIST_LABELS.get(chosen, chosen.title())
        desc = (
            f"Fitted distribution: {chosen_label}"
            + (f" (auto-best across {len(candidate_fits)} models)" if distribution == 'auto_best' else '')
        )
        title = f"Sensitivity ({chosen_label}): {orig_res['variable_name']}"

        ppk_base, ppk_scen = base_sum['ppk'], scen_sum['ppk']
        ppk_held = (
            (ppk_base is None and ppk_scen is None)
            or (ppk_base is not None and ppk_scen is not None and abs(ppk_scen - ppk_base) <= 0.10)
        )
        zb_base, zb_scen = base_sum['z_bench'], scen_sum['z_bench']
        zb_held = (
            (zb_base is None and zb_scen is None)
            or (zb_base is not None and zb_scen is not None and abs(zb_scen - zb_base) <= 0.25)
        )
        conclusions = [
            {
                'criterion': f'Capability Verdict (Ppk >= {ppk_threshold:g})',
                'baseline': 'Capable' if base_sum['capable'] else 'Not Capable',
                'scenario': 'Capable' if scen_sum['capable'] else 'Not Capable',
                'status': 'Held' if base_sum['capable'] == scen_sum['capable'] else 'Changed',
            },
            {
                'criterion': 'Overall Ppk (<=0.10)',
                'baseline': f'{ppk_base:.3f}' if ppk_base is not None else '*',
                'scenario': f'{ppk_scen:.3f}' if ppk_scen is not None else '*',
                'status': 'Held' if ppk_held else 'Changed',
            },
            {
                'criterion': 'Expected Overall Defect Rate (PPM)',
                'baseline': f"{base_sum['exp_overall_ppm']:.2f}",
                'scenario': f"{scen_sum['exp_overall_ppm']:.2f}",
                'status': 'Held' if _ppm_held(base_sum['exp_overall_ppm'], scen_sum['exp_overall_ppm']) else 'Changed',
            },
            {
                'criterion': 'Benchmark Z (<=0.25)',
                'baseline': f'{zb_base:.2f}' if zb_base is not None else '*',
                'scenario': f'{zb_scen:.2f}' if zb_scen is not None else '*',
                'status': 'Held' if zb_held else 'Changed',
            },
        ]
        kind = 'capability_distribution'
        extra_params = {'requested_distribution': distribution, 'selected_distribution': chosen, 'ppk_threshold': float(ppk_threshold)}
    elif mode == 'exclusion':
        n_rows = source.row_count
        excl_rows, excl_desc = _resolve_exclusion_rows(
            source, n_rows, batch_col_index, batch_values, exclude_rows_spec,
        )
        existing = parse_subgroup_omission(base_settings.get('exclude_rows', set()))
        merged = sorted(existing | set(excl_rows))
        if merged == sorted(existing):
            raise ValueError('Selected rows are already excluded.')
        scen_settings = copy.deepcopy(base_settings)
        scen_settings['exclude_rows'] = merged

        entry = _run_on_source_worksheet(
            presenter,
            source,
            lambda: presenter.normal_capability(settings=scen_settings),
        )
        scen_sum = _normal_cap_summary(entry['result'], float(ppk_threshold))
        desc = f"Excluded observations: {excl_desc}"
        title = f"Sensitivity ({excl_desc}): {orig_res['variable_name']}"
        candidate_fits = []

        ppk_base, ppk_scen = base_sum['ppk'], scen_sum['ppk']
        cpk_base, cpk_scen = base_sum['cpk'], scen_sum['cpk']
        ppk_held = (
            (ppk_base is None and ppk_scen is None)
            or (ppk_base is not None and ppk_scen is not None and abs(ppk_scen - ppk_base) <= 0.10)
        )
        cpk_held = (
            (cpk_base is None and cpk_scen is None)
            or (cpk_base is not None and cpk_scen is not None and abs(cpk_scen - cpk_base) <= 0.10)
        )
        zb_base, zb_scen = base_sum['z_bench'], scen_sum['z_bench']
        zb_held = (
            (zb_base is None and zb_scen is None)
            or (zb_base is not None and zb_scen is not None and abs(zb_scen - zb_base) <= 0.25)
        )
        conclusions = [
            {
                'criterion': f'Capability Verdict (Ppk >= {ppk_threshold:g})',
                'baseline': 'Capable' if base_sum['capable'] else 'Not Capable',
                'scenario': 'Capable' if scen_sum['capable'] else 'Not Capable',
                'status': 'Held' if base_sum['capable'] == scen_sum['capable'] else 'Changed',
            },
            {
                'criterion': 'Overall Ppk (<=0.10)',
                'baseline': f'{ppk_base:.3f}' if ppk_base is not None else '*',
                'scenario': f'{ppk_scen:.3f}' if ppk_scen is not None else '*',
                'status': 'Held' if ppk_held else 'Changed',
            },
            {
                'criterion': 'Within Cpk (<=0.10)',
                'baseline': f'{cpk_base:.3f}' if cpk_base is not None else '*',
                'scenario': f'{cpk_scen:.3f}' if cpk_scen is not None else '*',
                'status': 'Held' if cpk_held else 'Changed',
            },
            {
                'criterion': 'Expected Overall Defect Rate (PPM)',
                'baseline': f"{base_sum['exp_overall_ppm']:.2f}",
                'scenario': f"{scen_sum['exp_overall_ppm']:.2f}",
                'status': 'Held' if _ppm_held(base_sum['exp_overall_ppm'], scen_sum['exp_overall_ppm']) else 'Changed',
            },
            {
                'criterion': 'Benchmark Z (<=0.25)',
                'baseline': f'{zb_base:.2f}' if zb_base is not None else '*',
                'scenario': f'{zb_scen:.2f}' if zb_scen is not None else '*',
                'status': 'Held' if zb_held else 'Changed',
            },
        ]
        kind = 'capability_exclusion'
        extra_params = {'rows': excl_rows, 'filter': excl_desc, 'ppk_threshold': float(ppk_threshold)}
    else:
        raise ValueError(f'Unsupported capability sensitivity mode: {mode}')

    entry['title'] = title
    entry['result']['title'] = title
    entry['result']['sensitivity'] = {
        'kind': kind,
        'baseline_title': baseline['title'],
        'baseline_id': baseline.get('entry_id'),
        'scenario_description': desc,
        'ppk_threshold': float(ppk_threshold),
        'parameters': extra_params,
        'baseline_summary': base_sum,
        'scenario_summary': scen_sum,
        'candidate_fits': candidate_fits,
        'conclusions': conclusions,
    }
    presenter._results_dirty = True
    return entry


def comparison_text(result: dict[str, Any]) -> str:
    """Format a concise sensitivity comparison section for I-MR and Capability results."""
    sens = result.get('sensitivity')
    if not isinstance(sens, dict) or not sens.get('kind'):
        return ''
    kind = sens['kind']
    base = sens['baseline_summary']
    scen = sens['scenario_summary']
    lines = [
        'Sensitivity Analysis Comparison',
        f"Baseline: {sens['baseline_title']}",
        f"Scenario: {sens['scenario_description']}",
        '',
    ]
    if kind.startswith('imr_'):
        lines.extend([
            f"Observations:    {base['count']} -> {scen['count']}",
            f"Mean (I Center): {base['i_center']:.6g} -> {scen['i_center']:.6g} ({scen['i_center'] - base['i_center']:+g})",
            f"Within Sigma:    {base['within_stdev']:.6g} -> {scen['within_stdev']:.6g} ({scen['within_stdev'] - base['within_stdev']:+g})",
            f"Total Signals:   {base['total_signals']} -> {scen['total_signals']}",
        ])
    elif kind.startswith('subgroup_'):
        lines.extend([
            f"Subgroups:       {base['k_subgroups']} -> {scen['k_subgroups']}",
            f"Xbar Center:     {base['xbar_center']:.6g} -> {scen['xbar_center']:.6g} ({scen['xbar_center'] - base['xbar_center']:+g})",
            f"Within Sigma:    {base['within_stdev']:.6g} -> {scen['within_stdev']:.6g} ({scen['within_stdev'] - base['within_stdev']:+g})",
            f"Total Signals:   {base['total_signals']} -> {scen['total_signals']}",
        ])
    elif kind.startswith('attribute_'):
        lines.extend([
            f"Subgroups:       {base['n_subgroups']} -> {scen['n_subgroups']}",
            f"Center:          {base['center']:.6g} -> {scen['center']:.6g} ({scen['center'] - base['center']:+g})",
        ])
        if base.get('chart_type') in ("P'", "U'"):
            lines.append(
                f"Laney Sigma Z:   {base.get('sigma_z', 1.0):.6g} -> {scen.get('sigma_z', 1.0):.6g} "
                f"({scen.get('sigma_z', 1.0) - base.get('sigma_z', 1.0):+g})"
            )
        lines.append(f"Total Signals:   {base['total_signals']} -> {scen['total_signals']}")
    else:
        lines.extend([
            f"Method:          {base['method']} -> {scen['method']}",
            f"Sample N:        {base['n']} -> {scen['n']}",
            f"Expected PPM:    {base['exp_overall_ppm']:.2f} -> {scen['exp_overall_ppm']:.2f}",
        ])
        if sens.get('candidate_fits'):
            lines.append('')
            lines.append('Candidate Distribution Fits (Anderson-Darling)')
            for fit in sens['candidate_fits']:
                ad = f"{fit['ad_stat']:.3f}" if fit.get('ad_stat') is not None else '*'
                ppk_s = f"{fit['ppk']:.3f}" if fit.get('ppk') is not None else '*'
                lines.append(f"  {fit['distribution']:12s}  AD={ad}  Ppk={ppk_s}  Exp PPM={fit['exp_total_ppm']:.2f}")

    lines.extend(['', 'Conclusions'])
    for item in sens.get('conclusions', []):
        lines.append(
            f"  [{item['status']}] {item['criterion']}: {item['baseline']} -> {item['scenario']}"
        )
    return '\n'.join(lines)


class _ExclusionControls(QWidget):
    """Shared widget for flagged-batch value checklist and explicit row-range exclusion."""

    def __init__(self, sheet, parent=None, default_col_index: int | None = None):
        super().__init__(parent)
        self.sheet = sheet
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.batch_col_combo = QComboBox()
        self.batch_col_combo.addItem('(None — use row numbers below)', None)
        for idx, col in enumerate(sheet.columns):
            self.batch_col_combo.addItem(f'C{idx + 1}  {col.name}', idx)
            if default_col_index is not None and idx == default_col_index:
                self.batch_col_combo.setCurrentIndex(self.batch_col_combo.count() - 1)
        layout.addRow('Flagged Batch / Group Column:', self.batch_col_combo)

        self.batch_vals_list = QListWidget()
        self.batch_vals_list.setMaximumHeight(110)
        layout.addRow('Flagged Batch Values:', self.batch_vals_list)

        self.rows_edit = QLineEdit()
        self.rows_edit.setPlaceholderText('e.g. 5, 12:15')
        self.rows_label = QLabel('Additional Rows (1-based):')
        layout.addRow(self.rows_label, self.rows_edit)

        self.batch_col_combo.currentIndexChanged.connect(self._populate_values)
        self._populate_values()

    def _populate_values(self):
        self.batch_vals_list.clear()
        col_idx = self.batch_col_combo.currentData()
        if col_idx is None:
            self.batch_vals_list.setEnabled(False)
            return
        self.batch_vals_list.setEnabled(True)
        seen: list[str] = []
        seen_set: set[str] = set()
        for val in self.sheet.columns[col_idx].values:
            key = _cell_key(val)
            if key not in seen_set:
                seen_set.add(key)
                seen.append(key)
        for key in seen:
            item = QListWidgetItem(key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.batch_vals_list.addItem(item)

    def selected_batch(self) -> tuple[int | None, list[str], str]:
        col_idx = self.batch_col_combo.currentData()
        selected_vals = []
        if col_idx is not None:
            for idx in range(self.batch_vals_list.count()):
                item = self.batch_vals_list.item(idx)
                if item.checkState() == Qt.CheckState.Checked:
                    selected_vals.append(item.text())
        return col_idx, selected_vals, self.rows_edit.text().strip()


class IMRSensitivityDialog(QDialog):
    """Configure baseline-period or flagged-batch/row exclusion sensitivity for an I-MR chart."""

    def __init__(self, window, baseline_entry: dict[str, Any]):
        super().__init__(window)
        self.window = window
        self.baseline = baseline_entry
        self.entry = None
        self.setWindowTitle('I-MR Sensitivity Analysis')
        self.resize(520, 420)

        source = window.presenter.result_worksheet(baseline_entry)
        var_idx = baseline_entry['recipe']['parameters']['settings']['variables'][0]
        n_rows = len(source.columns[var_idx].values)

        layout = QVBoxLayout(self)
        res = baseline_entry['result']
        i_rows, mr_rows = _imr_signal_sets(res)
        summary_lbl = QLabel(
            f"Baseline: {baseline_entry['title']} · Rows={n_rows} · "
            f"Mean={res['i_center']:.4g}, Within Sigma={res['within_stdev']:.4g}, "
            f"Signals=I:{len(i_rows)} / MR:{len(mr_rows)}"
        )
        summary_lbl.setWordWrap(True)
        layout.addWidget(summary_lbl)

        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem('Baseline Period (Phase I Rows)', 'baseline_period')
        self.mode_combo.addItem('Flagged Batch / Row Exclusion', 'exclusion')
        form.addRow('Sensitivity Branch:', self.mode_combo)
        layout.addLayout(form)

        self.stack = QStackedWidget()

        period_page = QWidget()
        period_form = QFormLayout(period_page)
        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, max(1, n_rows - 1))
        self.start_spin.setValue(1)
        self.end_spin = QSpinBox()
        self.end_spin.setRange(2, max(2, n_rows))
        self.end_spin.setValue(max(2, n_rows // 2))
        period_form.addRow('Start Row (1-based):', self.start_spin)
        period_form.addRow('End Row (1-based):', self.end_spin)
        self.stack.addWidget(period_page)

        excl_page = QWidget()
        excl_layout = QVBoxLayout(excl_page)
        excl_layout.setContentsMargins(0, 0, 0, 0)
        self.exclusion_controls = _ExclusionControls(source, excl_page)
        excl_layout.addWidget(self.exclusion_controls)
        treat_form = QFormLayout()
        self.treatment_combo = QComboBox()
        self.treatment_combo.addItem('Exclude rows from plot & limits', 'exclude_rows')
        self.treatment_combo.addItem('Omit rows from limit estimation only', 'omit_estimation')
        treat_form.addRow('Exclusion Treatment:', self.treatment_combo)
        excl_layout.addLayout(treat_form)
        self.stack.addWidget(excl_page)

        layout.addWidget(self.stack)
        self.mode_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)

        self.error = QLabel('')
        self.error.setStyleSheet('color: #be123c;')
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate(self):
        try:
            mode = self.mode_combo.currentData()
            if mode == 'baseline_period':
                entry = self.window.presenter.imr_sensitivity(
                    self.baseline,
                    'baseline_period',
                    start_row=int(self.start_spin.value()),
                    end_row=int(self.end_spin.value()),
                )
            else:
                col_idx, batch_vals, rows_spec = self.exclusion_controls.selected_batch()
                entry = self.window.presenter.imr_sensitivity(
                    self.baseline,
                    'exclusion',
                    batch_col_index=col_idx,
                    batch_values=batch_vals,
                    exclude_rows_spec=rows_spec,
                    treatment=self.treatment_combo.currentData(),
                )
            self.entry = entry
            self.window.refresh()
            self.window.show_result(entry, target_tab='Report')
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class SubgroupSensitivityDialog(QDialog):
    """Configure baseline subgroup period or flagged-batch/row exclusion sensitivity for Xbar-R / Xbar-S."""

    def __init__(self, window, baseline_entry: dict[str, Any]):
        super().__init__(window)
        self.window = window
        self.baseline = baseline_entry
        self.entry = None
        self.setWindowTitle('Subgroup Sensitivity Analysis')
        self.resize(540, 440)

        source = window.presenter.result_worksheet(baseline_entry)
        res = baseline_entry['result']
        params = baseline_entry['recipe']['parameters']
        k_subgroups = int(res['k_subgroups'])
        xbar_sgs, disp_sgs = _subgroup_signal_sets(res)
        disp_lbl = _subgroup_disp_label(res.get('chart_type', 'xbar_r'))

        layout = QVBoxLayout(self)
        summary_lbl = QLabel(
            f"Baseline: {baseline_entry['title']} · Subgroups={k_subgroups} · "
            f"Xbar={res['xbar_center']:.4g}, Within Sigma={res['within_stdev']:.4g}, "
            f"Signals=Xbar:{len(xbar_sgs)} / {disp_lbl}:{len(disp_sgs)}"
        )
        summary_lbl.setWordWrap(True)
        layout.addWidget(summary_lbl)

        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem('Baseline Subgroup Period', 'baseline_period')
        self.mode_combo.addItem('Flagged Batch / Row Exclusion', 'exclusion')
        form.addRow('Sensitivity Branch:', self.mode_combo)
        layout.addLayout(form)

        self.stack = QStackedWidget()

        period_page = QWidget()
        period_form = QFormLayout(period_page)
        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, max(1, k_subgroups - 1))
        self.start_spin.setValue(1)
        self.end_spin = QSpinBox()
        self.end_spin.setRange(2, max(2, k_subgroups))
        self.end_spin.setValue(max(2, k_subgroups // 2))
        period_form.addRow('Start Subgroup (1-based):', self.start_spin)
        period_form.addRow('End Subgroup (1-based):', self.end_spin)
        self.stack.addWidget(period_page)

        excl_page = QWidget()
        excl_layout = QVBoxLayout(excl_page)
        excl_layout.setContentsMargins(0, 0, 0, 0)
        default_fac = params.get('factor_index') if params.get('stacked', True) else None
        self.exclusion_controls = _ExclusionControls(source, excl_page, default_col_index=default_fac)
        excl_layout.addWidget(self.exclusion_controls)
        treat_form = QFormLayout()
        self.treatment_combo = QComboBox()
        self.treatment_combo.addItem('Exclude rows from chart', 'exclude_rows')
        self.treatment_combo.addItem('Omit subgroups from estimation', 'omit_estimation')
        treat_form.addRow('Exclusion Treatment:', self.treatment_combo)
        excl_layout.addLayout(treat_form)
        self.stack.addWidget(excl_page)

        layout.addWidget(self.stack)
        self.mode_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.treatment_combo.currentIndexChanged.connect(self._sync_treatment_label)
        self._sync_treatment_label()

        self.error = QLabel('')
        self.error.setStyleSheet('color: #be123c;')
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sync_treatment_label(self):
        if self.treatment_combo.currentData() == 'omit_estimation':
            self.exclusion_controls.rows_label.setText('Additional Subgroups (1-based):')
            self.exclusion_controls.rows_edit.setPlaceholderText('e.g. 4 or 2:3')
        else:
            self.exclusion_controls.rows_label.setText('Additional Rows (1-based):')
            self.exclusion_controls.rows_edit.setPlaceholderText('e.g. 5, 10:12')

    def validate(self):
        try:
            mode = self.mode_combo.currentData()
            if mode == 'baseline_period':
                entry = self.window.presenter.subgroup_sensitivity(
                    self.baseline,
                    'baseline_period',
                    start_subgroup=int(self.start_spin.value()),
                    end_subgroup=int(self.end_spin.value()),
                )
            else:
                col_idx, batch_vals, text_spec = self.exclusion_controls.selected_batch()
                treatment = self.treatment_combo.currentData()
                kwargs: dict[str, Any] = {
                    'batch_col_index': col_idx,
                    'batch_values': batch_vals,
                    'treatment': treatment,
                }
                if treatment == 'omit_estimation':
                    kwargs['exclude_subgroups_spec'] = text_spec
                else:
                    kwargs['exclude_rows_spec'] = text_spec
                entry = self.window.presenter.subgroup_sensitivity(
                    self.baseline,
                    'exclusion',
                    **kwargs,
                )
            self.entry = entry
            self.window.refresh()
            self.window.show_result(entry, target_tab='Report')
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class CapabilitySensitivityDialog(QDialog):
    """Configure fitted-distribution or batch/row exclusion sensitivity for Normal Capability."""

    def __init__(self, window, baseline_entry: dict[str, Any]):
        super().__init__(window)
        self.window = window
        self.baseline = baseline_entry
        self.entry = None
        self.setWindowTitle('Capability Sensitivity Analysis')
        self.resize(520, 440)

        source = window.presenter.result_worksheet(baseline_entry)
        res = baseline_entry['result']
        ppk_s = f"{res['ppk']:.3f}" if res.get('ppk') is not None else '*'

        layout = QVBoxLayout(self)
        summary_lbl = QLabel(
            f"Baseline: {baseline_entry['title']} · N={res['sample_n']}, "
            f"Cpk={res.get('cpk', 0.0):.3f}, Ppk={ppk_s}"
        )
        summary_lbl.setWordWrap(True)
        layout.addWidget(summary_lbl)

        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem('Fitted Distribution / Transformation', 'distribution')
        self.mode_combo.addItem('Flagged Batch / Row Exclusion', 'exclusion')
        form.addRow('Sensitivity Branch:', self.mode_combo)

        self.ppk_thresh_spin = QDoubleSpinBox()
        self.ppk_thresh_spin.setRange(0.01, 10.0)
        self.ppk_thresh_spin.setDecimals(2)
        self.ppk_thresh_spin.setSingleStep(0.05)
        self.ppk_thresh_spin.setValue(1.33)
        form.addRow('Acceptance Ppk Threshold:', self.ppk_thresh_spin)
        layout.addLayout(form)

        self.stack = QStackedWidget()

        dist_page = QWidget()
        dist_form = QFormLayout(dist_page)
        self.dist_combo = QComboBox()
        for key in ('auto_best', *_DIST_CANDIDATES):
            self.dist_combo.addItem(_DIST_LABELS[key], key)
        dist_form.addRow('Alternative Model:', self.dist_combo)
        self.stack.addWidget(dist_page)

        excl_page = QWidget()
        excl_layout = QVBoxLayout(excl_page)
        excl_layout.setContentsMargins(0, 0, 0, 0)
        self.exclusion_controls = _ExclusionControls(source, excl_page)
        excl_layout.addWidget(self.exclusion_controls)
        self.stack.addWidget(excl_page)

        layout.addWidget(self.stack)
        self.mode_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)

        self.error = QLabel('')
        self.error.setStyleSheet('color: #be123c;')
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate(self):
        try:
            mode = self.mode_combo.currentData()
            thresh = float(self.ppk_thresh_spin.value())
            if mode == 'distribution':
                entry = self.window.presenter.capability_sensitivity(
                    self.baseline,
                    'distribution',
                    distribution=self.dist_combo.currentData(),
                    ppk_threshold=thresh,
                )
            else:
                col_idx, batch_vals, rows_spec = self.exclusion_controls.selected_batch()
                entry = self.window.presenter.capability_sensitivity(
                    self.baseline,
                    'exclusion',
                    ppk_threshold=thresh,
                    batch_col_index=col_idx,
                    batch_values=batch_vals,
                    exclude_rows_spec=rows_spec,
                )
            self.entry = entry
            self.window.refresh()
            self.window.show_result(entry, target_tab='Report')
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class AttributeSensitivityDialog(QDialog):
    """Configure baseline period or flagged-batch/row exclusion sensitivity for Attribute Control Charts."""

    def __init__(self, window, baseline_entry: dict[str, Any]):
        super().__init__(window)
        self.window = window
        self.baseline = baseline_entry
        self.entry = None
        self.setWindowTitle('Attribute Sensitivity Analysis')
        self.resize(540, 440)

        source = window.presenter.result_worksheet(baseline_entry)
        res = baseline_entry['result']
        n_rows = int(res.get('n_rows', len(res.get('observations') or [])))
        sig_rows = sorted(_attribute_signal_set(res))
        chart_type = str(res.get('chart_type', res.get('chart', 'P'))).upper().strip().replace('′', "'")
        z_str = f", Sigma Z={res.get('sigma_z', 1.0):.4g}" if chart_type in ("P'", "U'") else ''

        layout = QVBoxLayout(self)
        summary_lbl = QLabel(
            f"Baseline: {baseline_entry['title']} · Subgroups={res.get('n_subgroups', n_rows)} · "
            f"Center={res['center']:.4g}{z_str}, Signals={len(sig_rows)}"
        )
        summary_lbl.setWordWrap(True)
        layout.addWidget(summary_lbl)

        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem('Baseline Period (Phase I Subgroups)', 'baseline_period')
        self.mode_combo.addItem('Flagged Batch / Row Exclusion', 'exclusion')
        form.addRow('Sensitivity Branch:', self.mode_combo)
        layout.addLayout(form)

        self.stack = QStackedWidget()

        period_page = QWidget()
        period_form = QFormLayout(period_page)
        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, max(1, n_rows))
        self.start_spin.setValue(1)
        self.end_spin = QSpinBox()
        self.end_spin.setRange(1, max(1, n_rows))
        default_end = min(max(2, n_rows // 2), max(1, n_rows - 1)) if n_rows > 2 else max(1, n_rows)
        self.end_spin.setValue(default_end)
        period_form.addRow('Start Subgroup (1-based):', self.start_spin)
        period_form.addRow('End Subgroup (1-based):', self.end_spin)
        self.stack.addWidget(period_page)

        excl_page = QWidget()
        excl_layout = QVBoxLayout(excl_page)
        excl_layout.setContentsMargins(0, 0, 0, 0)
        self.exclusion_controls = _ExclusionControls(source, excl_page)
        excl_layout.addWidget(self.exclusion_controls)
        treat_form = QFormLayout()
        self.treatment_combo = QComboBox()
        self.treatment_combo.addItem('Exclude rows from chart', 'exclude_rows')
        self.treatment_combo.addItem('Omit subgroups from estimation', 'omit_estimation')
        treat_form.addRow('Exclusion Treatment:', self.treatment_combo)
        excl_layout.addLayout(treat_form)
        self.stack.addWidget(excl_page)

        layout.addWidget(self.stack)
        self.mode_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.treatment_combo.currentIndexChanged.connect(self._sync_treatment_label)
        self._sync_treatment_label()

        self.error = QLabel('')
        self.error.setStyleSheet('color: #be123c;')
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sync_treatment_label(self):
        if self.treatment_combo.currentData() == 'omit_estimation':
            self.exclusion_controls.rows_label.setText('Additional Subgroups (1-based):')
            self.exclusion_controls.rows_edit.setPlaceholderText('e.g. 4 or 2:3')
        else:
            self.exclusion_controls.rows_label.setText('Additional Rows (1-based):')
            self.exclusion_controls.rows_edit.setPlaceholderText('e.g. 5, 10:12')

    def validate(self):
        try:
            mode = self.mode_combo.currentData()
            if mode == 'baseline_period':
                entry = self.window.presenter.attribute_sensitivity(
                    self.baseline,
                    'baseline_period',
                    start_row=int(self.start_spin.value()),
                    end_row=int(self.end_spin.value()),
                )
            else:
                col_idx, batch_vals, text_spec = self.exclusion_controls.selected_batch()
                entry = self.window.presenter.attribute_sensitivity(
                    self.baseline,
                    'exclusion',
                    batch_col_index=col_idx,
                    batch_values=batch_vals,
                    exclude_rows_spec=text_spec,
                    treatment=self.treatment_combo.currentData(),
                )
            self.entry = entry
            self.window.refresh()
            self.window.show_result(entry, target_tab='Report')
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
