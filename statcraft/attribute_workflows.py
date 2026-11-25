"""Traceability, signal investigations, and batch workflow replay for Attribute Control Charts."""
from __future__ import annotations

import copy
import json
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

from .attribute_control_engine import parse_subgroup_omission
from .imr_investigation import context_rows


def _norm_chart_type(raw: Any) -> str:
    return str(raw or 'P').upper().strip().replace('′', "'")


def _chart_display(chart_type: str) -> str:
    norm = _norm_chart_type(chart_type)
    if norm == "P'":
        return "Laney P' Chart"
    if norm == "U'":
        return "Laney U' Chart"
    return f'{norm} Chart'


def _calc_method(chart_type: str) -> str:
    norm = _norm_chart_type(chart_type)
    if norm == 'P':
        return 'Proportion defective (count / subgroup_size)'
    if norm == "P'":
        return 'Proportion defective (count / subgroup_size) with Laney sigma_z adjustment'
    if norm == 'NP':
        return 'Number of defectives (count)'
    if norm == 'C':
        return 'Count of defects per unit (count, n=1)'
    if norm == 'U':
        return 'Defects per unit (count / subgroup_size)'
    return 'Defects per unit (count / subgroup_size) with Laney sigma_z adjustment'


def _parse_test_failures(result: dict[str, Any]) -> dict[int, list[int]]:
    raw = result.get('test_failures') or {}
    parsed: dict[int, list[int]] = {}
    for sg_key, rules in raw.items():
        try:
            sg_idx = int(sg_key)
        except (TypeError, ValueError):
            continue
        cleaned = sorted({int(r) for r in (rules or [])})
        if cleaned:
            parsed[sg_idx] = cleaned
    if not parsed and result.get('signals'):
        for sg_key in result.get('signals', []):
            try:
                parsed[int(sg_key)] = [1]
            except (TypeError, ValueError):
                continue
    return parsed


def point_trace(result: dict[str, Any], subgroup: int) -> dict[str, Any]:
    """Resolve a plotted attribute subgroup point against the observations saved with the result."""
    if not isinstance(result, dict) or result.get('analysis') != 'attribute_control':
        raise ValueError('Select a saved Attribute Control Chart.')
    obs_list = result.get('observations') or []
    n_rows = int(result.get('n_rows', len(obs_list)))
    if type(subgroup) is not int or not 1 <= subgroup <= n_rows:
        raise ValueError(f'Subgroup number must be between 1 and {n_rows}.')

    idx = subgroup - 1
    chart_type = _norm_chart_type(result.get('chart_type', result.get('chart', 'P')))
    counts = result.get('counts') or []
    sizes = result.get('subgroup_sizes') or []
    center_lines = result.get('center_lines') or []
    lcl_list = result.get('lcl') or []
    ucl_list = result.get('ucl') or []
    sigmas = result.get('sigmas') or []

    count_val = counts[idx] if idx < len(counts) else None
    size_val = sizes[idx] if idx < len(sizes) else None
    value = obs_list[idx] if idx < len(obs_list) else None

    opts = result.get('options') or {}
    excluded_set = set(int(x) for x in (result.get('excluded_rows') or parse_subgroup_omission(opts.get('exclude_rows'))))
    omitted_set = set(int(x) for x in (result.get('omitted_subgroups') or parse_subgroup_omission(opts.get('omit_subgroups'))))
    excluded = subgroup in excluded_set
    omitted = subgroup in omitted_set
    missing = (not excluded) and (count_val is None or size_val is None)

    limits = {
        'Lower': lcl_list[idx] if idx < len(lcl_list) else None,
        'Center': center_lines[idx] if idx < len(center_lines) else None,
        'Upper': ucl_list[idx] if idx < len(ucl_list) else None,
    }
    sigma = sigmas[idx] if idx < len(sigmas) else None
    rules = list(_parse_test_failures(result).get(subgroup, []))

    return {
        'subgroup': subgroup,
        'chart_type': chart_type,
        'variable_name': str(result.get('variable_name', 'Data')),
        'subgroup_size_name': result.get('subgroup_size_name'),
        'count': count_val,
        'subgroup_size': size_val,
        'value': value,
        'excluded': excluded,
        'omitted': omitted,
        'missing': missing,
        'limits': limits,
        'sigma': sigma,
        'sigma_z': float(result.get('sigma_z', 1.0)),
        'rules': rules,
        'method': _calc_method(chart_type),
    }


