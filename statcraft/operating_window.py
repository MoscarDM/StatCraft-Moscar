"""3D Operating Window & Drift Robustness analysis across fitted worksheet models."""
import copy
import itertools
import math
import numpy as np
from .model import Column, Worksheet, finite_number
from .optimizer import (
    SUPPORTED_MODELS,
    _fit_model_bundle,
    _merge_predictors,
    _predict_bundle_rows,
    normalize_model_recipe,
)

GOALS = ('auto', 'maximize', 'minimize', 'target')


def _finite_result(value):
    if isinstance(value, dict):
        return {str(k): _finite_result(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_result(v) for v in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        val = float(value)
        if not math.isfinite(val):
            raise ValueError('Operating window arithmetic produced a nonfinite result.')
        return val
    return value


def create_chemical_operating_window_sample():
    """Create the 13-run CCD Chemical Process Operating Window demo worksheet."""
    rng = np.random.default_rng(2026)
    alpha = math.sqrt(2.0)
    coded_points = [
        (-1.0, -1.0),
        (1.0, -1.0),
        (-1.0, 1.0),
        (1.0, 1.0),
        (-alpha, 0.0),
        (alpha, 0.0),
        (0.0, -alpha),
        (0.0, alpha),
        (0.0, 0.0),
        (0.0, 0.0),
        (0.0, 0.0),
        (0.0, 0.0),
        (0.0, 0.0),
    ]
    temps = [round(170.0 + 15.0 * zt, 4) for zt, _ in coded_points]
    pressures = [round(3.0 + 1.0 * zp, 4) for _, zp in coded_points]
    yields = []
    viscosities = []
    for t_val, p_val in zip(temps, pressures):
        zt = (t_val - 170.0) / 15.0
        zp = (p_val - 3.0) / 1.0
        y_true = 90.2 + 3.2 * zt + 1.4 * zp - 1.6 * zt * zt - 1.2 * zp * zp - 0.5 * zt * zp
        v_true = 22.3 - 2.8 * zt + 1.0 * zp - 1.6 * zt * zt - 0.4 * zp * zp - 0.3 * zt * zp
        yields.append(round(float(y_true + rng.normal(0.0, 0.22)), 4))
        viscosities.append(round(float(v_true + rng.normal(0.0, 0.18)), 4))
    return Worksheet(
        'Chemical_Operating_Window',
        [
            Column('Temp', 'number', temps),
            Column('Pressure', 'number', pressures),
            Column('Yield', 'number', yields),
            Column('Viscosity', 'number', viscosities),
        ],
    )


def chemical_operating_window_defaults(yield_recipe, viscosity_recipe):
    """Return flagship Yield & Viscosity specification bounds and drift tolerances."""
    specs = [
        dict(
            model_recipe=copy.deepcopy(yield_recipe),
            lower=86.0,
            upper=None,
            target=91.5,
            goal='maximize',
        ),
        dict(
            model_recipe=copy.deepcopy(viscosity_recipe),
            lower=18.0,
            upper=26.0,
            target=22.0,
            goal='target',
        ),
    ]
    options = dict(
        grid_size=21,
        confidence=0.95,
        primary_response_index=0,
        primary_goal='maximize',
        drifts=[{'index': 0, 'delta': 3.0}, {'index': 1, 'delta': 0.15}],
        design_region_only=True,
    )
    return specs, options


def simulate_chemical_confirmation_responses(run_sheet, seed=101):
    """Simulate physical confirmation runs on Temp/Pressure using the true chemical response surface."""
    names = {c.name.strip().casefold(): i for i, c in enumerate(run_sheet.columns)}
    if 'temp' not in names or 'pressure' not in names:
        raise ValueError("Confirmation worksheet must contain 'Temp' and 'Pressure' columns.")
    t_col = run_sheet.columns[names['temp']]
    p_col = run_sheet.columns[names['pressure']]
    rng = np.random.default_rng(int(seed))
    y_vals = []
    v_vals = []
    for r in range(run_sheet.row_count):
        t_raw = t_col.values[r] if r < len(t_col.values) else None
        p_raw = p_col.values[r] if r < len(p_col.values) else None
        if t_raw is None or p_raw is None:
            raise ValueError('All confirmation runs require numeric Temp and Pressure values.')
        zt = (float(t_raw) - 170.0) / 15.0
        zp = (float(p_raw) - 3.0) / 1.0
        y_true = 90.2 + 3.2 * zt + 1.4 * zp - 1.6 * zt * zt - 1.2 * zp * zp - 0.5 * zt * zp
        v_true = 22.3 - 2.8 * zt + 1.0 * zp - 1.6 * zt * zt - 0.4 * zp * zp - 0.3 * zt * zp
        y_vals.append(round(float(y_true + rng.normal(0.0, 0.25)), 4))
        v_vals.append(round(float(v_true + rng.normal(0.0, 0.20)), 4))

    for col_name, vals in (('Yield', y_vals), ('Viscosity', v_vals)):
        key = col_name.casefold()
        if key in names:
            col = run_sheet.columns[names[key]]
            col.kind = 'number'
            col.values = vals
            col.metadata.pop('auto_type', None)
        else:
            run_sheet.columns.append(Column(col_name, 'number', vals))
    return run_sheet


def _normalize_drifts(drifts):
    if drifts is None:
        return []
    items = []
    if isinstance(drifts, dict):
        for k, v in drifts.items():
            idx = int(k)
            delta = finite_number(v)
            if delta < 0.0:
                raise ValueError('Drift tolerances must be non-negative.')
            items.append({'index': idx, 'delta': float(delta)})
    elif isinstance(drifts, list):
        for item in drifts:
            if not isinstance(item, dict) or 'index' not in item or 'delta' not in item:
                raise ValueError('Each drift entry requires index and delta.')
            idx = item['index']
            if type(idx) is not int or idx < 0:
                raise ValueError('Drift column index must be a non-negative integer.')
            delta = finite_number(item['delta'])
            if delta < 0.0:
                raise ValueError('Drift tolerances must be non-negative.')
            items.append({'index': idx, 'delta': float(delta)})
    else:
        raise ValueError('Drift tolerances must be a list or mapping.')
    seen = set()
    cleaned = []
    for item in items:
        if item['index'] in seen:
            raise ValueError('Duplicate drift tolerance for the same predictor column.')
        seen.add(item['index'])
        cleaned.append(item)
    return sorted(cleaned, key=lambda d: d['index'])


def _normalize_holds(holds):
    if holds is None:
        return []
    if not isinstance(holds, list):
        raise ValueError('Hold settings must be provided as a list.')
    seen = set()
    cleaned = []
    for item in holds:
        if not isinstance(item, dict) or 'index' not in item or 'value' not in item:
            raise ValueError('Each hold entry requires index and value.')
        idx = item['index']
        if type(idx) is not int or idx < 0:
            raise ValueError('Hold column index must be a non-negative integer.')
        if idx in seen:
            raise ValueError('Duplicate hold value for the same predictor column.')
        seen.add(idx)
        val = item['value']
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float, str)):
            raise ValueError('Hold values must be numbers or category strings.')
        if isinstance(val, (int, float)):
            val = float(finite_number(val))
        cleaned.append({'index': idx, 'value': val})
    return sorted(cleaned, key=lambda h: h['index'])


