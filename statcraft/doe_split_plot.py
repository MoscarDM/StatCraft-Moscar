"""Split-plot factorial design creation and two-stratum ANOVA."""
import itertools
import math
import random

import numpy as np
from scipy.stats import f as f_dist

from .engine import normalize_numeric
from .model import Column, Worksheet

_RESERVED_COLUMNS = {'stdorder', 'runorder', 'pttype', 'blocks', 'wp', 'y'}


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be an integer from {low} to {high}.')
    return value


def _parse_factor(factor, seen_names, stratum):
    if not isinstance(factor, dict):
        raise ValueError('Each factor must be a dict with name and levels (or low/high).')
    name = factor.get('name')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Factor names must be non-empty strings.')
    name = name.strip()
    if name.casefold() in _RESERVED_COLUMNS or name.casefold() in seen_names:
        raise ValueError(f'Factor name "{name}" must be unique and not a reserved design column.')
    seen_names.add(name.casefold())

    if 'levels' in factor and factor['levels'] is not None:
        raw_levels = list(factor['levels'])
        if len(raw_levels) < 2:
            raise ValueError(f'Factor "{name}" must have at least 2 levels.')
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in raw_levels):
            numeric_levels = [normalize_numeric(v) for v in raw_levels]
        else:
            numeric_levels = [None]
        if all(v is not None for v in numeric_levels):
            kind = 'number'
            levels = numeric_levels
        else:
            kind = 'text'
            levels = [str(v).strip() for v in raw_levels]
            if any(not v for v in levels):
                raise ValueError(f'Factor "{name}" text levels must be non-empty.')
        if len(set(levels)) != len(levels):
            raise ValueError(f'Factor "{name}" levels must be distinct.')
        descriptor = {'name': name, 'kind': kind, 'levels': levels, 'stratum': stratum}
        if kind == 'number' and len(levels) == 2:
            lo, hi = min(levels), max(levels)
            descriptor['low'] = lo
            descriptor['high'] = hi
        return descriptor

    if 'low' in factor and 'high' in factor:
        low = normalize_numeric(factor['low'])
        high = normalize_numeric(factor['high'])
        if low is None or high is None:
            raise ValueError(f'Factor "{name}" low and high settings must be finite numbers.')
        if low >= high:
            raise ValueError(f'Factor "{name}" low setting must be below its high setting.')
        return {
            'name': name,
            'kind': 'number',
            'levels': [low, high],
            'low': low,
            'high': high,
            'stratum': stratum,
        }

    raise ValueError(f'Factor "{name}" requires either "levels" or "low" and "high" settings.')