def _fmt_opt(val: Any) -> str:
    if val is None:
        return '*'
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return f'{float(val):.6g}'
    return str(val)


class AttributeTraceDialog(QDialog):
    """Inspect source row values, subgroup size, limits, omissions/exclusions, and saved options."""

    def __init__(self, parent, entry: dict[str, Any], stale):
        super().__init__(parent)
        self.setWindowTitle('Trace Attribute Result')
        self.resize(640, 520)
        self.result = entry['result']
        chart_type = _norm_chart_type(self.result.get('chart_type', self.result.get('chart', 'P')))

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"Saved inputs from {entry.get('worksheet_name', 'worksheet')} · "
            f"{_chart_display(chart_type)} of {self.result.get('variable_name', 'Data')}"
        ))
        if stale is True:
            layout.addWidget(QLabel('The current worksheet differs from the saved analysis.'))

        form = QFormLayout()
        self.subgroup = QSpinBox()
        n_rows = int(self.result.get('n_rows', len(self.result.get('observations') or [])))
        self.subgroup.setRange(1, max(1, n_rows))
        form.addRow('Subgroup (Row)', self.subgroup)
        layout.addLayout(form)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.subgroup.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        result = self.result
        trace = point_trace(result, int(self.subgroup.value()))
        status_notes = []
        if trace['excluded']:
            status_notes.append('excluded from chart & estimation')
        if trace['omitted']:
            status_notes.append('omitted from parameter estimation')
        if trace['missing']:
            status_notes.append('missing/incomplete')
        note_str = f" ({'; '.join(status_notes)})" if status_notes else ''

        value_str = _fmt_opt(trace['value']) if trace['value'] is not None else 'No plotted point'
        size_lbl = trace['subgroup_size_name'] or 'Constant'
        rules_str = ', '.join(f'Test {r}' for r in trace['rules']) if trace['rules'] else 'None'

        lines = [
            f"Subgroup (Row): {trace['subgroup']}{note_str}",
            f"Count ({trace['variable_name']}): {_fmt_opt(trace['count'])} · Subgroup size ({size_lbl}): {_fmt_opt(trace['subgroup_size'])}",
            f"Plotted value: {value_str}",
            f"Calculation: {trace['method']}",
            f"Failed Nelson tests: {rules_str}",
            '',
            'Control limits at this subgroup',
        ]
        for label, val in trace['limits'].items():
            if val is not None:
                lines.append(f'{label}: {_fmt_opt(val)}')
            elif trace['excluded'] or trace['missing']:
                lines.append(f'{label}: * (Not plotted)')
            else:
                lines.append(f'{label}: Hidden')
        lines.append(f"Sigma: {_fmt_opt(trace['sigma'])}")
        if trace['chart_type'] in ("P'", "U'"):
            lines.append(f"Laney Sigma Z: {trace['sigma_z']:.6g}")

        from .imr_trace import format_trace_fields
        excl_rows = result.get('excluded_rows', [])
        omit_sg = result.get('omitted_subgroups', [])
        est_info = result.get('estimation_trace', {
            'chart_type': trace['chart_type'],
            'center': result.get('center'),
            'sigma_z': trace['sigma_z'],
            'omitted_subgroups': omit_sg,
            'excluded_rows': excl_rows,
        })
        lines.extend([
            '',
            f"Excluded rows: {', '.join(map(str, excl_rows)) if excl_rows else 'None'}",
            f"Subgroups omitted from estimation: {', '.join(map(str, omit_sg)) if omit_sg else 'None'}",
            '',
            'Limit estimation',
            *format_trace_fields(est_info),
            '',
            'Saved analysis options',
            *format_trace_fields(result.get('options', {})),
        ])
        self.details.setPlainText('\n'.join(lines))


def signals(result: dict[str, Any]) -> dict[int, list[int]]:
    return _parse_test_failures(result)