def operating_window_settings(options=None):
    """Validate and normalize 3D Operating Window configuration options."""
    opts = {} if options is None else dict(options)
    grid_size = opts.get('grid_size', 21)
    if type(grid_size) is not int or not 5 <= grid_size <= 45:
        raise ValueError('Grid resolution must be an integer between 5 and 45.')
    confidence = finite_number(opts.get('confidence', 0.95))
    if not 0.5 < confidence < 0.999:
        raise ValueError('Confidence level must lie strictly between 0.5 and 0.999.')
    primary_idx = opts.get('primary_response_index', 0)
    if type(primary_idx) is not int or primary_idx < 0:
        raise ValueError('Primary response index must be a non-negative integer.')
    primary_goal = opts.get('primary_goal', 'auto')
    if primary_goal not in GOALS:
        raise ValueError('Primary goal must be auto, maximize, minimize, or target.')
    design_region_only = bool(opts.get('design_region_only', True))
    drifts = _normalize_drifts(opts.get('drifts'))
    holds = _normalize_holds(opts.get('holds'))

    norm = dict(
        grid_size=int(grid_size),
        confidence=float(confidence),
        primary_response_index=int(primary_idx),
        primary_goal=primary_goal,
        drifts=drifts,
        holds=holds,
        design_region_only=design_region_only,
    )
    for axis_key in ('x_range', 'y_range'):
        rng = opts.get(axis_key)
        if rng is not None:
            if not isinstance(rng, (list, tuple)) or len(rng) != 2:
                raise ValueError(f'{axis_key} must contain [min, max].')
            lo, hi = finite_number(rng[0]), finite_number(rng[1])
            if lo >= hi:
                raise ValueError(f'{axis_key} minimum must be strictly less than maximum.')
            norm[axis_key] = [float(lo), float(hi)]
    sel = opts.get('selected_setting')
    if sel is not None:
        if not isinstance(sel, dict):
            raise ValueError('Selected candidate setting must be a factor-value mapping.')
        cleaned_sel = {}
        for k, v in sel.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cleaned_sel[str(k)] = float(finite_number(v))
            elif isinstance(v, str):
                cleaned_sel[str(k)] = v
            else:
                raise ValueError('Selected candidate setting values must be numeric or text.')
        norm['selected_setting'] = cleaned_sel
    return norm


