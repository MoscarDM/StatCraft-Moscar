"""Traceability, signal investigations, and batch workflow replay for Xbar-R / Xbar-S charts."""
from __future__ import annotations

import copy
import json
import math
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from .imr_investigation import context_rows
from .subgroup_control import c4, c5, d2, d3


def _disp_label(chart_type: str) -> str:
    return 'Range' if chart_type in ('xbar_r', 'r', 'xbar') else 'StDev'


def _panel_allowed(chart_type: str, panel: str) -> bool:
    if panel == 'xbar':
        return chart_type in ('xbar_r', 'xbar_s', 'xbar')
    if panel == 'disp':
        return chart_type in ('xbar_r', 'xbar_s', 'r', 's')
    return False


def point_trace(result: dict[str, Any], panel: str, subgroup: int) -> dict[str, Any]:
    """Resolve a plotted subgroup point against the observations saved with the result."""
    chart_type = result.get('chart_type', 'xbar_r')
    k_subgroups = int(result.get('k_subgroups', 0))
    if panel not in ('xbar', 'disp') or not _panel_allowed(chart_type, panel):
        raise ValueError('Select a valid chart panel for this subgroup control chart.')
    if type(subgroup) is not int or not 1 <= subgroup <= k_subgroups:
        raise ValueError(f'Subgroup number must be between 1 and {k_subgroups}.')

    idx = subgroup - 1
    is_range = chart_type in ('xbar_r', 'r', 'xbar')
    n = int(result['subgroup_sizes'][idx])
    omitted = subgroup in set(result.get('options', {}).get('omit_subgroups', []))

    if panel == 'xbar':
        value = result['means'][idx]
        limits = {
            'Lower': result['xbar_lcl'][idx],
            'Center': result['xbar_center'],
            'Upper': result['xbar_ucl'][idx],
        }
        method = 'Arithmetic mean of valid observations in subgroup'
    else:
        value = result['disp_values'][idx]
        limits = {
            'Lower': result['disp_lcl'][idx],
            'Center': result['disp_centers'][idx],
            'Upper': result['disp_ucl'][idx],
        }
        method = (
            'Maximum minus minimum of valid observations in subgroup'
            if is_range
            else 'Sample standard deviation (ddof=1) of valid observations in subgroup'
        )

    trace_list = result.get('subgroup_trace') or []
    if idx < len(trace_list):
        sg_meta = trace_list[idx]
        label = str(sg_meta.get('label', subgroup))
        rows = list(sg_meta.get('rows', []))
    else:
        label = str(subgroup)
        rows = []

    if is_range:
        constants = {'d2': d2(n) if n >= 2 else None, 'd3': d3(n) if n >= 2 else None}
    else:
        constants = {'c4': c4(n) if n >= 2 else None, 'c5': c5(n) if n >= 2 else None}

    missing_count = sum(1 for item in rows if len(item) >= 2 and item[1] is None)
    return {
        'subgroup': subgroup,
        'label': label,
        'value': value,
        'n': n,
        'missing_in_subgroup': missing_count,
        'omitted': omitted,
        'limits': limits,
        'rows': rows,
        'constants': constants,
        'method': method,
        'legacy_trace_missing': not bool(trace_list),
    }