def run_summary(entry: dict[str, Any]) -> dict[str, Any]:
    result = entry['result']
    flagged = signals(result)
    return {
        'title': entry['title'],
        'worksheet': entry.get('worksheet_name', ''),
        'entry_id': entry.get('entry_id'),
        'chart_type': _norm_chart_type(result.get('chart_type', result.get('chart', 'P'))),
        'variable': str(result.get('variable_name', 'Data')),
        'subgroup_size_name': result.get('subgroup_size_name'),
        'n_rows': int(result.get('n_rows', len(result.get('observations') or []))),
        'n_subgroups': int(result.get('n_subgroups', 0)),
        'signal_count': len(flagged),
        'test1_signals': sum(1 in rules for rules in flagged.values()),
        'center': float(result['center']),
        'sigma_z': float(result.get('sigma_z', 1.0)),
        'total_count': float(result.get('total_count', 0.0)),
        'total_sample_size': float(result.get('total_sample_size', 0.0)),
        'options': copy.deepcopy(result.get('options', {})),
    }


def format_investigation(result: dict[str, Any]) -> str:
    chart_type = _norm_chart_type(result.get('chart_type', 'P'))
    trace = result['trace']
    limits_str = ', '.join(f'{key}={_fmt_opt(val)}' for key, val in trace['limits'].items())
    if chart_type in ("P'", "U'"):
        limits_str += f" · Sigma Z={float(trace.get('sigma_z', 1.0)):.4f}"

    lines = [
        f"{_chart_display(chart_type)}, subgroup {result['subgroup']} · Test(s) {', '.join(map(str, result['rules']))}",
        f"Plotted value: {_fmt_opt(trace['value'])} · Count={_fmt_opt(trace['count'])} · Size={_fmt_opt(trace['subgroup_size'])} · {trace['method']}",
        f'Control limits: {limits_str}',
        '',
        'Worksheet context captured at investigation time',
    ]
    for row, columns in result['context']:
        lines.append(f"Row {row}: " + (' | '.join(f'{name}={value}' for name, value in columns) or 'No values'))
    for caption, key in [('Suspected cause', 'cause'), ('Supporting evidence', 'evidence'), ('Corrective action', 'action')]:
        lines.extend(['', caption, result[key] or 'Pending'])
    lines.extend(['', 'Before and after'])
    for caption, key in [('Before', 'before'), ('After', 'after')]:
        summary = result[key]
        if summary is None:
            lines.append(f'{caption}: Pending')
            continue
        center_line = f"  Center: {summary['center']:.6g}"
        if chart_type in ("P'", "U'"):
            center_line += f" · Sigma Z: {summary.get('sigma_z', 1.0):.6g}"
        lines.extend([
            f"{caption}: {summary['title']} ({summary['worksheet']})",
            f"  Signals: {summary['signal_count']}/{summary['n_subgroups']}",
            center_line,
            f"  Total count: {summary['total_count']:g} · Total size: {summary['total_sample_size']:g}",
        ])
    if result['after'] is not None:
        lines.append("Counts use each saved chart's own limits and tests.")
        if result['before']['options'] != result['after']['options']:
            lines.append('The saved chart options differ between runs.')
    return '\n'.join(lines)