def normalize_window_response_spec(worksheet, item):
    """Validate and normalize one response specification with LSL/USL bounds."""
    if not isinstance(item, dict):
        raise ValueError('Each response specification must be a dictionary.')
    if 'model_recipe' not in item:
        raise ValueError('Each response specification requires model_recipe.')
    recipe = normalize_model_recipe(item['model_recipe'])
    if recipe['action'] not in SUPPORTED_MODELS:
        raise ValueError('Choose a supported source model for the operating window.')
    bundle = _fit_model_bundle(worksheet, recipe)

    raw_lo = item.get('lower')
    raw_hi = item.get('upper')
    raw_target = item.get('target')
    lower = None if raw_lo is None or raw_lo == '' else float(finite_number(raw_lo))
    upper = None if raw_hi is None or raw_hi == '' else float(finite_number(raw_hi))
    target = None if raw_target is None or raw_target == '' else float(finite_number(raw_target))
    if lower is None and upper is None:
        raise ValueError(f"{bundle['response_name']}: Specify at least one specification limit (Lower or Upper).")
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError(f"{bundle['response_name']}: Lower specification limit must be strictly less than Upper.")
    if bundle['is_probability']:
        if lower is not None and not 0.0 <= lower <= 1.0:
            raise ValueError(f"{bundle['response_name']}: Probability lower limit must lie within [0, 1].")
        if upper is not None and not 0.0 <= upper <= 1.0:
            raise ValueError(f"{bundle['response_name']}: Probability upper limit must lie within [0, 1].")
    if lower is not None and upper is not None and target is not None and not (lower <= target <= upper):
        raise ValueError(f"{bundle['response_name']}: Target must lie within [Lower, Upper].")

    goal = item.get('goal')
    if goal is None:
        if lower is not None and upper is not None:
            goal = 'target'
        elif lower is not None:
            goal = 'maximize'
        else:
            goal = 'minimize'
    if goal not in ('maximize', 'minimize', 'target'):
        raise ValueError('Response spec goal must be maximize, minimize, or target.')
    if target is None:
        if lower is not None and upper is not None:
            target = 0.5 * (lower + upper)
        elif lower is not None:
            target = lower
        else:
            target = upper

    return dict(
        model_recipe=recipe,
        response_index=bundle['response_index'],
        response_name=bundle['response_name'],
        model_title=bundle['model_title'],
        lower=lower,
        upper=upper,
        target=float(target),
        goal=goal,
    ), bundle


def _convex_hull_2d(points):
    """Return CCW vertices of the 2D convex hull using Andrew's monotone chain."""
    pts = sorted({(round(float(x), 12), round(float(y), 12)) for x, y in points})
    if len(pts) <= 2:
        return [list(pt) for pt in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for pt in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], pt) <= 0.0:
            lower.pop()
        lower.append(pt)
    upper = []
    for pt in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], pt) <= 0.0:
            upper.pop()
        upper.append(pt)
    hull = lower[:-1] + upper[:-1]
    return [[float(x), float(y)] for x, y in hull]


