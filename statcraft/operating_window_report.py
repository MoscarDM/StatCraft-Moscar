"""Structured report tables and plain-text formatting for 3D Operating Window & Confirmation runs."""
from .prediction_report import _display


def _bounds_str(lo, hi):
    if lo is not None and hi is not None:
        return f'[{_display(lo)}, {_display(hi)}]'
    if lo is not None:
        return f'>= {_display(lo)}'
    if hi is not None:
        return f'<= {_display(hi)}'
    return '*'


def _interval_str(lo, hi):
    if lo is None or hi is None:
        return '*'
    return f'({_display(lo)}, {_display(hi)})'


def _operating_window_sections(result):
    tables = []
    spec_rows = [
        [
            r.get('response_name', ''),
            r.get('model_title', ''),
            r.get('lower'),
            r.get('upper'),
            r.get('target'),
            str(r.get('goal', '')).title(),
        ]
        for r in result.get('responses', [])
    ]
    tables.append(('Response Specifications', ['Response', 'Source Model', 'Lower', 'Upper', 'Target', 'Goal'], spec_rows))

    drift_rows = [
        [
            p.get('name', ''),
            p.get('role', ''),
            _display(p.get('min')) if p.get('role') != 'factor' else ', '.join(map(str, p.get('levels', []))),
            _display(p.get('max')) if p.get('role') != 'factor' else '—',
            p.get('drift_delta', 0.0),
        ]
        for p in result.get('predictors', [])
    ]
    tables.append(('Factor Ranges & Drift Tolerances', ['Factor', 'Role', 'Min / Levels', 'Max', 'Drift (±)'], drift_rows))

    candidates = []
    for key in ('robust_setting', 'predicted_optimum', 'selected_setting'):
        c = result.get(key)
        if isinstance(c, dict):
            candidates.append(c)

    cand_rows = []
    pred_names = [p['name'] for p in result.get('predictors', [])]
    for c in candidates:
        f_vals = [c.get('factors', {}).get(name) for name in pred_names]
        cand_rows.append(
            [c.get('label', c.get('key', ''))]
            + f_vals
            + [
                'Yes' if c.get('nominal_feasible') else 'No',
                'Yes' if c.get('worst_case_feasible') else 'No',
                'Outside' if c.get('outside_design_region') else 'Inside',
                round(float(c.get('min_drift_std_margin', 0.0)), 4),
                c.get('limiting_response', ''),
            ]
        )
    tables.append((
        'Candidate Operating Settings',
        ['Candidate'] + pred_names + ['Nominal Feasible', 'Drift Feasible', 'Design Region', 'Min Drift Std Margin', 'Limiting Spec'],
        cand_rows,
    ))

    resp_rows = []
    conf_pct = f"{100.0 * result.get('confidence', 0.95):.7g}%"
    for c in candidates:
        for rr in c.get('responses', []):
            resp_rows.append([
                c.get('label', ''),
                rr.get('response_name', ''),
                _bounds_str(rr.get('lower'), rr.get('upper')),
                rr.get('fit'),
                _interval_str(rr.get('ci_low'), rr.get('ci_high')),
                f"[{_display(rr.get('drift_min'))}, {_display(rr.get('drift_max'))}]",
                round(float(rr.get('worst_drift_margin', 0.0)), 4),
                'Yes' if rr.get('drift_feasible') else 'No',
            ])
    tables.append((
        'Candidate Response Predictions & Drift Envelope',
        ['Candidate', 'Response', 'Spec Limits', 'Fit', f'{conf_pct} CI', 'Drift Range', 'Worst Drift Margin', 'Passes Drift'],
        resp_rows,
    ))

    ws = result.get('window_summary', {})
    summary_rows = [
        ['Grid Resolution', f"{result.get('grid_size')} × {result.get('grid_size')} ({ws.get('total_cells', 0)} points)"],
        ['Nominal Feasible (All / In Hull)', f"{ws.get('nominal_feasible_cells', 0)} / {ws.get('nominal_feasible_in_hull', 0)}"],
        ['Drift-Feasible (All / In Hull)', f"{ws.get('drift_feasible_cells', 0)} / {ws.get('drift_feasible_in_hull', 0)} ({ws.get('drift_feasible_pct', 0):.1f}%)"],
        ['Empty Operating Window', 'Yes' if result.get('empty_window') else 'No'],
    ]
    if result.get('warnings'):
        summary_rows.append(['Warnings', '; '.join(result['warnings'])])
    tables.append(('Operating Window Summary', ['Metric', 'Value'], summary_rows))
    scenario = result.get('sensitivity')
    if scenario:
        baseline = scenario['baseline_setting']
        fixed = result['selected_setting']
        recommendation = result['robust_setting']

        def decision(candidate):
            if candidate['outside_design_region'] and result['design_region_only']:
                return 'Outside design region'
            return 'Pass' if candidate['worst_case_feasible'] else 'Fail'

        def setting(candidate):
            return ', '.join(f"{name}={_display(value)}" for name, value in candidate['factors'].items())

        tables.insert(0, (
            f"Sensitivity to {scenario['factor']} drift",
            ['Decision or measure', 'Baseline', 'Scenario', 'Change'],
            [
                ['Drift tolerance (±)', scenario['baseline_drift'], scenario['scenario_drift'], 'Varied'],
                ['In-hull feasible points (% of grid)', scenario['baseline_window'], ws['drift_feasible_pct'],
                 f"{ws['drift_feasible_pct'] - scenario['baseline_window']:+.2f} pp"],
                ['Operating window', 'Empty' if scenario['baseline_empty'] else 'Available',
                 'Empty' if result['empty_window'] else 'Available',
                 'Changed' if scenario['baseline_empty'] != result['empty_window'] else 'Unchanged'],
                ['Original setting under drift', decision(baseline), decision(fixed),
                 'Changed' if decision(baseline) != decision(fixed) else 'Unchanged'],
                ['Limiting response at original setting', baseline['limiting_response'], fixed['limiting_response'],
                 'Changed' if baseline['limiting_response'] != fixed['limiting_response'] else 'Unchanged'],
                ['Best setting on grid', setting(baseline), setting(recommendation),
                 'Changed' if baseline['factors'] != recommendation['factors'] else 'Unchanged'],
                ['Best setting under drift', decision(baseline), decision(recommendation),
                 'Changed' if decision(baseline) != decision(recommendation) else 'Unchanged'],
            ],
        ))
    return tables


