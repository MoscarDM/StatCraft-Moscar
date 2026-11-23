from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPlainTextEdit,
    QSpinBox, QVBoxLayout,
)


def point_trace(result, panel, row):
    """Resolve a plotted point against the observations saved with the result."""
    observations = result['observations']
    if panel not in ('i', 'mr') or type(row) is not int or not 1 <= row <= len(observations):
        raise ValueError('Select an I-MR panel and a worksheet row in range.')
    values = observations if panel == 'i' else result['moving_ranges']
    span = 1 if panel == 'i' else result['span']
    rows = range(max(1, row - span + 1), row + 1)
    omitted = set(result.get('omit_subgroups', []))
    return {
        'value': values[row - 1],
        'limits': {label: result.get(f'{panel}_{key}') for label, key in
                   [('Lower', 'lcl'), ('Center', 'center'), ('Upper', 'ucl')]},
        'rows': [(n, observations[n - 1], n in omitted) for n in rows],
        'method': 'Saved observation' if panel == 'i' else f'Maximum minus minimum over {span} consecutive rows',
    }


def _humanize_key(key: str) -> str:
    special = {
        'k_sigma': 'K sigma',
        'sigma_z': 'Laney Sigma Z',
        'center': 'Center',
        'xbar_center': 'Xbar center',
        'disp_center': 'Dispersion center',
        'within_stdev': 'Within sigma',
        'within_sigma': 'Within sigma',
        'historical_mean': 'Historical mean',
        'historical_sigma': 'Historical sigma',
        'historical_param': 'Historical parameter',
        'estimation_method': 'Estimation method',
        'method': 'Method',
        'chart_type': 'Chart type',
        'span': 'Moving range span',
        'unbiasing': 'Unbiasing constants',
        'use_nelson': 'Nelson defaults',
        'display_upper': 'Display UCL',
        'display_lower': 'Display LCL',
        'omit_subgroups': 'Omitted subgroups',
        'omitted_subgroups': 'Omitted subgroups',
        'excluded_rows': 'Excluded rows',
        'tests': 'Active tests',
    }
    if key in special:
        return special[key]
    return key.replace('_', ' ').strip().capitalize()


def _format_scalar(value, key: str = '') -> str:
    if value is None:
        if key.startswith('historical_'):
            return 'Estimated'
        return 'None'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, float):
        return f'{value:.6g}'
    if isinstance(value, (list, tuple)):
        if not value:
            return 'None'
        return ', '.join(_format_scalar(v) for v in value)
    if isinstance(value, dict):
        if key == 'tests':
            active = []
            for tname, cfg in value.items():
                if isinstance(cfg, dict) and cfg.get('enabled'):
                    num = tname.replace('test', 'Test ')
                    k_val = cfg.get('k')
                    active.append(f'{num} (k={k_val})' if k_val is not None else num)
            return ', '.join(active) if active else 'None'
        parts = [f'{_humanize_key(str(k))}: {_format_scalar(v, str(k))}' for k, v in value.items()]
        return '; '.join(parts) if parts else 'None'
    return str(value)


def format_trace_fields(mapping: dict | None, empty_label: str = 'None') -> list[str]:
    if not isinstance(mapping, dict) or not mapping:
        return [empty_label]
    return [f'{_humanize_key(str(k))}: {_format_scalar(v, str(k))}' for k, v in mapping.items()]


class IMRTraceDialog(QDialog):
    def __init__(self, parent, entry, stale):
        super().__init__(parent)
        self.setWindowTitle('Trace I-MR Result')
        self.resize(620, 500)
        self.result = entry['result']
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Saved inputs from {entry.get('worksheet_name', 'worksheet')} · {self.result['variable_name']}"))
        if stale is True:
            layout.addWidget(QLabel('The current worksheet differs from the saved analysis.'))
        form = QFormLayout()
        self.panel = QComboBox()
        self.panel.addItem('Individuals', 'i')
        self.panel.addItem('Moving Range', 'mr')
        self.row = QSpinBox()
        self.row.setRange(1, len(self.result['observations']))
        form.addRow('Panel', self.panel)
        form.addRow('Worksheet row', self.row)
        layout.addLayout(form)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.panel.currentIndexChanged.connect(self.refresh)
        self.row.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        result = self.result
        trace = point_trace(result, self.panel.currentData(), self.row.value())
        value = trace['value'] if trace['value'] is not None else 'No plotted point'
        omitted = result.get('omit_subgroups', [])
        lines = [f"Value: {value}", f"Calculation: {trace['method']}", "", "Source rows"]
        for row, observation, is_omitted in trace['rows']:
            suffix = ' (omitted from limit estimation)' if is_omitted else ''
            lines.append(f"{row}: {observation if observation is not None else 'Missing'}{suffix}")
        missing = sum(v is None for v in result['observations'])
        lines.extend([
            '',
            f'Missing observations in run: {missing}',
            f"Rows omitted from limit estimation: {', '.join(map(str, omitted)) if omitted else 'None'}",
            '',
            'Control limits',
        ])
        lines.extend(f'{label}: {val if val is not None else "Hidden"}'
                     for label, val in trace['limits'].items())
        est_info = result.get('estimation_trace', {
            'method': result['estimation_method'], 'span': result['span'],
        })
        lines.extend(['', 'Limit estimation', *format_trace_fields(est_info), '', 'Saved analysis options', *format_trace_fields(result.get('options', {}))])
        self.details.setPlainText('\n'.join(lines))