def _point_in_hull_2d(x, y, hull, tol=1e-9):
    """Return True if (x, y) lies inside or on the boundary of a CCW 2D convex hull."""
    if not hull:
        return True
    if len(hull) == 1:
        return abs(x - hull[0][0]) <= tol and abs(y - hull[0][1]) <= tol
    if len(hull) == 2:
        (x0, y0), (x1, y1) = hull[0], hull[1]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length <= tol:
            return math.hypot(x - x0, y - y0) <= tol
        cross = abs((x - x0) * dy - (y - y0) * dx) / length
        dot = (x - x0) * dx + (y - y0) * dy
        return cross <= tol and -tol * length <= dot <= length * length + tol * length
    xs = [pt[0] for pt in hull]
    ys = [pt[1] for pt in hull]
    scale = max(1.0, max(xs) - min(xs), max(ys) - min(ys))
    eps = tol * scale
    for i in range(len(hull)):
        x0, y0 = hull[i]
        x1, y1 = hull[(i + 1) % len(hull)]
        if (x1 - x0) * (y - y0) - (y1 - y0) * (x - x0) < -eps:
            return False
    return True


def _raw_margin(y_val, spec):
    lo = spec['lower']
    hi = spec['upper']
    if lo is not None and hi is not None:
        return min(y_val - lo, hi - y_val)
    if lo is not None:
        return y_val - lo
    return hi - y_val


def _response_scale(spec, bundle):
    lo = spec['lower']
    hi = spec['upper']
    if lo is not None and hi is not None:
        return max(0.5 * (hi - lo), 1e-6)
    res = bundle['result']
    stdev = res.get('residual_stdev') or 0.0
    obs_span = max(0.0, bundle['observed_max'] - bundle['observed_min'])
    if stdev and stdev > 1e-9:
        return float(stdev)
    return max(0.25 * obs_span, 1.0)


def _drift_offsets(active_drifts):
    """Generate hypercube drift vectors to evaluate worst-case factor drift."""
    if not active_drifts:
        return [{}]
    n = len(active_drifts)
    if n <= 3:
        choices = [(-d['delta'], 0.0, d['delta']) if d['delta'] > 0 else (0.0,) for d in active_drifts]
        combos = [(0.0,) * n] + list(itertools.product(*choices))
    elif n <= 6:
        combos = [(0.0,) * n] + list(itertools.product(*[(-d['delta'], d['delta']) if d['delta'] > 0 else (0.0,) for d in active_drifts]))
    else:
        combos = [(0.0,) * n]
        for k in range(n):
            if active_drifts[k]['delta'] > 0:
                for sign in (-1.0, 1.0):
                    vec = [0.0] * n
                    vec[k] = sign * active_drifts[k]['delta']
                    combos.append(tuple(vec))
        rng = np.random.default_rng(7)
        for _ in range(32):
            combos.append(tuple(float(rng.choice([-d['delta'], d['delta']])) for d in active_drifts))
    unique = []
    seen = set()
    for vec in combos:
        key = tuple(round(v, 10) for v in vec)
        if key in seen:
            continue
        seen.add(key)
        unique.append({d['index']: float(val) for d, val in zip(active_drifts, vec)})
    return unique


def _build_bundle_rows(base_settings, bundle):
    """Map full predictor dicts to the exact predictor order of one model bundle."""
    return [[row_map[p['index']] for p in bundle['predictors']] for row_map in base_settings]


def _score_primary(z_val, goal, target):
    if goal == 'minimize':
        return -float(z_val)
    if goal == 'target':
        return -abs(float(z_val) - float(target))
    return float(z_val)