def create_split_plot_design(
    hard_factors: list,
    easy_factors: list,
    replicates: int = 1,
    seed: int | None = None,
    randomize: bool = True,
    subplot_replicates: int = 1,
) -> Worksheet:
    """Create a split-plot factorial design with randomized whole-plot (WP) blocks.

    Hard-to-change factors are constant within each whole-plot block (WP), while
    easy-to-change factors vary across subplot runs within each WP block.
    A blank response column 'Y' is appended at the end of the worksheet.
    """
    hard_list = list(hard_factors)
    easy_list = list(easy_factors)
    if not 1 <= len(hard_list) <= 6:
        raise ValueError('Specify 1 to 6 hard-to-change (whole-plot) factors.')
    if not 1 <= len(easy_list) <= 8:
        raise ValueError('Specify 1 to 8 easy-to-change (subplot) factors.')
    _integer(replicates, 1, 20, 'Whole-plot replicates')
    _integer(subplot_replicates, 1, 20, 'Subplot replicates')
    if type(randomize) is not bool:
        raise ValueError('Randomize must be true or false.')
    if seed is not None:
        _integer(seed, -(2**63), 2**63 - 1, 'Randomization seed')

    def _with_text_levels(f):
        if isinstance(f, dict) and str(f.get('kind', '')).lower() == 'text' and 'levels' not in f and 'low' in f and 'high' in f:
            return {**f, 'levels': [str(f['low']), str(f['high'])]}
        return f

    seen_names = set()
    hard_desc = [_parse_factor(_with_text_levels(f), seen_names, 'whole_plot') for f in hard_list]
    easy_desc = [_parse_factor(_with_text_levels(f), seen_names, 'subplot') for f in easy_list]
    all_desc = hard_desc + easy_desc
    for idx, desc in enumerate(all_desc):
        desc['column_index'] = 4 + idx

    wp_combos = list(itertools.product(*[d['levels'] for d in hard_desc]))
    sp_combos = list(itertools.product(*[d['levels'] for d in easy_desc]))
    n_wp = len(wp_combos) * replicates
    total_runs = n_wp * len(sp_combos) * subplot_replicates
    if total_runs > 4096:
        raise ValueError('The split-plot design exceeds the 4096-run limit.')

    # Build standard-order whole plots and subplot runs
    whole_plots = []
    std_order = 1
    for _rep in range(replicates):
        for wp_vals in wp_combos:
            sp_runs = []
            for _sp_rep in range(subplot_replicates):
                for sp_vals in sp_combos:
                    sp_runs.append({
                        'std_order': std_order,
                        'pt_type': 1,
                        'hard': list(wp_vals),
                        'easy': list(sp_vals),
                    })
                    std_order += 1
            whole_plots.append(sp_runs)

    if randomize:
        rng = random.Random(seed)
        rng.shuffle(whole_plots)
        for sp_runs in whole_plots:
            rng.shuffle(sp_runs)

    flat_runs = []
    for wp_id, sp_runs in enumerate(whole_plots, 1):
        for run in sp_runs:
            run['wp'] = wp_id
            flat_runs.append(run)

    columns = [
        Column('StdOrder', values=[r['std_order'] for r in flat_runs]),
        Column('RunOrder', values=list(range(1, total_runs + 1))),
        Column('PtType', values=[r['pt_type'] for r in flat_runs]),
        Column('WP', values=[r['wp'] for r in flat_runs]),
    ]
    for i, desc in enumerate(hard_desc):
        columns.append(Column(desc['name'], kind=desc['kind'], values=[r['hard'][i] for r in flat_runs]))
    for i, desc in enumerate(easy_desc):
        columns.append(Column(desc['name'], kind=desc['kind'], values=[r['easy'][i] for r in flat_runs]))
    columns.append(Column('Y', kind='number', values=[None] * total_runs))

    return Worksheet(
        'Split-plot factorial design',
        columns,
        metadata={
            'doe': {
                'schema': 'statcraft-split-plot-v1',
                'origin': 'Original StatCraft design',
                'design': 'split-plot factorial',
                'whole_plot_col': 'WP',
                'hard_factors': hard_desc,
                'easy_factors': easy_desc,
                'factors': all_desc,
                'replicates': replicates,
                'subplot_replicates': subplot_replicates,
                'randomize': randomize,
                'seed': seed,
                'whole_plots': n_wp,
                'standard_order': 'Whole plots grouped by replicate; subplots ordered within each whole plot.',
                'native_parity': False,
            }
        },
    )


def _resolve_column(worksheet, spec, label):
    if type(spec) is int:
        if not 0 <= spec < len(worksheet.columns):
            raise ValueError(f'{label} column index {spec} is out of range.')
        return spec, worksheet.columns[spec]
    if isinstance(spec, str):
        matches = [(i, c) for i, c in enumerate(worksheet.columns) if c.name == spec]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f'{label} column name "{spec}" is ambiguous.')
        raise ValueError(f'{label} column "{spec}" not found in worksheet.')
    raise ValueError(f'Invalid {label.lower()} column specification.')


def _is_missing(val):
    if val is None:
        return True
    if isinstance(val, str) and not val.strip():
        return True
    if isinstance(val, float) and not math.isfinite(val):
        return True
    return False


def _rss(design_matrix, y):
    """Residual sum of squares from least-squares fit of y on design_matrix."""
    if design_matrix.shape[1] == 0:
        return float(np.sum(y * y))
    coef, _, _, _ = np.linalg.lstsq(design_matrix, y, rcond=None)
    resid = y - design_matrix @ coef
    return float(np.dot(resid, resid))


def _rank(matrix):
    if matrix.shape[1] == 0:
        return 0
    return int(np.linalg.matrix_rank(matrix))


def _encode_factor_levels(raw_values, name):
    """Return (contrast_matrix, observed_levels) using sum-to-zero coding."""
    levels = []
    seen = set()
    for v in raw_values:
        key = v
        if key not in seen:
            seen.add(key)
            levels.append(v)
    try:
        levels.sort()
    except TypeError:
        pass
    k = len(levels)
    if k < 2:
        raise ValueError(f'Factor "{name}" must have at least 2 observed levels.')
    n = len(raw_values)
    cols = np.zeros((n, k - 1), dtype=float)
    ref = levels[-1]
    idx_map = {lvl: j for j, lvl in enumerate(levels[:-1])}
    for i, v in enumerate(raw_values):
        if v == ref:
            cols[i, :] = -1.0
        else:
            cols[i, idx_map[v]] = 1.0
    return cols, levels