class SubgroupTraceDialog(QDialog):
    """Inspect source worksheet rows, constants, stepped limits, and saved options."""

    def __init__(self, parent, entry: dict[str, Any], stale):
        super().__init__(parent)
        self.setWindowTitle('Trace Subgroup Result')
        self.resize(640, 520)
        self.result = entry['result']
        chart_type = self.result.get('chart_type', 'xbar_r')

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Saved inputs from {entry.get('worksheet_name', 'worksheet')} · {self.result['variable_name']}"))
        if stale is True:
            layout.addWidget(QLabel('The current worksheet differs from the saved analysis.'))

        form = QFormLayout()
        self.panel = QComboBox()
        if _panel_allowed(chart_type, 'xbar'):
            self.panel.addItem('Xbar (Mean)', 'xbar')
        if _panel_allowed(chart_type, 'disp'):
            self.panel.addItem(_disp_label(chart_type), 'disp')
        self.subgroup = QSpinBox()
        self.subgroup.setRange(1, max(1, int(self.result.get('k_subgroups', 1))))
        form.addRow('Panel', self.panel)
        form.addRow('Subgroup', self.subgroup)
        layout.addLayout(form)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.panel.currentIndexChanged.connect(self.refresh)
        self.subgroup.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        result = self.result
        trace = point_trace(result, self.panel.currentData(), self.subgroup.value())
        value = trace['value'] if trace['value'] is not None else 'No plotted point'
        omitted_note = ' (subgroup omitted from parameter estimation)' if trace['omitted'] else ''
        lines = [
            f"Subgroup: {trace['subgroup']} ({trace['label']}){omitted_note}",
            f"Plotted value: {value} · Valid n = {trace['n']} · Missing in subgroup = {trace['missing_in_subgroup']}",
            f"Calculation: {trace['method']}",
            '',
            'Source rows',
        ]
        if trace['rows']:
            for item in trace['rows']:
                ws_row, obs = item[0], item[1]
                col_tag = f' [{item[2]}]' if len(item) > 2 else ''
                lines.append(f"Row {ws_row}{col_tag}: {obs if obs is not None else 'Missing'}")
        elif trace['legacy_trace_missing']:
            lines.append('Row provenance unavailable on legacy snapshot; rerun the chart to capture row numbers.')

        from .imr_trace import format_trace_fields
        omit_sg = result.get('options', {}).get('omit_subgroups', [])
        est_info = result.get('estimation_trace', {
            'method': result.get('estimation_method'),
            'chart_type': result.get('chart_type'),
        })
        lines.extend([
            '',
            f"Subgroups omitted from estimation: {', '.join(map(str, omit_sg)) if omit_sg else 'None'}",
            '',
            'Control limits (subgroup size n = ' + str(trace['n']) + ')',
        ])
        lines.extend(
            f"{label}: {val if val is not None else 'Hidden'}"
            for label, val in trace['limits'].items()
        )
        const_strs = [f"{k}={v:.6g}" for k, v in trace['constants'].items() if v is not None]
        if const_strs:
            lines.append('Unbiasing constants: ' + ', '.join(const_strs))
        lines.extend([
            '',
            'Limit estimation',
            *format_trace_fields(est_info),
            '',
            'Saved analysis options',
            *format_trace_fields(result.get('options', {})),
        ])
        self.details.setPlainText('\n'.join(lines))


def signals(result: dict[str, Any]) -> dict[tuple[str, int], list[int]]:
    chart_type = result.get('chart_type', 'xbar_r')
    flagged: dict[tuple[str, int], list[int]] = {}
    if _panel_allowed(chart_type, 'xbar'):
        for sg, rules in (result.get('test_failures') or {}).items():
            flagged[('xbar', int(sg))] = list(rules)
    if _panel_allowed(chart_type, 'disp'):
        for sg in result.get('disp_signals', []):
            flagged[('disp', int(sg))] = [1]
    return flagged


def run_summary(entry: dict[str, Any]) -> dict[str, Any]:
    result = entry['result']
    flagged = signals(result)
    return {
        'title': entry['title'],
        'worksheet': entry.get('worksheet_name', ''),
        'entry_id': entry.get('entry_id'),
        'chart_type': result.get('chart_type', 'xbar_r'),
        'variable': result['variable_name'],
        'subgroups': int(result['k_subgroups']),
        'total_observations': int(sum(result['subgroup_sizes'])),
        'xbar_signals': sum(panel == 'xbar' for panel, _ in flagged),
        'disp_signals': sum(panel == 'disp' for panel, _ in flagged),
        'xbar_center': float(result['xbar_center']),
        'disp_center': float(result['disp_center']) if result.get('disp_center') is not None else 0.0,
        'within_sigma': float(result['within_stdev']),
        'options': copy.deepcopy(result['options']),
    }


