"""Replay an approved Individuals and Moving Range analysis on a new batch."""
import copy

from .imr_investigation import run_summary


def approve(presenter, entry, limit):
    if presenter.result_stale(entry) is not False:
        raise ValueError('Rerun the chart before approving it as a baseline.')
    if type(limit) is not int or limit < 0:
        raise ValueError('The maximum signal count must be a nonnegative integer.')
    recipe = entry['recipe']['parameters']['settings']
    col = presenter.result_worksheet(entry).columns[recipe['variables'][0]]
    comparison = entry['result'].get('workflow_comparison')
    previous = entry['result'].get('workflow_replay')
    if comparison and previous:
        comparison.setdefault('baseline', copy.deepcopy(previous['baseline']))
        comparison.setdefault('max_signals', previous['max_signals'])
    entry['result']['workflow_replay'] = {
        'baseline': run_summary(entry), 'column': col.name,
        'unit': col.metadata.get('unit') or col.metadata.get('units'),
        'options': copy.deepcopy(entry['result']['options']), 'max_signals': limit,
    }
    presenter._results_dirty = True


def preview(presenter, template, index):
    if type(index) is not int or not 0 <= index < len(presenter.worksheet.columns):
        raise ValueError('Select a batch measurement column.')
    column = presenter.worksheet.columns[index]
    if column.kind != 'number':
        raise ValueError('Choose a numeric measurement column.')
    unit = column.metadata.get('unit') or column.metadata.get('units')
    if unit != template['unit']:
        raise ValueError(f"Batch unit {unit or '(unspecified)'} differs from baseline unit {template['unit'] or '(unspecified)'}.")
    from .imr_engine import parse_subgroup_omission
    omitted = parse_subgroup_omission(template['options'].get('omit_subgroups'))
    if omitted and max(omitted) > len(column.values):
        raise ValueError('A saved estimation exclusion refers to a row beyond the batch.')
    return f"{template['column']} → C{index + 1} {column.name}\nUnits: {unit or 'Unspecified'}\nObservations omitted from limit estimation: {sorted(omitted)}\nMaximum combined Individuals and Moving Range signals: {template['max_signals']}"


def replay(presenter, template, index):
    mapping = preview(presenter, template, index)
    entry = presenter.imr_chart({'variables': [index], 'options': copy.deepcopy(template['options'])})
    candidate = run_summary(entry)
    entry['result']['workflow_replay'] = copy.deepcopy(template)
    entry['result']['workflow_comparison'] = {'mapping': mapping, 'batch': candidate, 'baseline': copy.deepcopy(template['baseline']),
                                               'max_signals': template['max_signals']}
    presenter._results_dirty = True
    return entry


def comparison_text(result):
    template = result.get('workflow_replay')
    comparison = result.get('workflow_comparison')
    if not template or not comparison:
        return ''
    baseline, batch = comparison.get('baseline', template['baseline']), comparison['batch']
    lines = ['Workflow Replay', comparison['mapping'], '',
             f"Approved baseline: {baseline['worksheet']} / {baseline['variable']}",
             f"Batch: {batch['worksheet']} / {batch['variable']}"]
    for label, key in [('Individuals signals', 'i_signals'), ('Moving Range signals', 'mr_signals'),
                       ('Center', 'center'), ('Within sigma', 'within_sigma')]:
        lines.append(f'{label}: {baseline[key]:g} → {batch[key]:g} ({batch[key] - baseline[key]:+g})')
    count = batch['i_signals'] + batch['mr_signals']
    maximum = comparison.get('max_signals', template['max_signals'])
    lines.append(f"Acceptance: {'Pass' if count <= maximum else 'Fail'}")
    return '\n'.join(lines)