def _term_matrix(factor_names, factor_matrices):
    mat = factor_matrices[factor_names[0]]
    for fname in factor_names[1:]:
        next_mat = factor_matrices[fname]
        cols = [mat[:, i] * next_mat[:, j] for i in range(mat.shape[1]) for j in range(next_mat.shape[1])]
        mat = np.column_stack(cols)
    return mat


def analyze_split_plot(
    worksheet,
    response: str | int,
    whole_plot_col: str | int = 'WP',
    terms: list | None = None,
    confidence: float = 0.95,
) -> dict:
    """Compute a two-stratum split-plot ANOVA separating whole-plot and subplot error.

    Whole-plot terms (composed solely of factors constant within every whole plot)
    are tested against Whole-Plot Error. Subplot terms (containing at least one factor
    varying within whole plots) are tested against Subplot Residual Error controlling
    for whole-plot effects, so missing subplot cells never collapse whole-plot error
    into subplot residual error.
    """
    if not isinstance(worksheet, Worksheet):
        raise ValueError('A Worksheet is required.')
    if not 0.0 < confidence < 1.0:
        raise ValueError('Confidence level must be between 0 and 1.')

    resp_idx, resp_col = _resolve_column(worksheet, response, 'Response')
    if resp_col.kind != 'number':
        raise ValueError('Response column must be numeric.')
    wp_idx, wp_col = _resolve_column(worksheet, whole_plot_col, 'Whole-plot')
    if resp_idx == wp_idx:
        raise ValueError('Response and whole-plot columns must be distinct.')

    # Determine candidate factors & terms
    col_by_name = {}
    for i, c in enumerate(worksheet.columns):
        if i not in (resp_idx, wp_idx):
            col_by_name.setdefault(c.name, (i, c))

    if terms is None:
        meta = worksheet.metadata.get('doe', {})
        if isinstance(meta, dict) and meta.get('schema') == 'statcraft-split-plot-v1':
            factor_names = [f['name'] for f in meta.get('factors', []) if isinstance(f, dict) and f.get('name') in col_by_name]
        else:
            factor_names = [
                c.name for i, c in enumerate(worksheet.columns)
                if i not in (resp_idx, wp_idx) and c.name.casefold() not in _RESERVED_COLUMNS
            ]
        if not factor_names:
            raise ValueError('No factor columns found for split-plot analysis.')
        parsed_terms = [(fn,) for fn in factor_names]
        for a, b in itertools.combinations(factor_names, 2):
            parsed_terms.append((a, b))
        term_labels = ['*'.join(t) for t in parsed_terms]
    else:
        if not isinstance(terms, (list, tuple)) or not terms:
            raise ValueError('Specify at least one model term.')
        parsed_terms = []
        term_labels = []
        for raw_term in terms:
            if not isinstance(raw_term, str) or not raw_term.strip():
                raise ValueError('Each model term must be a non-empty string.')
            sep = '*' if '*' in raw_term else ':'
            parts = [p.strip() for p in raw_term.split(sep) if p.strip()]
            if not parts or len(set(parts)) != len(parts):
                raise ValueError(f'Invalid model term "{raw_term}".')
            for p in parts:
                if p not in col_by_name:
                    raise ValueError(f'Term factor "{p}" not found in worksheet.')
            parsed_terms.append(tuple(parts))
            term_labels.append('*'.join(parts))

    referenced_factors = []
    for t in parsed_terms:
        for f in t:
            if f not in referenced_factors:
                referenced_factors.append(f)

    n_total = worksheet.row_count
    used_rows = []
    ys = []
    wp_values = []
    factor_raw = {f: [] for f in referenced_factors}

    for r in range(n_total):
        y_raw = resp_col.values[r] if r < len(resp_col.values) else None
        y_val = normalize_numeric(y_raw)
        wp_val = wp_col.values[r] if r < len(wp_col.values) else None
        if y_val is None or _is_missing(wp_val):
            continue
        row_factors = {}
        missing_factor = False
        for f in referenced_factors:
            _, fcol = col_by_name[f]
            fval = fcol.values[r] if r < len(fcol.values) else None
            if fcol.kind == 'number':
                fval = normalize_numeric(fval)
                if fval is None:
                    missing_factor = True
                    break
            elif _is_missing(fval):
                missing_factor = True
                break
            else:
                fval = str(fval).strip()
            row_factors[f] = fval
        if missing_factor:
            continue
        used_rows.append(r)
        ys.append(y_val)
        wp_values.append(wp_val)
        for f in referenced_factors:
            factor_raw[f].append(row_factors[f])

    n_used = len(used_rows)
    missing_count = n_total - n_used
    if n_used < 2:
        raise ValueError('Insufficient non-missing observations for split-plot analysis.')

    # Group observations by whole plot
    unique_wps = []
    wp_row_indices = {}
    for idx, wp_val in enumerate(wp_values):
        if wp_val not in wp_row_indices:
            unique_wps.append(wp_val)
            wp_row_indices[wp_val] = []
        wp_row_indices[wp_val].append(idx)

    n_wp = len(unique_wps)
    if n_wp < 2:
        raise ValueError('At least 2 whole plots are required to estimate whole-plot error.')

    # Classify factors as whole-plot (constant within every WP) vs subplot
    wp_factors = []
    sp_factors = []
    for f in referenced_factors:
        vals = factor_raw[f]
        is_wp = all(len({vals[i] for i in wp_row_indices[wp]}) == 1 for wp in unique_wps)
        if is_wp:
            wp_factors.append(f)
        else:
            sp_factors.append(f)

    if not sp_factors:
        raise ValueError('Split-plot analysis requires at least one subplot (easy-to-change) factor varying within whole plots.')

    # Encode factors
    factor_matrices = {}
    for f in referenced_factors:
        mat, _ = _encode_factor_levels(factor_raw[f], f)
        factor_matrices[f] = mat

    # Partition terms into whole-plot vs subplot strata
    wp_term_indices = []
    sp_term_indices = []
    term_mats = {}
    for i, (label, parts) in enumerate(zip(term_labels, parsed_terms)):
        term_mats[label] = _term_matrix(parts, factor_matrices)
        if all(p in wp_factors for p in parts):
            wp_term_indices.append(i)
        else:
            sp_term_indices.append(i)

    y_vec = np.array(ys, dtype=float)
    y_total_ss = float(np.sum((y_vec - np.mean(y_vec)) ** 2))

    # --- Whole-Plot Stratum (between whole plots) ---
    wp_sizes = [len(wp_row_indices[wp]) for wp in unique_wps]
    mean_wp_size = n_used / n_wp
    y_wp_means = np.array([float(np.mean(y_vec[wp_row_indices[wp]])) for wp in unique_wps], dtype=float)
    wp_first_rows = [wp_row_indices[wp][0] for wp in unique_wps]

    wp_mats_w = [term_mats[term_labels[i]][wp_first_rows, :] for i in wp_term_indices]
    ones_w = np.ones((n_wp, 1), dtype=float)
    x_wp_w = np.column_stack(wp_mats_w) if wp_mats_w else np.zeros((n_wp, 0), dtype=float)
    a_full = np.column_stack([ones_w, x_wp_w])
    rank_wp_full = _rank(a_full)
    wp_df = n_wp - rank_wp_full
    if wp_df <= 0:
        raise ValueError(
            f'Insufficient whole-plot degrees of freedom ({n_wp} whole plots for {rank_wp_full} whole-plot parameters); '
            'add whole-plot replicates or reduce whole-plot terms.'
        )
    wp_rss_means = _rss(a_full, y_wp_means)
    wp_ss = mean_wp_size * wp_rss_means
    wp_ms = wp_ss / wp_df

    term_results = {}
    for pos, t_idx in enumerate(wp_term_indices):
        label = term_labels[t_idx]
        other_wp = [wp_mats_w[j] for j in range(len(wp_mats_w)) if j != pos]
        x_other = np.column_stack(other_wp) if other_wp else np.zeros((n_wp, 0), dtype=float)
        a_red = np.column_stack([ones_w, x_other])
        df_t = rank_wp_full - _rank(a_red)
        if df_t <= 0:
            raise ValueError(f'Whole-plot term "{label}" is rank-deficient on the retained whole plots.')
        ss_t = max(0.0, mean_wp_size * (_rss(a_red, y_wp_means) - wp_rss_means))
        ms_t = ss_t / df_t
        f_val = (ms_t / wp_ms) if wp_ms > 0.0 else None
        p_val = float(f_dist.sf(f_val, df_t, wp_df)) if f_val is not None else None
        term_results[label] = {
            'source': label,
            'stratum': 'Whole-Plot',
            'df': int(df_t),
            'ss': ss_t,
            'ms': ms_t,
            'f': f_val,
            'p_value': p_val,
        }

    # --- Subplot Stratum (intra-whole-plot) ---
    z_wp = np.zeros((n_used, n_wp), dtype=float)
    for w_idx, wp_val in enumerate(unique_wps):
        for r_idx in wp_row_indices[wp_val]:
            z_wp[r_idx, w_idx] = 1.0

    sp_mats = [term_mats[term_labels[i]] for i in sp_term_indices]
    x_sp = np.column_stack(sp_mats) if sp_mats else np.zeros((n_used, 0), dtype=float)
    m_full = np.column_stack([z_wp, x_sp])
    rank_sp_full = _rank(m_full)
    sp_df = n_used - rank_sp_full
    if sp_df <= 0:
        raise ValueError('Insufficient subplot residual degrees of freedom for split-plot analysis.')
    sp_ss = _rss(m_full, y_vec)
    sp_ms = sp_ss / sp_df

    for pos, t_idx in enumerate(sp_term_indices):
        label = term_labels[t_idx]
        other_sp = [sp_mats[j] for j in range(len(sp_mats)) if j != pos]
        x_other = np.column_stack(other_sp) if other_sp else np.zeros((n_used, 0), dtype=float)
        m_red = np.column_stack([z_wp, x_other])
        df_t = rank_sp_full - _rank(m_red)
        if df_t <= 0:
            raise ValueError(f'Model term "{label}" is rank-deficient or confounded with whole plots.')
        ss_t = max(0.0, _rss(m_red, y_vec) - sp_ss)
        ms_t = ss_t / df_t
        f_val = (ms_t / sp_ms) if sp_ms > 0.0 else None
        p_val = float(f_dist.sf(f_val, df_t, sp_df)) if f_val is not None else None
        term_results[label] = {
            'source': label,
            'stratum': 'Subplot',
            'df': int(df_t),
            'ss': ss_t,
            'ms': ms_t,
            'f': f_val,
            'p_value': p_val,
        }

    balanced = len(set(wp_sizes)) == 1 and missing_count == 0
    warnings = []
    if not balanced:
        warnings.append(
            'Unbalanced whole-plot sizes or missing subplot cells detected; two-stratum ANOVA preserves separate whole-plot and subplot error degrees of freedom.'
        )

    anova_table = []
    for t_idx in wp_term_indices:
        anova_table.append(term_results[term_labels[t_idx]])
    anova_table.append({
        'source': 'Whole-Plot Error',
        'stratum': 'Whole-Plot',
        'df': int(wp_df),
        'ss': wp_ss,
        'ms': wp_ms,
        'f': None,
        'p_value': None,
    })
    for t_idx in sp_term_indices:
        anova_table.append(term_results[term_labels[t_idx]])
    anova_table.append({
        'source': 'Subplot Error',
        'stratum': 'Subplot',
        'df': int(sp_df),
        'ss': sp_ss,
        'ms': sp_ms,
        'f': None,
        'p_value': None,
    })
    anova_table.append({
        'source': 'Total',
        'stratum': 'Total',
        'df': int(n_used - 1),
        'ss': y_total_ss,
        'ms': None,
        'f': None,
        'p_value': None,
    })

    wp_var = max(0.0, (wp_ms - sp_ms) / mean_wp_size)
    sp_var = sp_ms

    return {
        'analysis': 'split_plot',
        'method': 'Two-stratum Split-Plot ANOVA',
        'response': resp_col.name,
        'whole_plot_col': wp_col.name,
        'whole_plots': n_wp,
        'count': n_used,
        'missing': missing_count,
        'balanced': balanced,
        'confidence': confidence,
        'whole_plot_factors': wp_factors,
        'subplot_factors': sp_factors,
        'whole_plot_terms': [term_labels[i] for i in wp_term_indices],
        'subplot_terms': [term_labels[i] for i in sp_term_indices],
        'whole_plot_df': int(wp_df),
        'whole_plot_ss': wp_ss,
        'whole_plot_ms': wp_ms,
        'subplot_df': int(sp_df),
        'subplot_ss': sp_ss,
        'subplot_ms': sp_ms,
        'term_results': term_results,
        'anova_table': anova_table,
        'variance_components': {'whole_plot_var': wp_var, 'subplot_var': sp_var},
        'warnings': warnings,
        'native_parity': False,
    }
