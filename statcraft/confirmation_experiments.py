"""Predeclared confirmation run sheet generation and RunID-aligned evaluation."""
import copy
import math
import numpy as np
from .model import Column, Worksheet, finite_number
from .optimizer import _encode_ols, _fit_model_bundle

try:
    from .operating_window import _finite_result
except ImportError:
    _finite_result = lambda x: x


def _find_predictor_value(factor_map, p_info):
    by_name = {str(k).casefold(): v for k, v in factor_map.items()}
    if p_info['name'].casefold() in by_name:
        return by_name[p_info['name'].casefold()]
    if str(p_info['index']) in factor_map:
        return factor_map[str(p_info['index'])]
    if p_info['index'] in factor_map:
        return factor_map[p_info['index']]
    raise ValueError(f"Setting is missing predictor '{p_info['name']}'.")


def _compute_prediction_intervals(bundle, pred_row, m_replicates, confidence):
    """Compute nominal fit, CI, individual PI (m=1), and confirmation-mean PI (m replicates)."""
    if bundle['action'] == 'fit_binary_logistic':
        from scipy import special, stats
        from .logistic import _encode as encode_logistic
        res = bundle['result']
        x = encode_logistic([pred_row], res['coding_information'], res['terms'])
        z = np.column_stack([np.ones(1), (x[:, 1:] - np.asarray(res['_centers'])) / np.asarray(res['_scales'])])
        eta = float((z @ np.asarray(res['_gamma']))[0])
        fit_val = float(special.expit(eta))
        cov = np.asarray(res['_covariance'])
        var_eta = max(0.0, float(np.einsum('ij,jk,ik->i', z, cov, z)[0]))
        se_eta = math.sqrt(var_eta)
        se_fit = fit_val * (1.0 - fit_val) * se_eta
        z_crit = float(stats.norm.isf((1.0 - confidence) / 2.0))
        ci_lo = float(special.expit(eta - z_crit * se_eta))
        ci_hi = float(special.expit(eta + z_crit * se_eta))
        # Binomial sampling spread for m Bernoulli trials plus model uncertainty
        se_m = math.sqrt(se_fit ** 2 + (fit_val * (1.0 - fit_val)) / max(1, m_replicates))
        se_1 = math.sqrt(se_fit ** 2 + fit_val * (1.0 - fit_val))
        return dict(
            fit=fit_val,
            residual_stdev=None,
            df_error=None,
            leverage=None,
            t_critical=z_crit,
            se_fit=float(se_fit),
            ci_low=ci_lo,
            ci_high=ci_hi,
            indiv_pi_low=max(0.0, fit_val - z_crit * se_1),
            indiv_pi_high=min(1.0, fit_val + z_crit * se_1),
            confirm_pi_low=max(0.0, fit_val - z_crit * se_m),
            confirm_pi_high=min(1.0, fit_val + z_crit * se_m),
        )

    from scipy import stats
    svd = bundle['svd']
    res = bundle['result']
    new_x = _encode_ols([pred_row], bundle['encode_action'], res)
    coded = (new_x - svd['means']) / svd['scales']
    fit_val = float((svd['mean_y'] + svd['unit'] * (coded @ svd['gamma']))[0])
    transformed = (coded @ svd['vh'].T) / svd['singular']
    leverage = float(1.0 / svd['n'] + np.sum(transformed * transformed, axis=1)[0])
    df_error = int(res.get('df_error', 0) or 0)
    stdev = res.get('residual_stdev')
    if res.get('status') == 'exact_fit' or df_error < 1 or stdev is None:
        raise ValueError(
            f"Model for {bundle['response_name']} has zero residual degrees of freedom; "
            'cannot predeclare confirmation prediction intervals.'
        )
    s = float(stdev)
    t_crit = float(stats.t.ppf((1.0 + confidence) / 2.0, df_error))
    se_fit = s * math.sqrt(leverage)
    delta_ci = t_crit * se_fit
    delta_1 = t_crit * s * math.sqrt(leverage + 1.0)
    delta_m = t_crit * s * math.sqrt(leverage + 1.0 / float(m_replicates))
    return dict(
        fit=fit_val,
        residual_stdev=s,
        df_error=df_error,
        leverage=leverage,
        t_critical=t_crit,
        se_fit=float(se_fit),
        ci_low=float(fit_val - delta_ci),
        ci_high=float(fit_val + delta_ci),
        indiv_pi_low=float(fit_val - delta_1),
        indiv_pi_high=float(fit_val + delta_1),
        confirm_pi_low=float(fit_val - delta_m),
        confirm_pi_high=float(fit_val + delta_m),
    )