class AttributeInvestigationDialog(QDialog):
    """Record cause, supporting evidence, corrective action, and after-chart comparison."""

    def __init__(self, window, entry: dict[str, Any] | None, investigation: dict[str, Any] | None = None):
        super().__init__(window)
        self.window = window
        self.entry = entry
        self.investigation = investigation
        self.saved_entry = None
        self.setWindowTitle('Investigate Attribute Signal')
        self.resize(720, 680)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.signal = QComboBox()
        self.after = QComboBox()
        self.after.addItem('Pending', None)

        before = investigation['result']['before'] if investigation else run_summary(entry)
        self._chart_type = before['chart_type']
        for candidate in window.presenter.history:
            res = candidate.get('result', {})
            if (
                res.get('analysis') == 'attribute_control'
                and _norm_chart_type(res.get('chart_type', res.get('chart'))) == before['chart_type']
                and str(res.get('variable_name', '')) == before['variable']
                and candidate.get('entry_id') != before['entry_id']
            ):
                label = f"{candidate['title']} · {candidate.get('worksheet_name', '')} · {candidate['time']}"
                self.after.addItem(label, candidate['entry_id'])

        if investigation:
            record = investigation['result']
            self.after_snapshot = record['after']
            if self.after_snapshot:
                self.after.insertItem(1, f"Saved comparison · {self.after_snapshot['worksheet']}", '')
                self.after.setCurrentIndex(1)
            self.signal.addItem(self._signal_label(record['subgroup'], record['rules']))
            self.signal.setEnabled(False)
        else:
            self.after_snapshot = None
            for sg, rules in sorted(signals(entry['result']).items()):
                self.signal.addItem(self._signal_label(sg, rules), sg)

        form.addRow('Signal', self.signal)
        form.addRow('After chart', self.after)
        layout.addLayout(form)

        self.notes: dict[str, QPlainTextEdit] = {}
        existing = investigation['result'] if investigation else {}
        for title, key in [
            ('Suspected cause', 'cause'),
            ('Supporting evidence', 'evidence'),
            ('Corrective action', 'action'),
        ]:
            layout.addWidget(QLabel(title))
            field = QPlainTextEdit(existing.get(key, ''))
            field.setMaximumHeight(68)
            self.notes[key] = field
            layout.addWidget(field)

        layout.addWidget(QLabel('Investigation report preview'))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)

        self.error = QLabel()
        self.error.setStyleSheet('color: #be123c;')
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.signal.currentIndexChanged.connect(self.refresh)
        self.after.currentIndexChanged.connect(self.refresh)
        for field in self.notes.values():
            field.textChanged.connect(self.refresh)
        self.refresh()

    def _signal_label(self, subgroup: int, rules: list[int] | None = None) -> str:
        if rules is None and self.entry is not None:
            rules = signals(self.entry['result']).get(subgroup, [])
        rules_str = ', '.join(map(str, rules or []))
        return f'Subgroup {subgroup} (Test {rules_str})'

    def record(self) -> dict[str, Any]:
        presenter = self.window.presenter
        if self.investigation:
            record = copy.deepcopy(self.investigation['result'])
        else:
            sg = self.signal.currentData()
            if sg is None:
                raise ValueError('No special-cause signal is available to investigate.')
            result = self.entry['result']
            sheet = presenter.result_worksheet(self.entry)
            trace = point_trace(result, sg)
            lo = max(1, sg - 1)
            hi = min(sheet.row_count, sg + 1)
            ctx_range = range(lo, hi + 1) if sheet.row_count > 0 else range(0)
            record = {
                'analysis': 'attribute_investigation',
                'chart_type': self._chart_type,
                'subgroup': sg,
                'rules': signals(result)[sg],
                'trace': trace,
                'context': context_rows(sheet, ctx_range),
                'before': run_summary(self.entry),
            }

        after_id = self.after.currentData()
        record['after'] = None
        if after_id == '':
            record['after'] = self.after_snapshot
        elif after_id is not None:
            after = next((item for item in presenter.history if item.get('entry_id') == after_id), None)
            if after is None:
                raise ValueError('The selected after chart is no longer available.')
            record['after'] = run_summary(after)
        record.update({key: field.toPlainText().strip() for key, field in self.notes.items()})
        return record

    def refresh(self):
        try:
            self.preview.setPlainText(format_investigation(self.record()))
            self.error.clear()
        except ValueError as exc:
            self.preview.clear()
            self.error.setText(str(exc))

    def save(self):
        try:
            record = self.record()
            if not any(record[key] for key in self.notes):
                raise ValueError('Enter a suspected cause, supporting evidence, or corrective action.')
            presenter = self.window.presenter
            if self.investigation:
                self.investigation['result'] = record
                self.saved_entry = self.investigation
            else:
                label = self._signal_label(record['subgroup'], record['rules'])
                title = f"Attribute Investigation: {record['before']['variable']} ({label})"
                self.saved_entry = presenter._record(title, record)
                self.saved_entry['worksheet_id'] = self.entry.get('worksheet_id')
                self.saved_entry['worksheet_name'] = self.entry.get('worksheet_name')
            presenter._results_dirty = True
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


