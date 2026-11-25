"""Record investigation evidence alongside saved Individuals and Moving Range results."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPlainTextEdit,
    QVBoxLayout,
)

from .imr_trace import point_trace


def signals(result):
    individual = result.get('test_failures') or {row: [1] for row in result.get('i_signals', [])}
    return {('i', int(row)): list(rules) for row, rules in individual.items()} | {
        ('mr', int(row)): [1] for row in result.get('mr_signals', [])
    }


def run_summary(entry):
    result = entry['result']
    flagged = signals(result)
    return {
        'title': entry['title'],
        'worksheet': entry.get('worksheet_name', ''),
        'entry_id': entry.get('entry_id'),
        'variable': result['variable_name'],
        'observations': result['count'],
        'moving_ranges': sum(value is not None for value in result['moving_ranges']),
        'i_signals': sum(panel == 'i' for panel, row in flagged),
        'mr_signals': sum(panel == 'mr' for panel, row in flagged),
        'center': result['i_center'],
        'within_sigma': result['within_stdev'],
        'i_limits': [result['i_lcl'], result['i_ucl']],
        'mr_limits': [result['mr_lcl'], result['mr_ucl']],
        'options': copy.deepcopy(result['options']),
    }


def context_rows(sheet, rows):
    return [
        [row, [[f'C{index + 1} {column.name}', column.values[row - 1]]
               for index, column in enumerate(sheet.columns)
               if row <= len(column.values) and column.values[row - 1] is not None]]
        for row in rows
    ]


def format_investigation(result):
    panel = 'Individuals' if result['panel'] == 'i' else 'Moving Range'
    trace = result['trace']
    lines = [
        f'{panel}, worksheet row {result["row"]} · Test(s) {", ".join(map(str, result["rules"]))}',
        f'Plotted value: {trace["value"]} · {trace["method"]}',
        'Control limits: ' + ', '.join(f'{key}={value}' for key, value in trace['limits'].items()),
        '', 'Worksheet context captured at investigation time',
    ]
    for row, columns in result['context']:
        lines.append(f'Row {row}: ' + (' | '.join(f'{name}={value}' for name, value in columns) or 'No values'))
    for caption, key in [('Suspected cause', 'cause'), ('Supporting evidence', 'evidence'),
                         ('Corrective action', 'action')]:
        lines.extend(['', caption, result[key] or 'Pending'])
    lines.extend(['', 'Before and after'])
    for caption, key in [('Before', 'before'), ('After', 'after')]:
        summary = result[key]
        if summary is None:
            lines.append(f'{caption}: Pending')
            continue
        lines.extend([
            f'{caption}: {summary["title"]} ({summary["worksheet"]})',
            f'  Individuals signals: {summary["i_signals"]}/{summary["observations"]}',
            f'  Moving Range signals: {summary["mr_signals"]}/{summary["moving_ranges"]}',
            f'  Center: {summary["center"]:.6g} · Within sigma: {summary["within_sigma"]:.6g}',
            f'  Individuals limits: {summary["i_limits"]} · Moving Range limits: {summary["mr_limits"]}',
        ])
    if result['after'] is not None:
        lines.append('Counts use each saved chart’s own limits and tests.')
        if result['before']['options'] != result['after']['options']:
            lines.append('The saved chart options differ between runs.')
    return '\n'.join(lines)


class IMRInvestigationDialog(QDialog):
    def __init__(self, window, entry, investigation=None):
        super().__init__(window)
        self.window = window
        self.entry = entry
        self.investigation = investigation
        self.saved_entry = None
        self.setWindowTitle('Investigate I-MR Signal')
        self.resize(720, 680)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.signal = QComboBox()
        self.after = QComboBox()
        self.after.addItem('Pending', None)
        before = investigation['result']['before'] if investigation else run_summary(entry)
        for candidate in window.presenter.history:
            result = candidate.get('result', {})
            if (result.get('analysis') == 'imr_control' and result['variable_name'] == before['variable']
                    and candidate.get('entry_id') != before['entry_id']):
                label = f"{candidate['title']} · {candidate.get('worksheet_name', '')} · {candidate['time']}"
                self.after.addItem(label, candidate['entry_id'])
        if investigation:
            record = investigation['result']
            self.after_snapshot = record['after']
            if self.after_snapshot:
                self.after.insertItem(1, f"Saved comparison · {self.after_snapshot['worksheet']}", '')
                self.after.setCurrentIndex(1)
            self.signal.addItem(self._signal_label(record['panel'], record['row']))
            self.signal.setEnabled(False)
        else:
            self.after_snapshot = None
            for panel, row in sorted(signals(entry['result'])):
                self.signal.addItem(self._signal_label(panel, row), (panel, row))
        form.addRow('Signal', self.signal)
        form.addRow('After chart', self.after)
        self.notes = {}
        for label, key in [('Suspected cause', 'cause'), ('Supporting evidence', 'evidence'),
                           ('Corrective action', 'action')]:
            editor = QPlainTextEdit()
            editor.setMaximumHeight(60)
            if investigation:
                editor.setPlainText(investigation['result'][key])
            self.notes[key] = editor
            form.addRow(label, editor)
        layout.addLayout(form)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
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

    @staticmethod
    def _signal_label(panel, row):
        return f"{'Individuals' if panel == 'i' else 'Moving Range'} · row {row}"

    def record(self):
        presenter = self.window.presenter
        if self.investigation:
            record = copy.deepcopy(self.investigation['result'])
        else:
            if self.signal.currentData() is None:
                raise ValueError('This chart has no saved signal to investigate.')
            panel, row = self.signal.currentData()
            if presenter.result_stale(self.entry) is not False:
                raise ValueError('Rerun the chart on its source worksheet before capturing process context.')
            result = self.entry['result']
            trace = point_trace(result, panel, row)
            sheet = presenter.result_worksheet(self.entry)
            first = min(row - 2, trace['rows'][0][0])
            record = {
                'analysis': 'imr_investigation',
                'panel': panel,
                'row': row,
                'rules': signals(result)[panel, row],
                'trace': trace,
                'context': context_rows(sheet, range(max(1, first), min(row + 2, sheet.row_count) + 1)),
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
                signal_label = self._signal_label(record['panel'], record['row'])
                title = f"I-MR Investigation: {record['before']['variable']} ({signal_label})"
                self.saved_entry = presenter._record(title, record)
                self.saved_entry['worksheet_id'] = self.entry.get('worksheet_id')
                self.saved_entry['worksheet_name'] = self.entry.get('worksheet_name')
            presenter._results_dirty = True
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()