def create_confirmation_plan(
    worksheet,
    operating_window_result,
    setting_keys=None,
    custom_settings=None,
    replicates=3,
    seed=42,
    confidence=0.95,
    sheet_name='Confirmation_Runs',
):
    """Create a randomized replicated confirmation run worksheet and predeclared acceptance criteria."""
    if not isinstance(operating_window_result, dict) or operating_window_result.get('analysis') != 'operating_window_3d':
        raise ValueError('Choose a valid 3D Operating Window result to plan confirmation runs.')
    if type(replicates) is not int or not 1 <= replicates <= 100:
        raise ValueError('Confirmation replicates m must be an integer between 1 and 100.')
    if type(seed) is not int or seed < 0:
        raise ValueError('Randomization seed must be a non-negative integer.')
    confidence = finite_number(confidence)
    if not 0.5 < confidence < 0.999:
        raise ValueError('Confirmation confidence level must lie strictly between 0.5 and 0.999.')
    if not isinstance(sheet_name, str) or not sheet_name.strip():
        raise ValueError('Enter a non-empty confirmation worksheet name.')

    keys = ['robust_setting'] if setting_keys is None and not custom_settings else list(setting_keys or [])
    chosen_settings = []
    seen_keys = set()
    for key in keys:
        cand = operating_window_result.get(key)
        if not isinstance(cand, dict) or 'factors' not in cand:
            raise ValueError(f"Operating window result does not contain '{key}'.")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        chosen_settings.append(dict(
            key=key,
            label=str(cand.get('label', key)),
            factors=dict(cand['factors']),
        ))

    if custom_settings:
        if not isinstance(custom_settings, list):
            raise ValueError('Custom confirmation settings must be a list of setting dictionaries.')
        for idx, item in enumerate(custom_settings, start=1):
            if not isinstance(item, dict) or 'factors' not in item:
                raise ValueError('Each custom confirmation setting requires a factors dictionary.')
            c_key = str(item.get('key') or f'custom_{idx}')
            while c_key in seen_keys:
                c_key = f'{c_key}_2'
            seen_keys.add(c_key)
            chosen_settings.append(dict(
                key=c_key,
                label=str(item.get('label') or f'Custom Setting {idx}'),
                factors=dict(item['factors']),
            ))

    if not chosen_settings:
        raise ValueError('Select at least one candidate setting for confirmation runs.')

    predictors = list(operating_window_result.get('predictors', []))
    responses = list(operating_window_result.get('responses', []))
    if not predictors or not responses:
        raise ValueError('Operating window result is missing predictor or response metadata.')

    bundles = [_fit_model_bundle(worksheet, r_meta['model_recipe']) for r_meta in responses]

    planned_settings = []
    run_items = []
    for s_entry in chosen_settings:
        resolved_factors = {}
        factor_by_index = {}
        for p_info in predictors:
            raw_val = _find_predictor_value(s_entry['factors'], p_info)
            if p_info['role'] == 'factor':
                val = str(raw_val)
            else:
                val = float(finite_number(raw_val))
            resolved_factors[p_info['name']] = val
            factor_by_index[p_info['index']] = val

        resp_criteria = []
        for r_meta, bundle in zip(responses, bundles):
            pred_row = [factor_by_index[p['index']] for p in bundle['predictors']]
            intervals = _compute_prediction_intervals(bundle, pred_row, replicates, confidence)
            lo = r_meta.get('lower')
            hi = r_meta.get('upper')
            resp_criteria.append(dict(
                response_index=r_meta['response_index'],
                response_name=r_meta['response_name'],
                lower=None if lo is None else float(lo),
                upper=None if hi is None else float(hi),
                target=r_meta.get('target'),
                replicates=int(replicates),
                confidence=float(confidence),
                **intervals,
            ))

        planned_settings.append(dict(
            key=s_entry['key'],
            label=s_entry['label'],
            factors=resolved_factors,
            responses=resp_criteria,
        ))
        for rep_i in range(1, replicates + 1):
            run_items.append(dict(
                setting_key=s_entry['key'],
                setting_label=s_entry['label'],
                replicate=rep_i,
                factors=resolved_factors,
            ))

    rng = np.random.default_rng(int(seed))
    perm = rng.permutation(len(run_items))
    randomized_runs = [run_items[int(idx)] for idx in perm]

    n_runs = len(randomized_runs)
    width = max(2, len(str(n_runs)))
    run_ids = []
    run_orders = []
    setting_labels = []
    setting_keys_col = []
    rep_col = []
    pred_cols_data = {p['name']: [] for p in predictors}

    for order_i, item in enumerate(randomized_runs, start=1):
        rid = f'CONF-{order_i:0{width}d}'
        item['run_id'] = rid
        item['run_order'] = order_i
        run_ids.append(rid)
        run_orders.append(float(order_i))
        setting_labels.append(item['setting_label'])
        setting_keys_col.append(item['setting_key'])
        rep_col.append(float(item['replicate']))
        for p in predictors:
            val = item['factors'][p['name']]
            pred_cols_data[p['name']].append(val)

    columns = [
        Column('RunID', 'text', run_ids),
        Column('RunOrder', 'number', run_orders),
        Column('Setting', 'text', setting_labels),
        Column('SettingKey', 'text', setting_keys_col),
        Column('Replicate', 'number', rep_col),
    ]
    used_names = {c.name.casefold() for c in columns}
    for p in predictors:
        kind = 'text' if p['role'] == 'factor' else 'number'
        col_name = p['name']
        while col_name.casefold() in used_names:
            col_name = f'{col_name}_Factor'
        used_names.add(col_name.casefold())
        columns.append(Column(col_name, kind, pred_cols_data[p['name']]))
    for r_meta in responses:
        col_name = r_meta['response_name']
        while col_name.casefold() in used_names:
            col_name = f'{col_name}_Obs'
        used_names.add(col_name.casefold())
        columns.append(Column(col_name, 'number', [None] * n_runs))

    ws = Worksheet(sheet_name.strip(), columns)

    plan_result = _finite_result(dict(
        analysis='confirmation_plan',
        title=f'Confirmation Run Plan ({ws.name})',
        worksheet_name=ws.name,
        source_title=operating_window_result.get('title', '3D Operating Window'),
        confidence=float(confidence),
        replicates=int(replicates),
        seed=int(seed),
        n_runs=n_runs,
        predictors=[dict(name=p['name'], role=p['role'], index=p['index']) for p in predictors],
        responses=[
            dict(
                response_index=r['response_index'],
                response_name=r['response_name'],
                lower=r.get('lower'),
                upper=r.get('upper'),
                target=r.get('target'),
            )
            for r in responses
        ],
        settings=planned_settings,
        runs=[
            dict(
                run_id=item['run_id'],
                run_order=item['run_order'],
                setting_key=item['setting_key'],
                setting_label=item['setting_label'],
                replicate=item['replicate'],
                factors=item['factors'],
            )
            for item in randomized_runs
        ],
        method='Randomized confirmation run sheet with predeclared confirmation-mean prediction intervals',
        method_notes=(
            f'Confirmation-mean PI accounts for both regression fit uncertainty at x0 and future sample mean variance '
            f'(s * sqrt(h + 1/m), m = {replicates}, {confidence * 100:.1f}% confidence).'
        ),
    ))
    return ws, plan_result