def evaluate_operating_window(worksheet, response_specs, x_index, y_index, options=None):
    """Evaluate a 3D operating window, robustness under drift, and candidate settings."""
    if not isinstance(response_specs, list) or not 1 <= len(response_specs) <= 8:
        raise ValueError('Select 1–8 fitted response models for the 3D Operating Window.')
    opts = operating_window_settings(options)
    if opts['primary_response_index'] >= len(response_specs):
        raise ValueError('Primary response index exceeds the selected responses.')

    norm_specs = []
    bundles = []
    for item in response_specs:
        spec, bundle = normalize_window_response_spec(worksheet, item)
        norm_specs.append(spec)
        bundles.append(bundle)

    resp_cols = [s['response_index'] for s in norm_specs]
    if len(set(resp_cols)) != len(resp_cols):
        raise ValueError('Duplicate response columns in Operating Window specification.')

    merged = _merge_predictors(bundles, {'constraints': [], 'starting_values': []})
    pred_by_idx = {p['index']: p for p in merged}
    cont_preds = [p for p in merged if p['role'] == 'covariate']
    if len(cont_preds) < 2:
        raise ValueError('3D Operating Window requires at least two shared or active continuous predictors.')

    if type(x_index) is not int or type(y_index) is not int or x_index == y_index:
        raise ValueError('Select two distinct continuous predictors for X Axis and Y Axis.')
    if x_index not in pred_by_idx or y_index not in pred_by_idx:
        raise ValueError('X Axis and Y Axis must be predictors in the selected models.')
    if pred_by_idx[x_index]['role'] != 'covariate' or pred_by_idx[y_index]['role'] != 'covariate':
        raise ValueError('X Axis and Y Axis must both be continuous numeric predictors.')

    hold_map = {}
    for h in opts['holds']:
        idx = h['index']
        if idx not in pred_by_idx:
            raise ValueError('Hold setting references a column that is not a predictor in these models.')
        if idx in (x_index, y_index):
            raise ValueError('Plotted X and Y axes cannot also have fixed hold values.')
        p_info = pred_by_idx[idx]
        if p_info['role'] == 'factor':
            if h['value'] not in p_info['levels']:
                raise ValueError(f"Hold value for {p_info['name']} must be an observed factor level.")
            hold_map[idx] = h['value']
        else:
            if isinstance(h['value'], str):
                raise ValueError(f"Hold value for continuous predictor {p_info['name']} must be numeric.")
            hold_map[idx] = float(h['value'])

    base_predictors = {}
    hold_summary = []
    for p_info in merged:
        idx = p_info['index']
        if idx in (x_index, y_index):
            continue
        if idx in hold_map:
            val = hold_map[idx]
        elif p_info['role'] == 'factor':
            val = p_info['levels'][0]
        else:
            val = 0.5 * (float(p_info['observed_min']) + float(p_info['observed_max']))
        base_predictors[idx] = val
        hold_summary.append(dict(index=idx, name=p_info['name'], role=p_info['role'], value=val))

    drift_map = {}
    for d in opts['drifts']:
        idx = d['index']
        if idx not in pred_by_idx:
            raise ValueError('Drift tolerance references a column that is not a model predictor.')
        if pred_by_idx[idx]['role'] != 'covariate':
            raise ValueError('Drift tolerances can only be applied to continuous predictors.')
        drift_map[idx] = d['delta']
    active_drifts = [
        {'index': p['index'], 'name': p['name'], 'delta': float(drift_map.get(p['index'], 0.0))}
        for p in cont_preds
        if drift_map.get(p['index'], 0.0) > 0.0
    ]

    x_info = pred_by_idx[x_index]
    y_info = pred_by_idx[y_index]
    x_lo, x_hi = opts.get('x_range', [float(x_info['observed_min']), float(x_info['observed_max'])])
    y_lo, y_hi = opts.get('y_range', [float(y_info['observed_min']), float(y_info['observed_max'])])
    if x_lo >= x_hi or y_lo >= y_hi:
        raise ValueError('Predictor plotting ranges must have non-zero span.')

    g = opts['grid_size']
    x_grid = [float(v) for v in np.linspace(x_lo, x_hi, g)]
    y_grid = [float(v) for v in np.linspace(y_lo, y_hi, g)]

    # Build 2D convex hull from training rows across bundles for design-region checking
    train_xy = []
    for bundle in bundles:
        col_x = worksheet.columns[x_index]
        col_y = worksheet.columns[y_index]
        for r in bundle['result']['row_indices']:
            xv = col_x.values[r]
            yv = col_y.values[r]
            if xv is not None and yv is not None:
                train_xy.append((float(xv), float(yv)))
    design_hull = _convex_hull_2d(train_xy)

    held_cont_outside = False
    for p_info in cont_preds:
        idx = p_info['index']
        if idx in base_predictors:
            hv = float(base_predictors[idx])
            if hv < float(p_info['observed_min']) - 1e-9 or hv > float(p_info['observed_max']) + 1e-9:
                held_cont_outside = True
                break

    # Evaluate nominal grid + drift hypercube in bulk
    offsets = _drift_offsets(active_drifts)
    nominal_rows = []
    outside_region_grid = []
    for r_i, y_val in enumerate(y_grid):
        out_row = []
        for c_i, x_val in enumerate(x_grid):
            row_dict = dict(base_predictors)
            row_dict[x_index] = x_val
            row_dict[y_index] = y_val
            nominal_rows.append(row_dict)
            outside = held_cont_outside or (not _point_in_hull_2d(x_val, y_val, design_hull))
            out_row.append(bool(outside))
        outside_region_grid.append(out_row)

    all_rows = []
    for off in offsets:
        for base_row in nominal_rows:
            if not off:
                all_rows.append(base_row)
            else:
                shifted = dict(base_row)
                for d_idx, delta in off.items():
                    shifted[d_idx] = float(shifted[d_idx]) + delta
                all_rows.append(shifted)

    # Batch predict per response model across all offsets x grid points
    n_grid = len(nominal_rows)
    n_off = len(offsets)
    scales = [_response_scale(spec, bnd) for spec, bnd in zip(norm_specs, bundles)]
    preds_by_resp = []
    for bnd in bundles:
        b_rows = _build_bundle_rows(all_rows, bnd)
        p_out = _predict_bundle_rows(bnd, b_rows, confidence=opts['confidence'], side='two_sided', compute_intervals=False)
        fits = np.asarray([p['fit'] for p in p_out], dtype=float).reshape((n_off, n_grid))
        preds_by_resp.append(fits)

    prim_idx = opts['primary_response_index']
    prim_spec = norm_specs[prim_idx]
    prim_goal = prim_spec['goal'] if opts['primary_goal'] == 'auto' else opts['primary_goal']

    z_grid = []
    status_grid = []
    nominal_margin_grid = []
    drift_margin_grid = []
    limiting_grid = []

    drift_feasible_cells = []
    nominal_feasible_cells = []
    all_cells = []

    for idx_flat in range(n_grid):
        r_i, c_i = divmod(idx_flat, g)
        if c_i == 0:
            z_grid.append([])
            status_grid.append([])
            nominal_margin_grid.append([])
            drift_margin_grid.append([])
            limiting_grid.append([])
        outside = outside_region_grid[r_i][c_i]
        prim_fit = float(preds_by_resp[prim_idx][0, idx_flat])
        z_grid[r_i].append(prim_fit)

        nom_std_min = float('inf')
        drift_std_min = float('inf')
        lim_name = norm_specs[0]['response_name']
        for resp_k, (spec, sc, mat) in enumerate(zip(norm_specs, scales, preds_by_resp)):
            y_nom = float(mat[0, idx_flat])
            nom_std = _raw_margin(y_nom, spec) / sc
            if nom_std < nom_std_min:
                nom_std_min = nom_std
            worst_raw = min(_raw_margin(float(mat[o_i, idx_flat]), spec) for o_i in range(n_off))
            drift_std = worst_raw / sc
            if drift_std < drift_std_min:
                drift_std_min = drift_std
                lim_name = spec['response_name']

        if drift_std_min >= 0.0:
            cell_status = 'drift_feasible'
        elif nom_std_min >= 0.0:
            cell_status = 'nominal_only'
        else:
            cell_status = 'out_of_spec'

        status_grid[r_i].append(cell_status)
        nominal_margin_grid[r_i].append(float(nom_std_min))
        drift_margin_grid[r_i].append(float(drift_std_min))
        limiting_grid[r_i].append(lim_name)

        cell_rec = dict(
            r=r_i,
            c=c_i,
            x=x_grid[c_i],
            y=y_grid[r_i],
            z=prim_fit,
            outside=outside,
            status=cell_status,
            nom_margin=float(nom_std_min),
            drift_margin=float(drift_std_min),
            prim_score=_score_primary(prim_fit, prim_goal, prim_spec['target']),
        )
        all_cells.append(cell_rec)
        if nom_std_min >= 0.0:
            nominal_feasible_cells.append(cell_rec)
        if drift_std_min >= 0.0:
            drift_feasible_cells.append(cell_rec)

    n_drift_feasible_in = sum(1 for c in drift_feasible_cells if not c['outside'])
    n_nominal_feasible_in = sum(1 for c in nominal_feasible_cells if not c['outside'])
    n_drift_feasible_all = len(drift_feasible_cells)
    n_nominal_feasible_all = len(nominal_feasible_cells)

    warnings = []
    # Candidate selection
    def _pick_robust():
        pool_in = [c for c in drift_feasible_cells if not c['outside']]
        if pool_in:
            return max(pool_in, key=lambda c: (c['drift_margin'], c['prim_score'])), False
        if not opts['design_region_only'] and drift_feasible_cells:
            warnings.append('Robust setting lies outside the convex hull of design runs.')
            return max(drift_feasible_cells, key=lambda c: (c['drift_margin'], c['prim_score'])), False
        pool_fb = [c for c in all_cells if not c['outside']] if opts['design_region_only'] else all_cells
        if not pool_fb:
            pool_fb = all_cells
        warnings.append('No grid point remains within all specifications across the full drift box (empty operating window); reporting best least-infeasible compromise.')
        return max(pool_fb, key=lambda c: (c['drift_margin'], c['nom_margin'], c['prim_score'])), True

    def _pick_predicted_optimum():
        pool_in = [c for c in nominal_feasible_cells if not c['outside']]
        if pool_in:
            return max(pool_in, key=lambda c: (c['prim_score'], c['nom_margin']))
        if not opts['design_region_only'] and nominal_feasible_cells:
            return max(nominal_feasible_cells, key=lambda c: (c['prim_score'], c['nom_margin']))
        pool_fb = [c for c in all_cells if not c['outside']] if opts['design_region_only'] else all_cells
        if not pool_fb:
            pool_fb = all_cells
        return max(pool_fb, key=lambda c: (c['nom_margin'], c['prim_score']))

    robust_cell, empty_window = _pick_robust()
    nom_opt_cell = _pick_predicted_optimum()

    def _evaluate_candidate(label, key_name, factor_vals):
        x_pt = float(factor_vals[x_index])
        y_pt = float(factor_vals[y_index])
        outside = held_cont_outside or (not _point_in_hull_2d(x_pt, y_pt, design_hull))
        resp_details = []
        nom_margins = []
        drift_margins = []
        worst_lim = norm_specs[0]['response_name']
        worst_std = float('inf')

        shifted_rows = []
        for off in offsets:
            s_row = dict(factor_vals)
            for d_idx, delta in off.items():
                s_row[d_idx] = float(s_row[d_idx]) + delta
            shifted_rows.append(s_row)

        for spec, sc, bnd in zip(norm_specs, scales, bundles):
            nom_row = _build_bundle_rows([factor_vals], bnd)
            ci_out = _predict_bundle_rows(bnd, nom_row, confidence=opts['confidence'], side='two_sided', compute_intervals=True)[0]
            drift_rows = _build_bundle_rows(shifted_rows, bnd)
            dr_out = _predict_bundle_rows(bnd, drift_rows, confidence=opts['confidence'], side='two_sided', compute_intervals=False)
            dr_fits = [float(item['fit']) for item in dr_out]
            fit_nom = float(ci_out['fit'])
            nom_raw = _raw_margin(fit_nom, spec)
            nom_std = nom_raw / sc
            w_min = float(min(dr_fits))
            w_max = float(max(dr_fits))
            drift_raw = min(_raw_margin(fv, spec) for fv in dr_fits)
            drift_std = drift_raw / sc
            nom_margins.append(nom_std)
            drift_margins.append(drift_std)
            if drift_std < worst_std:
                worst_std = drift_std
                worst_lim = spec['response_name']

            resp_details.append(dict(
                response_index=spec['response_index'],
                response_name=spec['response_name'],
                lower=spec['lower'],
                upper=spec['upper'],
                target=spec['target'],
                fit=fit_nom,
                se_fit=ci_out['se_fit'],
                ci_low=ci_out['ci_low'],
                ci_high=ci_out['ci_high'],
                pi_low=ci_out['pi_low'],
                pi_high=ci_out['pi_high'],
                drift_min=w_min,
                drift_max=w_max,
                nominal_margin=float(nom_raw),
                nominal_std_margin=float(nom_std),
                worst_drift_margin=float(drift_raw),
                worst_drift_std_margin=float(drift_std),
                nominal_feasible=bool(nom_raw >= 0.0),
                drift_feasible=bool(drift_raw >= 0.0),
            ))

        named_factors = {}
        indexed_factors = {}
        for p_info in merged:
            val = factor_vals[p_info['index']]
            named_factors[p_info['name']] = float(val) if isinstance(val, (int, float)) else str(val)
            indexed_factors[str(p_info['index'])] = named_factors[p_info['name']]

        min_nom_std = min(nom_margins)
        min_drift_std = min(drift_margins)
        min_drift_raw = min(d['worst_drift_margin'] for d in resp_details)
        return dict(
            key=key_name,
            label=label,
            x=x_pt,
            y=y_pt,
            z=float(resp_details[prim_idx]['fit']),
            outside_design_region=bool(outside),
            nominal_feasible=bool(min_nom_std >= 0.0),
            worst_case_feasible=bool(min_drift_std >= 0.0),
            min_nominal_std_margin=float(min_nom_std),
            min_drift_margin=float(min_drift_raw),
            min_drift_std_margin=float(min_drift_std),
            limiting_response=worst_lim,
            factors=named_factors,
            factors_by_index=indexed_factors,
            responses=resp_details,
        )

    def _cell_to_map(cell):
        m = dict(base_predictors)
        m[x_index] = cell['x']
        m[y_index] = cell['y']
        return m

    predicted_optimum = _evaluate_candidate('Predicted Optimum', 'predicted_optimum', _cell_to_map(nom_opt_cell))
    robust_setting = _evaluate_candidate('Robust Setting', 'robust_setting', _cell_to_map(robust_cell))

    selected_setting = None
    if 'selected_setting' in opts:
        sel_map = dict(base_predictors)
        raw_sel = opts['selected_setting']
        by_name = {p['name'].casefold(): p for p in merged}
        for k_str, val in raw_sel.items():
            target_p = by_name.get(k_str.casefold())
            if target_p is None:
                try:
                    target_p = pred_by_idx.get(int(k_str))
                except ValueError:
                    target_p = None
            if target_p is None:
                raise ValueError(f"Selected setting references unknown factor '{k_str}'.")
            if target_p['role'] == 'factor':
                if val not in target_p['levels']:
                    raise ValueError(f"Selected level for {target_p['name']} is not an observed factor level.")
                sel_map[target_p['index']] = val
            else:
                if isinstance(val, str):
                    raise ValueError(f"Selected value for {target_p['name']} must be numeric.")
                sel_map[target_p['index']] = float(val)
        sel_map.setdefault(x_index, robust_cell['x'])
        sel_map.setdefault(y_index, robust_cell['y'])
        selected_setting = _evaluate_candidate('Selected Setting', 'selected_setting', sel_map)

    return _finite_result(dict(
        analysis='operating_window_3d',
        title=f"3D Operating Window: {prim_spec['response_name']} ({x_info['name']} vs {y_info['name']})",
        confidence=float(opts['confidence']),
        grid_size=int(g),
        design_region_only=bool(opts['design_region_only']),
        empty_window=bool(empty_window),
        x_index=int(x_index),
        y_index=int(y_index),
        x_name=x_info['name'],
        y_name=y_info['name'],
        primary_response_index=int(prim_idx),
        primary_response_name=prim_spec['response_name'],
        primary_goal=prim_goal,
        responses=[
            dict(
                response_index=s['response_index'],
                response_name=s['response_name'],
                model_title=s['model_title'],
                model_recipe=s['model_recipe'],
                lower=s['lower'],
                upper=s['upper'],
                target=s['target'],
                goal=s['goal'],
                scale=sc,
            )
            for s, sc in zip(norm_specs, scales)
        ],
        predictors=[
            dict(
                index=p['index'],
                name=p['name'],
                role=p['role'],
                levels=p['levels'],
                min=p['observed_min'],
                max=p['observed_max'],
                drift_delta=float(drift_map.get(p['index'], 0.0)),
            )
            for p in merged
        ],
        hold_summary=hold_summary,
        drifts=active_drifts,
        design_hull=design_hull,
        x_grid=x_grid,
        y_grid=y_grid,
        z_grid=z_grid,
        status_grid=status_grid,
        nominal_margin_grid=nominal_margin_grid,
        drift_margin_grid=drift_margin_grid,
        limiting_grid=limiting_grid,
        outside_region_grid=outside_region_grid,
        window_summary=dict(
            total_cells=n_grid,
            nominal_feasible_cells=n_nominal_feasible_all,
            drift_feasible_cells=n_drift_feasible_all,
            nominal_feasible_in_hull=n_nominal_feasible_in,
            drift_feasible_in_hull=n_drift_feasible_in,
            drift_feasible_pct=round(100.0 * n_drift_feasible_in / max(1, n_grid), 2),
        ),
        predicted_optimum=predicted_optimum,
        robust_setting=robust_setting,
        selected_setting=selected_setting,
        options=opts,
        warnings=warnings,
        method='Multi-response quadratic/regression grid & drift-hypercube robustness evaluation',
        method_notes=(
            'Grid cells are colored by worst-case specification margin across the factor drift hypercube; '
            'points outside the 2D convex hull of design runs are flagged as extrapolations.'
        ),
    ))