def approve(
    presenter,
    entry: dict[str, Any],
    max_signals: int = 0,
    max_center: float | None = None,
) -> dict[str, Any]:
    if not isinstance(entry, dict) or entry.get('result', {}).get('analysis') != 'attribute_control':
        raise ValueError('Select a saved Attribute Control Chart.')
    if presenter.result_stale(entry) is not False:
        raise ValueError('Rerun the attribute chart before approving it as a baseline.')
    if type(max_signals) is not int or max_signals < 0:
        raise ValueError('The maximum signal count must be a nonnegative integer.')

    res = entry['result']
    chart_type = _norm_chart_type(res.get('chart_type', res.get('chart', 'P')))
    req_center: float | None = None
    if max_center is not None:
        if isinstance(max_center, bool) or not isinstance(max_center, (int, float)) or not math.isfinite(float(max_center)):
            raise ValueError('Maximum center threshold must be a finite nonnegative number.')
        req_center = float(max_center)
        if req_center < 0.0:
            raise ValueError('Maximum center threshold cannot be negative.')
        if chart_type in ('P', "P'") and req_center > 1.0:
            raise ValueError(f'Maximum center proportion for {chart_type} Chart must be between 0 and 1.')

    params = entry['recipe']['parameters']['settings']
    source = presenter.result_worksheet(entry)
    var_idx = (params.get('variables') or [0])[0]
    count_col = source.columns[var_idx]
    is_sub_col = bool(params.get('is_subgroup_col', False)) and chart_type != 'C'
    sub_col_name = None
    if is_sub_col and params.get('subgroup_col_idx') is not None:
        sub_col_name = source.columns[params['subgroup_col_idx']].name

    options = copy.deepcopy(res.get('options', {}))

    comparison = res.get('workflow_comparison')
    previous = res.get('workflow_replay')
    if comparison and previous:
        comparison.setdefault('baseline', copy.deepcopy(previous['baseline']))
        comparison.setdefault('max_signals', previous['max_signals'])
        comparison.setdefault('max_center', previous.get('max_center'))

    template = {
        'baseline': run_summary(entry),
        'chart_type': chart_type,
        'variable_name': count_col.name,
        'is_subgroup_col': is_sub_col,
        'subgroup_size_name': sub_col_name,
        'subgroup_size': params.get('subgroup_size'),
        'options': options,
        'max_signals': max_signals,
        'max_center': req_center,
    }
    res['workflow_replay'] = template
    presenter._results_dirty = True
    return template


class ApproveAttributeReplayDialog(QDialog):
    """Configure signal-count and optional center acceptance thresholds for Attribute replay."""

    def __init__(self, parent, default_center: float = 0.0, chart_type: str = 'P'):
        super().__init__(parent)
        self.setWindowTitle('Approve Attribute Replay Baseline')
        self.resize(440, 200)
        norm_type = _norm_chart_type(chart_type)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.max_signals_spin = QSpinBox()
        self.max_signals_spin.setRange(0, 1_000_000)
        self.max_signals_spin.setValue(0)
        form.addRow('Maximum special-cause signals', self.max_signals_spin)

        self.use_max_center = QCheckBox('Require Maximum Center (p̄ / Mean)')
        self.use_max_center.setChecked(False)
        self.max_center_spin = QDoubleSpinBox()
        self.max_center_spin.setDecimals(4)
        if norm_type in ('P', "P'"):
            self.max_center_spin.setRange(0.0, 1.0)
            self.max_center_spin.setSingleStep(0.01)
            init_val = min(1.0, max(0.0, float(default_center or 0.05)))
        else:
            self.max_center_spin.setRange(0.0, 1_000_000_000.0)
            self.max_center_spin.setSingleStep(0.5)
            init_val = max(0.0, float(default_center or 1.0))
        self.max_center_spin.setValue(init_val)
        self.max_center_spin.setEnabled(False)
        form.addRow(self.use_max_center, self.max_center_spin)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.use_max_center.toggled.connect(self.max_center_spin.setEnabled)

    def thresholds(self) -> tuple[int, float | None]:
        return (
            int(self.max_signals_spin.value()),
            float(self.max_center_spin.value()) if self.use_max_center.isChecked() else None,
        )