def _resolve_response_column(worksheet, response_name, explicit_idx=None):
    if explicit_idx is not None:
        if type(explicit_idx) is not int or not 0 <= explicit_idx < len(worksheet.columns):
            raise ValueError(f"Selected column index for response '{response_name}' does not exist.")
        col = worksheet.columns[explicit_idx]
        if col.kind != 'number':
            raise ValueError(f"Response measurement column '{col.name}' must be numeric.")
        return explicit_idx, col
    by_name = {c.name.strip().casefold(): (i, c) for i, c in enumerate(worksheet.columns)}
    for candidate in (response_name.strip().casefold(), f'{response_name.strip()}_obs'.casefold()):
        if candidate in by_name:
            idx, col = by_name[candidate]
            if col.kind != 'number':
                raise ValueError(f"Response measurement column '{col.name}' must be numeric.")
            return idx, col
    raise ValueError(f"Measurement worksheet is missing numeric response column '{response_name}'.")


def evaluate_confirmation_runs(plan_result, measurement_worksheet, response_column_map=None):
    """Evaluate observed confirmation runs aligned strictly by RunID against predeclared criteria."""
    if not isinstance(plan_result, dict) or plan_result.get('analysis') != 'confirmation_plan':
        raise ValueError('Choose a valid Confirmation Run Plan result.')
    runs = plan_result.get('runs', [])
    settings = plan_result.get('settings', [])
    if not runs or not settings:
        raise ValueError('Confirmation plan contains no planned runs.')

    col_by_name = {c.name.strip().casefold(): c for c in measurement_worksheet.columns}
    run_id_col = None
    for cand in ('runid', 'run_id', 'run id'):
        if cand in col_by_name:
            run_id_col = col_by_name[cand]
            break
    if run_id_col is None:
        raise ValueError("Measurement worksheet must contain a 'RunID' column for row alignment.")

    by_run_id = {}
    n_rows = measurement_worksheet.row_count
    for r in range(n_rows):
        raw_id = run_id_col.values[r] if r < len(run_id_col.values) else None
        rid = '' if raw_id is None else str(raw_id).strip()
        if not rid:
            raise ValueError(f'Measurement worksheet row {r + 1} has a blank or missing RunID.')
        if rid in by_run_id:
            raise ValueError(f"Duplicate RunID '{rid}' in measurement worksheet; RunIDs must be unique.")
        by_run_id[rid] = r

    planned_rids = [str(item['run_id']).strip() for item in runs]
    missing_rids = [rid for rid in planned_rids if rid not in by_run_id]
    if missing_rids:
        preview = ', '.join(missing_rids[:5])
        raise ValueError(f'Measurement worksheet is missing planned RunID(s): {preview}.')

    explicit_map = {}
    if response_column_map is not None:
        if not isinstance(response_column_map, dict):
            raise ValueError('Response column map must be a dictionary.')
        for k, v in response_column_map.items():
            explicit_map[str(k)] = int(v)

    # Resolve measurement columns per response
    resolved_resp_cols = {}
    for resp in plan_result.get('responses', []):
        r_name = resp['response_name']
        explicit_idx = explicit_map.get(r_name)
        if explicit_idx is None:
            explicit_idx = explicit_map.get(str(resp.get('response_index')))
        idx, col = _resolve_response_column(measurement_worksheet, r_name, explicit_idx=explicit_idx)
        resolved_resp_cols[r_name] = (idx, col)

    setting_evaluations = []
    comparison_rows = []
    all_confirmed = True
    any_confirmed = False

    for s_entry in settings:
        s_key = s_entry['key']
        s_label = s_entry['label']
        s_runs = [item for item in runs if item['setting_key'] == s_key]
        s_rids = [item['run_id'] for item in s_runs]

        resp_results = []
        s_confirmed = True
        for crit in s_entry['responses']:
            r_name = crit['response_name']
            col_idx, col = resolved_resp_cols[r_name]
            obs_vals = []
            for item in s_runs:
                rid = item['run_id']
                row_idx = by_run_id[rid]
                raw_v = col.values[row_idx] if row_idx < len(col.values) else None
                if raw_v is None:
                    raise ValueError(f"Missing measurement for '{r_name}' at RunID '{rid}'.")
                val = finite_number(raw_v)
                obs_vals.append(val)

            obs_mean = float(np.mean(obs_vals))
            obs_sd = float(np.std(obs_vals, ddof=1)) if len(obs_vals) >= 2 else None
            lo = crit.get('lower')
            hi = crit.get('upper')

            def _in_spec(v):
                if lo is not None and v < lo - 1e-12:
                    return False
                if hi is not None and v > hi + 1e-12:
                    return False
                return True

            mean_in_spec = _in_spec(obs_mean)
            all_in_spec = all(_in_spec(v) for v in obs_vals)
            mean_in_pi = crit['confirm_pi_low'] - 1e-12 <= obs_mean <= crit['confirm_pi_high'] + 1e-12
            all_in_indiv = all(crit['indiv_pi_low'] - 1e-12 <= v <= crit['indiv_pi_high'] + 1e-12 for v in obs_vals)

            if mean_in_spec and mean_in_pi:
                status = 'Confirmed'
            elif mean_in_spec and not mean_in_pi:
                status = 'Spec Pass / Model Drift'
            elif not mean_in_spec and mean_in_pi:
                status = 'Model Match / Out of Spec'
            else:
                status = 'Failed'

            passed = bool(mean_in_spec and mean_in_pi)
            if not passed:
                s_confirmed = False

            rec = dict(
                response_name=r_name,
                column_index=int(col_idx),
                column_name=col.name,
                m=len(obs_vals),
                fit=float(crit['fit']),
                ci_low=float(crit['ci_low']),
                ci_high=float(crit['ci_high']),
                confirm_pi_low=float(crit['confirm_pi_low']),
                confirm_pi_high=float(crit['confirm_pi_high']),
                indiv_pi_low=float(crit['indiv_pi_low']),
                indiv_pi_high=float(crit['indiv_pi_high']),
                lower=lo,
                upper=hi,
                target=crit.get('target'),
                observed_values=[float(v) for v in obs_vals],
                observed_run_ids=list(s_rids),
                observed_mean=obs_mean,
                observed_sd=obs_sd,
                residual=float(obs_mean - crit['fit']),
                mean_in_confirm_pi=bool(mean_in_pi),
                mean_in_spec=bool(mean_in_spec),
                all_runs_in_spec=bool(all_in_spec),
                all_runs_in_indiv_pi=bool(all_in_indiv),
                confirmed=passed,
                status=status,
            )
            resp_results.append(rec)
            comparison_rows.append(dict(setting_key=s_key, setting_label=s_label, **rec))

        all_confirmed = all_confirmed and s_confirmed
        any_confirmed = any_confirmed or s_confirmed
        setting_evaluations.append(dict(
            key=s_key,
            label=s_label,
            factors=dict(s_entry['factors']),
            confirmed=bool(s_confirmed),
            responses=resp_results,
        ))

    return _finite_result(dict(
        analysis='confirmation_evaluation',
        title=f"Confirmation Evaluation ({measurement_worksheet.name})",
        plan_title=plan_result.get('title', 'Confirmation Run Plan'),
        worksheet_name=measurement_worksheet.name,
        confidence=float(plan_result.get('confidence', 0.95)),
        replicates=int(plan_result.get('replicates', 1)),
        confirmed=bool(all_confirmed),
        any_confirmed=bool(any_confirmed),
        settings=setting_evaluations,
        comparisons=comparison_rows,
        method='RunID-aligned confirmation mean evaluation against predeclared spec limits and confirmation PI',
        method_notes=(
            'Measurements are matched strictly by RunID (independent of worksheet sort order) and checked against '
            'both engineering specifications and the predeclared confirmation-mean prediction interval.'
        ),
    ))