def format_investigation(result: dict[str, Any]) -> str:
    chart_type = result.get('chart_type', 'xbar_r')
    disp_name = _disp_label(chart_type)
    panel = 'Xbar' if result['panel'] == 'xbar' else disp_name
    trace = result['trace']
    lines = [
        f"{panel}, subgroup {result['subgroup']} ({trace.get('label', result['subgroup'])}) · Test(s) {', '.join(map(str, result['rules']))}",
        f"Plotted value: {trace['value']} · n={trace.get('n', '*')} · {trace['method']}",
        'Control limits: ' + ', '.join(f'{key}={value}' for key, value in trace['limits'].items()),
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
        lines.extend([
            f"{caption}: {summary['title']} ({summary['worksheet']})",
            f"  Xbar signals: {summary['xbar_signals']}/{summary['subgroups']}",
            f"  {disp_name} signals: {summary['disp_signals']}/{summary['subgroups']}",
            f"  Xbar center: {summary['xbar_center']:.6g} · Within sigma: {summary['within_sigma']:.6g}",
        ])
    if result['after'] is not None:
        lines.append("Counts use each saved chart's own limits and tests.")
        if result['before']['options'] != result['after']['options']:
            lines.append('The saved chart options differ between runs.')
    return '\n'.join(lines)


class SubgroupInvestigationDialog(QDialog):
    """Record cause, supporting evidence, corrective action, and after-chart comparison."""

    def __init__(self, window, entry: dict[str, Any] | None, investigation: dict[str, Any] | None = None):
        super().__init__(window)
        self.window = window
        self.entry = entry
        self.investigation = investigation
        self.saved_entry = None
        self.setWindowTitle('Investigate Subgroup Signal')
        self.resize(720, 680)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.signal = QComboBox()
        self.after = QComboBox()
        self.after.addItem('Pending', None)

        before = investigation['result']['before'] if investigation else run_summary(entry)
        self._chart_type = before['chart_type']
        for candidate in window.presenter.history:
            result = candidate.get('result', {})
            if (
                result.get('analysis') == 'subgroup_control'
                and result.get('variable_name') == before['variable']
                and result.get('chart_type') == before['chart_type']
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
            self.signal.addItem(self._signal_label(record['panel'], record['subgroup']))
            self.signal.setEnabled(False)
        else:
            self.after_snapshot = None
            for panel, sg in sorted(signals(entry['result'])):
                self.signal.addItem(self._signal_label(panel, sg), (panel, sg))

        form.addRow('Signal', self.signal)
        form.addRow('After chart', self.after)
        self.notes = {}
        for caption, key in [('Suspected cause', 'cause'), ('Supporting evidence', 'evidence'), ('Corrective action', 'action')]:
            editor = QPlainTextEdit()
            editor.setMaximumHeight(60)
            if investigation:
                editor.setPlainText(investigation['result'][key])
            self.notes[key] = editor
            form.addRow(caption, editor)
        layout.addLayout(form)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)

        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setStyleSheet('color: #be123c;')
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.signal.currentIndexChanged.connect(self.refresh)
        self.after.currentIndexChanged.connect(self.refresh)
        for editor in self.notes.values():
            editor.textChanged.connect(self.refresh)
        self.refresh()

    def _signal_label(self, panel: str, subgroup: int) -> str:
        panel_name = 'Xbar' if panel == 'xbar' else _disp_label(self._chart_type)
        return f'{panel_name} · subgroup {subgroup}'

    def record(self) -> dict[str, Any]:
        presenter = self.window.presenter
        if self.investigation:
            record = copy.deepcopy(self.investigation['result'])
        else:
            if self.signal.currentData() is None:
                raise ValueError('This chart has no saved signal to investigate.')
            panel, sg = self.signal.currentData()
            if presenter.result_stale(self.entry) is not False:
                raise ValueError('Rerun the chart on its source worksheet before capturing process context.')
            result = self.entry['result']
            trace = point_trace(result, panel, sg)
            sheet = presenter.result_worksheet(self.entry)
            ws_rows = [int(item[0]) for item in trace.get('rows', [])]
            if ws_rows:
                lo = max(1, min(ws_rows) - 1)
                hi = min(sheet.row_count, max(ws_rows) + 1)
                ctx_range = range(lo, hi + 1)
            else:
                ctx_range = range(1, min(3, sheet.row_count) + 1)
            record = {
                'analysis': 'subgroup_investigation',
                'chart_type': result.get('chart_type', 'xbar_r'),
                'panel': panel,
                'subgroup': sg,
                'rules': signals(result)[panel, sg],
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
                label = self._signal_label(record['panel'], record['subgroup'])
                title = f"Subgroup Investigation: {record['before']['variable']} ({label})"
                self.saved_entry = presenter._record(title, record)
                self.saved_entry['worksheet_id'] = self.entry.get('worksheet_id')
                self.saved_entry['worksheet_name'] = self.entry.get('worksheet_name')
            presenter._results_dirty = True
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


def approve(presenter, entry: dict[str, Any], limit: int) -> None:
    if not isinstance(entry, dict) or entry.get('result', {}).get('analysis') != 'subgroup_control':
        raise ValueError('Select a saved Xbar-R or Xbar-S chart.')
    if presenter.result_stale(entry) is not False:
        raise ValueError('Rerun the chart before approving it as a baseline.')
    if type(limit) is not int or limit < 0:
        raise ValueError('The maximum signal count must be a nonnegative integer.')

    params = entry['recipe']['parameters']
    res = entry['result']
    source = presenter.result_worksheet(entry)
    stacked = bool(params.get('stacked', True))
    if stacked:
        resp_col = source.columns[params['response_index']]
        fac_idx = params.get('factor_index')
        col_names = [resp_col.name] + ([source.columns[fac_idx].name] if fac_idx is not None else [])
        units = [resp_col.metadata.get('unit') or resp_col.metadata.get('units')]
    else:
        cols = [source.columns[i] for i in params['indices']]
        col_names = [c.name for c in cols]
        units = [c.metadata.get('unit') or c.metadata.get('units') for c in cols]

    options = copy.deepcopy(res['options'])
    if isinstance(options.get('storage'), dict):
        options['storage'] = {k: False for k in options['storage']}

    comparison = res.get('workflow_comparison')
    previous = res.get('workflow_replay')
    if comparison and previous:
        comparison.setdefault('baseline', copy.deepcopy(previous['baseline']))
        comparison.setdefault('max_signals', previous['max_signals'])

    res['workflow_replay'] = {
        'baseline': run_summary(entry),
        'chart_type': params.get('chart_type', res['chart_type']),
        'stacked': stacked,
        'has_factor': bool(stacked and params.get('factor_index') is not None),
        'subgroup_size': params.get('subgroup_size'),
        'columns': col_names,
        'units': units,
        'options': options,
        'max_signals': limit,
    }
    presenter._results_dirty = True


def preview(
    presenter,
    template: dict[str, Any],
    response_index: int | None = None,
    factor_index: int | None = None,
    indices: list[int] | None = None,
) -> str:
    sheet = presenter.worksheet
    omit = set(template['options'].get('omit_subgroups', []))

    if template['stacked']:
        if type(response_index) is not int or not 0 <= response_index < len(sheet.columns):
            raise ValueError('Select a batch measurement column.')
        resp_col = sheet.columns[response_index]
        if resp_col.kind != 'number':
            raise ValueError('Choose a numeric measurement column.')
        unit = resp_col.metadata.get('unit') or resp_col.metadata.get('units')
        expected_unit = template['units'][0]
        if unit != expected_unit:
            raise ValueError(f"Batch unit {unit or '(unspecified)'} differs from baseline unit {expected_unit or '(unspecified)'}.")

        if template['has_factor']:
            if type(factor_index) is not int or not 0 <= factor_index < len(sheet.columns) or factor_index == response_index:
                raise ValueError('Select a distinct subgroup ID column for the batch.')
            fac_col = sheet.columns[factor_index]
            sg_count = len({v for v in fac_col.values if v is not None and v != ''})
            sg_desc = f"Subgroup ID: {template['columns'][1]} → C{factor_index + 1} {fac_col.name} ({sg_count} subgroups)"
        else:
            sz = int(template.get('subgroup_size') or 5)
            sg_count = math.ceil(len(resp_col.values) / sz) if resp_col.values else 0
            sg_desc = f'Subgroup size: {sz} ({sg_count} subgroups)'
        if omit and max(omit) > sg_count:
            raise ValueError('A saved estimation exclusion refers to a subgroup beyond the batch.')
        mapping_desc = f"{template['columns'][0]} → C{response_index + 1} {resp_col.name}\n{sg_desc}"
        units_desc = unit or 'Unspecified'
    else:
        expected_cols = template['columns']
        if not indices or len(indices) != len(expected_cols):
            raise ValueError(f'Select {len(expected_cols)} numeric subgroup columns for this unstacked baseline.')
        if len(set(indices)) != len(indices) or any(type(i) is not int or not 0 <= i < len(sheet.columns) for i in indices):
            raise ValueError('Select distinct valid columns from the current worksheet.')
        mapped_lines = []
        unit_labels = []
        row_counts = []
        for base_name, expected_unit, col_idx in zip(expected_cols, template['units'], indices):
            col = sheet.columns[col_idx]
            if col.kind != 'number':
                raise ValueError(f"Column '{col.name}' must be numeric.")
            unit = col.metadata.get('unit') or col.metadata.get('units')
            if unit != expected_unit:
                raise ValueError(f"Batch unit {unit or '(unspecified)'} for {col.name} differs from baseline unit {expected_unit or '(unspecified)'}.")
            mapped_lines.append(f'{base_name} → C{col_idx + 1} {col.name}')
            unit_labels.append(unit or 'Unspecified')
            row_counts.append(len(col.values))
        sg_count = max(row_counts) if row_counts else 0
        if omit and max(omit) > sg_count:
            raise ValueError('A saved estimation exclusion refers to a subgroup beyond the batch.')
        mapping_desc = 'Columns: ' + ', '.join(mapped_lines) + f' ({sg_count} subgroups)'
        units_desc = ', '.join(unit_labels)

    return (
        f"{mapping_desc}\n"
        f"Units: {units_desc}\n"
        f"Subgroups omitted from limit estimation: {sorted(omit)}\n"
        f"Maximum combined Xbar and {_disp_label(template['chart_type'])} signals: {template['max_signals']}"
    )


def replay(
    presenter,
    template: dict[str, Any],
    response_index: int | None = None,
    factor_index: int | None = None,
    indices: list[int] | None = None,
) -> dict[str, Any]:
    mapping = preview(presenter, template, response_index=response_index, factor_index=factor_index, indices=indices)
    entry = presenter.subgroup_control_chart(
        chart_type=template['chart_type'],
        stacked=template['stacked'],
        response_index=response_index if template['stacked'] else None,
        factor_index=factor_index if (template['stacked'] and template['has_factor']) else None,
        indices=list(indices) if not template['stacked'] else None,
        subgroup_size=template.get('subgroup_size') if (template['stacked'] and not template['has_factor']) else None,
        options=copy.deepcopy(template['options']),
    )
    candidate = run_summary(entry)
    entry['result']['workflow_replay'] = copy.deepcopy(template)
    entry['result']['workflow_comparison'] = {
        'mapping': mapping,
        'batch': candidate,
        'baseline': copy.deepcopy(template['baseline']),
        'max_signals': template['max_signals'],
    }
    presenter._results_dirty = True
    return entry


def comparison_text(result: dict[str, Any]) -> str:
    template = result.get('workflow_replay')
    comparison = result.get('workflow_comparison')
    if not template or not comparison:
        return ''
    baseline = comparison.get('baseline', template['baseline'])
    batch = comparison['batch']
    disp_name = _disp_label(batch.get('chart_type', template.get('chart_type', 'xbar_r')))
    lines = [
        'Workflow Replay',
        comparison['mapping'],
        '',
        f"Approved baseline: {baseline['worksheet']} / {baseline['variable']}",
        f"Batch: {batch['worksheet']} / {batch['variable']}",
        f"Subgroups: {baseline['subgroups']} -> {batch['subgroups']} ({batch['subgroups'] - baseline['subgroups']:+d})",
        f"Xbar signals: {baseline['xbar_signals']} -> {batch['xbar_signals']} ({batch['xbar_signals'] - baseline['xbar_signals']:+d})",
        f"{disp_name} signals: {baseline['disp_signals']} -> {batch['disp_signals']} ({batch['disp_signals'] - baseline['disp_signals']:+d})",
        f"Xbar center: {baseline['xbar_center']:g} -> {batch['xbar_center']:g} ({batch['xbar_center'] - baseline['xbar_center']:+g})",
        f"Within sigma: {baseline['within_sigma']:g} -> {batch['within_sigma']:g} ({batch['within_sigma'] - baseline['within_sigma']:+g})",
    ]
    count = int(batch['xbar_signals']) + int(batch['disp_signals'])
    maximum = comparison.get('max_signals', template['max_signals'])
    lines.append(f"Acceptance: {'Pass' if count <= maximum else 'Fail'}")
    return '\n'.join(lines)


class SubgroupReplayDialog(QDialog):
    """Map columns on the active worksheet to an approved subgroup replay template."""

    def __init__(self, window, baseline_entry: dict[str, Any]):
        super().__init__(window)
        self.window = window
        self.template = baseline_entry['result']['workflow_replay']
        self.saved_entry = None
        self.setWindowTitle('Replay Subgroup Chart on Current Worksheet')
        self.resize(520, 360)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        sheet = window.presenter.worksheet

        self.resp_combo = None
        self.fac_combo = None
        self.col_combos: list[QComboBox] = []

        if self.template['stacked']:
            self.resp_combo = QComboBox()
            for idx, col in enumerate(sheet.columns):
                if col.kind == 'number':
                    self.resp_combo.addItem(f'C{idx + 1} {col.name}', idx)
                    if col.name == self.template['columns'][0]:
                        self.resp_combo.setCurrentIndex(self.resp_combo.count() - 1)
            form.addRow('Batch measurement', self.resp_combo)
            if self.template['has_factor']:
                self.fac_combo = QComboBox()
                target_fac = self.template['columns'][1] if len(self.template['columns']) > 1 else ''
                for idx, col in enumerate(sheet.columns):
                    self.fac_combo.addItem(f'C{idx + 1} {col.name}', idx)
                    if col.name == target_fac:
                        self.fac_combo.setCurrentIndex(self.fac_combo.count() - 1)
                form.addRow('Subgroup ID column', self.fac_combo)
        else:
            num_cols = [(idx, col) for idx, col in enumerate(sheet.columns) if col.kind == 'number']
            for pos, base_name in enumerate(self.template['columns']):
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
                self.col_combos.append(combo)

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

        if self.resp_combo is not None:
            self.resp_combo.currentIndexChanged.connect(self.update_preview)
        if self.fac_combo is not None:
            self.fac_combo.currentIndexChanged.connect(self.update_preview)
        for combo in self.col_combos:
            combo.currentIndexChanged.connect(self.update_preview)
        self.update_preview()

    def _selection_kwargs(self) -> dict[str, Any]:
        if self.template['stacked']:
            return {
                'response_index': self.resp_combo.currentData() if self.resp_combo else None,
                'factor_index': self.fac_combo.currentData() if self.fac_combo else None,
                'indices': None,
            }
        return {
            'response_index': None,
            'factor_index': None,
            'indices': [combo.currentData() for combo in self.col_combos if combo.currentData() is not None],
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