def preview(
    presenter,
    template: dict[str, Any],
    count_index: int | None = None,
    size_index: int | None = None,
) -> str:
    sheet = presenter.worksheet
    chart_type = _norm_chart_type(template['chart_type'])
    opts = template.get('options') or {}
    omit_set = parse_subgroup_omission(opts.get('omit_subgroups'))
    excl_set = parse_subgroup_omission(opts.get('exclude_rows'))

    if type(count_index) is not int or not 0 <= count_index < len(sheet.columns):
        raise ValueError('Select a batch count column.')
    count_col = sheet.columns[count_index]
    if count_col.kind != 'number':
        raise ValueError('Choose a numeric count column.')
    raw_counts = count_col.numeric_values(True)
    n_rows = len(raw_counts)
    if n_rows == 0:
        raise ValueError(f'{chart_type} Chart requires at least one observation.')

    is_sub_col = bool(template.get('is_subgroup_col')) and chart_type != 'C'
    if chart_type == 'C':
        raw_sizes: list[float | None] = [1.0] * n_rows
        size_desc = 'Subgroup size: Constant (1)'
    elif is_sub_col:
        if type(size_index) is not int or not 0 <= size_index < len(sheet.columns) or size_index == count_index:
            raise ValueError('Select a distinct numeric subgroup size column for the batch.')
        size_col = sheet.columns[size_index]
        if size_col.kind != 'number':
            raise ValueError('Subgroup size column must be numeric.')
        raw_sizes = size_col.numeric_values(True)
        if len(raw_sizes) != n_rows:
            raise ValueError('Batch count and subgroup size columns must have the same length.')
        size_desc = f"Subgroup size: {template.get('subgroup_size_name') or 'Size'} → C{size_index + 1} {size_col.name}"
    else:
        const_sz = template.get('subgroup_size')
        if const_sz is None or float(const_sz) <= 0:
            raise ValueError(f'{chart_type} Chart replay requires a positive subgroup size.')
        raw_sizes = [float(const_sz)] * n_rows
        size_desc = f'Constant subgroup size: {float(const_sz):g}'

    if omit_set and max(omit_set) > n_rows:
        raise ValueError('A saved estimation omission refers to a row beyond the batch.')
    if excl_set and max(excl_set) > n_rows:
        raise ValueError('A saved row exclusion refers to a row beyond the batch.')

    complete = 0
    in_est = 0
    for r, (c_raw, s_raw) in enumerate(zip(raw_counts, raw_sizes), 1):
        if r in excl_set:
            continue
        c_val = None if c_raw is None or not math.isfinite(float(c_raw)) else float(c_raw)
        s_val = None if s_raw is None or not math.isfinite(float(s_raw)) else float(s_raw)
        if c_val is not None and c_val < 0:
            raise ValueError(f'Row {r}: count values cannot be negative ({c_val}).')
        if s_val is not None and s_val <= 0:
            raise ValueError(f'Row {r}: subgroup sizes must be positive ({s_val}).')
        if chart_type in ('P', "P'", 'NP') and c_val is not None and s_val is not None and c_val > s_val:
            raise ValueError(f'Row {r}: defective count ({c_val}) cannot exceed subgroup size ({s_val}).')
        if c_val is not None and s_val is not None:
            complete += 1
            if r not in omit_set:
                in_est += 1

    if complete == 0 or in_est == 0:
        raise ValueError('At least one complete non-excluded estimation subgroup is required.')

    crit_parts = [f"Max special-cause signals <= {template['max_signals']}"]
    if template.get('max_center') is not None:
        crit_parts.append(f"Max center <= {float(template['max_center']):g}")

    return (
        f"{template['variable_name']} → C{count_index + 1} {count_col.name} ({complete} complete subgroup(s))\n"
        f"{size_desc}\n"
        f"Excluded rows: {sorted(excl_set)} · Omitted from estimation: {sorted(omit_set)}\n"
        f"Acceptance criteria: {'; '.join(crit_parts)}"
    )


def replay(
    presenter,
    template: dict[str, Any],
    count_index: int | None = None,
    size_index: int | None = None,
) -> dict[str, Any]:
    mapping = preview(presenter, template, count_index=count_index, size_index=size_index)
    chart_type = _norm_chart_type(template['chart_type'])
    is_sub_col = bool(template.get('is_subgroup_col')) and chart_type != 'C'

    entry = presenter.attribute_control_chart(settings={
        'chart_type': chart_type,
        'variables': [count_index],
        'is_subgroup_col': is_sub_col,
        'subgroup_col_idx': size_index if is_sub_col else None,
        'subgroup_size': template.get('subgroup_size') if not is_sub_col else None,
        'options': copy.deepcopy(template.get('options', {})),
    })
    batch = run_summary(entry)
    max_sig = int(template['max_signals'])
    max_ctr = template.get('max_center')
    passed = int(batch['signal_count']) <= max_sig and (
        max_ctr is None or float(batch['center']) <= float(max_ctr)
    )

    entry['result']['workflow_replay'] = copy.deepcopy(template)
    entry['result']['workflow_comparison'] = {
        'mapping': mapping,
        'batch': batch,
        'baseline': copy.deepcopy(template['baseline']),
        'max_signals': max_sig,
        'max_center': max_ctr,
        'passed': passed,
    }
    presenter._results_dirty = True
    return entry