def _confirmation_plan_sections(result):
    tables = []
    pred_names = [p['name'] for p in result.get('predictors', [])]
    crit_rows = []
    conf_pct = f"{100.0 * result.get('confidence', 0.95):.7g}%"
    for s in result.get('settings', []):
        f_txt = ', '.join(f"{name}={_display(s['factors'].get(name))}" for name in pred_names)
        for rr in s.get('responses', []):
            crit_rows.append([
                s.get('label', ''),
                f_txt,
                rr.get('response_name', ''),
                rr.get('fit'),
                _interval_str(rr.get('confirm_pi_low'), rr.get('confirm_pi_high')),
                _interval_str(rr.get('indiv_pi_low'), rr.get('indiv_pi_high')),
                _bounds_str(rr.get('lower'), rr.get('upper')),
            ])
    tables.append((
        'Predeclared Acceptance Criteria',
        ['Setting', 'Factor Levels', 'Response', 'Fit', f'{conf_pct} Confirm Mean PI (m={result.get("replicates")})', f'{conf_pct} Indiv PI', 'Spec Limits'],
        crit_rows,
    ))

    run_rows = []
    for run in result.get('runs', []):
        f_vals = [run.get('factors', {}).get(name) for name in pred_names]
        run_rows.append([run.get('run_id'), run.get('run_order'), run.get('setting_label'), run.get('replicate')] + f_vals)
    tables.append(('Randomized Confirmation Run Order', ['RunID', 'RunOrder', 'Setting', 'Replicate'] + pred_names, run_rows))
    return tables


def _confirmation_eval_sections(result):
    tables = []
    conf_pct = f"{100.0 * result.get('confidence', 0.95):.7g}%"
    comp_rows = []
    for row in result.get('comparisons', []):
        comp_rows.append([
            row.get('setting_label', ''),
            row.get('response_name', ''),
            row.get('m'),
            row.get('fit'),
            row.get('observed_mean'),
            row.get('observed_sd'),
            _interval_str(row.get('confirm_pi_low'), row.get('confirm_pi_high')),
            _bounds_str(row.get('lower'), row.get('upper')),
            'Yes' if row.get('mean_in_confirm_pi') else 'No',
            'Yes' if row.get('mean_in_spec') else 'No',
            row.get('status', ''),
        ])
    tables.append((
        'Confirmation Results Comparison',
        ['Setting', 'Response', 'm', 'Predicted Fit', 'Observed Mean', 'Observed SD', f'{conf_pct} Confirm PI', 'Spec Limits', 'Mean in PI', 'Mean in Spec', 'Status'],
        comp_rows,
    ))

    verdict_rows = [
        ['Overall Confirmation Verdict', 'CONFIRMED' if result.get('confirmed') else 'NOT CONFIRMED'],
        ['Measurement Worksheet', result.get('worksheet_name', '')],
        ['Replicates per Setting (m)', result.get('replicates')],
        ['Confidence Level', conf_pct],
    ]
    tables.append(('Confirmation Summary', ['Metric', 'Value'], verdict_rows))
    return tables


def sections(result):
    """Return (title, headers, rows) tuples for Operating Window & Confirmation results."""
    analysis = result.get('analysis') if isinstance(result, dict) else None
    if analysis == 'operating_window_3d':
        return _operating_window_sections(result)
    if analysis == 'confirmation_plan':
        return _confirmation_plan_sections(result)
    if analysis == 'confirmation_evaluation':
        return _confirmation_eval_sections(result)
    return []


def text_report(result):
    """Render plain-text tabular summary for history / clipboard / export."""
    lines = []
    for title, headers, rows in sections(result):
        data = [[_display(v) for v in row] for row in rows]
        widths = [max(len(h), max((len(row[i]) for row in data), default=0)) for i, h in enumerate(headers)]
        lines += [title, '  '.join(h.ljust(w) for h, w in zip(headers, widths))]
        lines += ['  '.join(v.ljust(w) for v, w in zip(row, widths)) for row in data]
        lines.append('')
    if result.get('method_notes'):
        lines.append(str(result['method_notes']))
    lines.extend(str(w) for w in result.get('warnings', []))
    return '\n'.join(lines)