def comparison_text(result: dict[str, Any]) -> str:
    template = result.get('workflow_replay')
    comp = result.get('workflow_comparison')
    if not template or not comp or result.get('analysis') != 'attribute_control':
        return ''
    baseline = comp.get('baseline', template['baseline'])
    batch = comp['batch']
    chart_type = _norm_chart_type(batch.get('chart_type', template.get('chart_type', 'P')))
    lines = [
        'Workflow Replay (Attribute Control Chart)',
        comp['mapping'],
        '',
        f"Approved baseline: {baseline['worksheet']} / {baseline['variable']} ({_chart_display(chart_type)})",
        f"Batch: {batch['worksheet']} / {batch['variable']}",
        f"Subgroups: {baseline['n_subgroups']} -> {batch['n_subgroups']} ({batch['n_subgroups'] - baseline['n_subgroups']:+d})",
        f"Special-cause signals: {baseline['signal_count']} -> {batch['signal_count']} ({batch['signal_count'] - baseline['signal_count']:+d})",
        f"Center: {baseline['center']:g} -> {batch['center']:g} ({batch['center'] - baseline['center']:+g})",
    ]
    if chart_type in ("P'", "U'"):
        lines.append(
            f"Laney Sigma Z: {baseline.get('sigma_z', 1.0):g} -> {batch.get('sigma_z', 1.0):g} "
            f"({batch.get('sigma_z', 1.0) - baseline.get('sigma_z', 1.0):+g})"
        )
    max_sig = comp.get('max_signals', template['max_signals'])
    max_ctr = comp.get('max_center', template.get('max_center'))
    passed = comp.get('passed')
    if passed is None:
        passed = int(batch['signal_count']) <= int(max_sig) and (
            max_ctr is None or float(batch['center']) <= float(max_ctr)
        )
    lines.append(f"Acceptance: {'Pass' if passed else 'Fail'}")
    return '\n'.join(lines)


class AttributeReplayDialog(QDialog):
    """Map active worksheet columns to an approved Attribute Control Chart replay template."""

    def __init__(self, window, baseline_entry: dict[str, Any]):
        super().__init__(window)
        self.window = window
        self.template = baseline_entry['result']['workflow_replay']
        self.saved_entry = None
        self.setWindowTitle('Replay Attribute Chart on Current Worksheet')
        self.resize(540, 360)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        sheet = window.presenter.worksheet
        chart_type = _norm_chart_type(self.template['chart_type'])
        is_sub_col = bool(self.template.get('is_subgroup_col')) and chart_type != 'C'

        self.count_combo = QComboBox()
        for idx, col in enumerate(sheet.columns):
            if col.kind == 'number':
                self.count_combo.addItem(f'C{idx + 1} {col.name}', idx)
                if col.name == self.template['variable_name']:
                    self.count_combo.setCurrentIndex(self.count_combo.count() - 1)
        form.addRow('Batch count column', self.count_combo)

        self.size_combo: QComboBox | None = None
        if is_sub_col:
            self.size_combo = QComboBox()
            target_sz = self.template.get('subgroup_size_name') or ''
            selected_cnt = self.count_combo.currentData()
            matched = False
            fallback_pos = None
            for idx, col in enumerate(sheet.columns):
                if col.kind == 'number':
                    self.size_combo.addItem(f'C{idx + 1} {col.name}', idx)
                    pos = self.size_combo.count() - 1
                    if col.name == target_sz:
                        self.size_combo.setCurrentIndex(pos)
                        matched = True
                    elif idx != selected_cnt and fallback_pos is None:
                        fallback_pos = pos
            if not matched and fallback_pos is not None:
                self.size_combo.setCurrentIndex(fallback_pos)
            form.addRow('Subgroup size column', self.size_combo)

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

        self.count_combo.currentIndexChanged.connect(self.update_preview)
        if self.size_combo is not None:
            self.size_combo.currentIndexChanged.connect(self.update_preview)
        self.update_preview()

    def _selection_kwargs(self) -> dict[str, Any]:
        return {
            'count_index': self.count_combo.currentData(),
            'size_index': self.size_combo.currentData() if self.size_combo is not None else None,
        }

    def update_preview(self):
        try:
            text = preview(self.window.presenter, self.template, **self._selection_kwargs())
        except ValueError as exc:
            self.preview_label.clear()
            self.error.setText(str(exc))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        else:
            self.error.clear()
            self.preview_label.setText(text)
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def accept_replay(self):
        try:
            self.saved_entry = replay(self.window.presenter, self.template, **self._selection_kwargs())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()
