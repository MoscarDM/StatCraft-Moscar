"""Generate self-contained base-R checks for saved StatCraft analyses."""
import json
import math

from .capability_engine import d2 as _cap_d2, d4 as _cap_d4
from .engine import normalize_numeric
from .subgroup_control import d2 as _sub_d2, d3 as _sub_d3

SUPPORTED = {
    'analyze_factorial',
    'analyze_factorial_terms',
    'multiple_regression',
    'imr_chart',
    'subgroup_control_chart',
    'attribute_control_chart',
    'normal_capability',
    'gage_rr',
}


def supports(entry):
    """Return True when the saved entry can be verified in the R Workbench."""
    if not isinstance(entry, dict):
        return False
    recipe = entry.get('recipe', {})
    action = recipe.get('action')
    if action not in SUPPORTED:
        return False
    params = recipe.get('parameters', {})
    result = entry.get('result', {})
    if action == 'multiple_regression':
        return not params.get('categorical_indices') and not params.get('model_terms')
    if action == 'subgroup_control_chart':
        return params.get('chart_type', result.get('chart_type', 'xbar_r')) in ('xbar_r', 'xbar_s')
    if action == 'attribute_control_chart':
        chart_type = str(result.get('chart_type', result.get('chart', params.get('settings', {}).get('chart_type', '')))).upper().strip().replace('′', "'")
        return result.get('analysis') == 'attribute_control' and chart_type in ('P', 'NP', 'C', 'U', "P'", "U'")
    if action == 'normal_capability':
        return result.get('analysis_mode', 'normal') == 'normal'
    if action == 'gage_rr':
        return result.get('analysis') == 'gage_rr'
    return True


def tab_name(entry):
    """Return a clear script tab filename for the supported analysis."""
    action = entry.get('recipe', {}).get('action')
    return {
        'imr_chart': 'Verify_IMR.R',
        'subgroup_control_chart': 'Verify_Subgroup.R',
        'attribute_control_chart': 'Verify_Attribute.R',
        'normal_capability': 'Verify_Capability.R',
        'gage_rr': 'Verify_GageRR.R',
    }.get(action, 'Verify_OLS.R')


def _vector(values):
    return 'c(' + ', '.join(repr(float(value)) for value in values) + ')'


def _r_num(value):
    if value is None:
        return 'NA_real_'
    val = float(value)
    return repr(val) if math.isfinite(val) else 'NA_real_'


def _r_num_vector(values):
    return 'c(' + ', '.join(_r_num(v) for v in values) + ')'


def _r_bool(value):
    return 'TRUE' if value else 'FALSE'


def _r_bool_vector(values):
    return 'c(' + ', '.join('TRUE' if v else 'FALSE' for v in values) + ')'


def _r_int_vector(values):
    return 'c(' + ', '.join(f'{int(v)}L' for v in values) + ')'


def _r_str_vector(values):
    return 'c(' + ', '.join(json.dumps(str(v), ensure_ascii=False) for v in values) + ')'


def _build_ols_script(sheet, entry):
    recipe = entry['recipe']
    action = recipe['action']
    params = recipe['parameters']
    result = entry['result']
    rows = result['row_indices']
    response = sheet.columns[params['response_index']].numeric_values(True)
    if action == 'multiple_regression':
        if params.get('categorical_indices') or params.get('model_terms'):
            raise ValueError('This R verification supports regression with continuous main effects.')
        raw = [sheet.columns[index].numeric_values(True) for index in params['predictor_indices']]
        columns = [[values[row] for row in rows] for values in raw]
        metadata = {}
    else:
        codes = result['coded_factors']
        if result.get('include_blocks') and 'verification_block_columns' not in result:
            raise ValueError('Rerun this blocked factorial model to capture its original block coding.')
        columns = result.get('verification_block_columns', []) + [
            [math.prod(row[index] for index in term) for row in codes]
            for term in result['selected_terms']
        ]
        metadata = {
            'factor coding': result['factor_coding'],
            'selected terms': result['selected_terms'],
            'blocks': result['block_terms'],
            'design seed': result.get('design_seed'),
        }
    coefficients = result['coefficients']
    if len(columns) + 1 != len(coefficients):
        raise ValueError('The saved model terms do not match the verification design matrix.')

    terms = [coefficient['name'] for coefficient in coefficients]
    expected = [coefficient['estimate'] for coefficient in coefficients]
    expected += [result['ss_error'], result['df_error'], result['r_squared']]
    labels = ', '.join(json.dumps(term, ensure_ascii=False) for term in terms + ['Residual SS', 'Residual DF', 'R-squared'])
    design_vectors = ',\n  '.join(_vector(column) for column in columns)
    omitted = ', '.join(str(row + 1) for row in sorted(set(range(result['count'] + result['missing'])) - set(rows)))
    settings = json.dumps({'confidence': params.get('confidence', 0.95), **metadata}, ensure_ascii=False)
    return f"""# StatCraft independent base-R OLS verification
# Retained rows are selected jointly across response and predictors.
# Omitted worksheet rows: {omitted or 'none'}
# Saved settings: {settings}

worksheet_row <- c({', '.join(str(row + 1) for row in rows)})
y <- {_vector([response[row] for row in rows])}
x <- cbind(
  {design_vectors}
)
colnames(x) <- paste0("Term", seq_len(ncol(x)))
data <- data.frame(worksheet_row = worksheet_row, y = y, x)
fit <- lm(reformulate(colnames(x), response = "y"), data = data, na.action = na.fail)
print(summary(fit))
cat("\\nRuntime\\n")
print(sessionInfo())

cat("\\nStatCraft versus R\\n")
reference <- {_vector(expected)}
actual <- c(unname(coef(fit)), deviance(fit), df.residual(fit), summary(fit)$r.squared)
difference <- actual - reference
limit <- 1e-7 + 1e-6 * abs(reference)
matches <- is.finite(difference) & abs(difference) <= limit
comparison <- data.frame(Metric = c({labels}), StatCraft = reference,
                         R = actual, Difference = difference, WithinTolerance = matches)
print(comparison, row.names = FALSE, digits = 10)
cat(if (all(matches)) "Verification: PASS\\n" else "Verification: DIFFERENCES FOUND\\n")
print(data.frame(WorksheetRow = data$worksheet_row, Fitted = fitted(fit),
                 Residual = residuals(fit)), row.names = FALSE)
old <- par(mfrow = c(1, 2))
plot(fit, which = c(1, 2))
par(old)
"""


def _normalize_imr_values(raw_values, exclude_rows=None):
    from .imr_engine import parse_subgroup_omission
    excl = parse_subgroup_omission(exclude_rows or set())
    observations = []
    for idx, v in enumerate(raw_values, 1):
        if idx in excl:
            observations.append(None)
        elif v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            observations.append(None)
        else:
            try:
                observations.append(float(v))
            except (ValueError, TypeError):
                observations.append(None)
    return observations


def _build_imr_script(sheet, entry):
    params = entry['recipe']['parameters']['settings']
    var_idx = params['variables'][0]
    if var_idx < 0 or var_idx >= len(sheet.columns):
        raise ValueError('The saved I-MR variable column is unavailable on the worksheet.')
    col = sheet.columns[var_idx]
    if col.kind != 'number':
        raise ValueError('I-MR verification requires a numeric measurement column.')
    result = entry['result']
    opts = result.get('options', {})
    trace = result.get('estimation_trace', {})
    span = int(result.get('span', opts.get('span', 2)))
    est_method = str(result.get('estimation_method', opts.get('estimation_method', 'amr'))).lower()
    unbiasing = bool(result.get('unbiasing', opts.get('unbiasing', True)))
    use_nelson = bool(result.get('use_nelson', opts.get('use_nelson', True)))
    k_sigma = float(trace.get('k_sigma', opts.get('k_sigma', 3.0)))
    hist_mean = trace.get('historical_mean', opts.get('historical_mean'))
    hist_sigma = trace.get('historical_sigma', opts.get('historical_sigma'))
    display_upper = bool(opts.get('display_upper', True))
    display_lower = bool(opts.get('display_lower', True))
    omitted_set = {int(x) for x in result.get('omit_subgroups', [])}

    observations = _normalize_imr_values(col.values, opts.get('exclude_rows'))
    n_total = len(observations)
    rows = list(range(1, n_total + 1))
    omitted_flags = [r in omitted_set for r in rows]

    d2_val = _cap_d2(span)
    d3_val = _sub_d3(span)
    d4_val = _cap_d4(span)

    metrics = [
        ('Observations', float(result['count']), 'as.numeric(obs_count)'),
        ('Mean (I Center)', result['i_center'], 'i_center'),
        ('Within Sigma', result['within_stdev'], 'sigma_within'),
        ('MR Center', result['mr_center'], 'mr_center'),
    ]
    if result.get('i_lcl') is not None:
        metrics.append(('I LCL', result['i_lcl'], 'i_lcl'))
    if result.get('i_ucl') is not None:
        metrics.append(('I UCL', result['i_ucl'], 'i_ucl'))
    if result.get('mr_lcl') is not None:
        metrics.append(('MR LCL', result['mr_lcl'], 'mr_lcl'))
    if result.get('mr_ucl') is not None:
        metrics.append(('MR UCL', result['mr_ucl'], 'mr_ucl'))
    metrics.extend([
        ('I Test 1 Signals', float(len(result.get('i_signals', []))), 'as.numeric(length(i_signals))'),
        ('MR Test 1 Signals', float(len(result.get('mr_signals', []))), 'as.numeric(length(mr_signals))'),
    ])

    metric_labels = _r_str_vector([m[0] for m in metrics])
    ref_vector = _vector([m[1] for m in metrics])
    actual_expr = 'c(' + ', '.join(m[2] for m in metrics) + ')'
    settings_json = json.dumps({
        'variable': col.name,
        'span': span,
        'estimation_method': est_method,
        'unbiasing': unbiasing,
        'use_nelson': use_nelson,
        'k_sigma': k_sigma,
        'historical_mean': hist_mean,
        'historical_sigma': hist_sigma,
        'display_upper': display_upper,
        'display_lower': display_lower,
        'omitted_rows': sorted(omitted_set),
    }, ensure_ascii=False)

    return f"""# StatCraft independent base-R I-MR Control Chart verification
# Missing observations break moving-range spans without bridging.
# Saved settings: {settings_json}

worksheet_row <- {_r_int_vector(rows)}
value <- {_r_num_vector(observations)}
omitted <- {_r_bool_vector(omitted_flags)}
span <- {span}L
est_method <- {json.dumps(est_method)}
unbiasing <- {_r_bool(unbiasing)}
use_nelson <- {_r_bool(use_nelson)}
k_sigma <- {repr(float(k_sigma))}
hist_mean <- {_r_num(hist_mean)}
hist_sigma <- {_r_num(hist_sigma)}
display_upper <- {_r_bool(display_upper)}
display_lower <- {_r_bool(display_lower)}
d2_val <- {repr(float(d2_val))}
d3_val <- {repr(float(d3_val))}
d4_val <- {repr(float(d4_val))}

n_total <- length(value)
obs_count <- sum(!is.na(value))
mr <- rep(NA_real_, n_total)
if (span >= 2L && n_total >= span) {{
  for (i in seq(span, n_total)) {{
    win <- value[(i - span + 1L):i]
    if (!any(is.na(win))) {{
      mr[i] <- max(win) - min(win)
    }}
  }}
}}

est_obs <- value[!is.na(value) & !omitted]
i_center <- if (!is.na(hist_mean)) hist_mean else mean(est_obs)

if (!is.na(hist_sigma)) {{
  sigma_within <- hist_sigma
  mr_center <- d2_val * hist_sigma
}} else {{
  est_mr <- numeric(0)
  if (n_total >= span) {{
    for (i in seq(span, n_total)) {{
      if (!is.na(mr[i]) && !any(omitted[(i - span + 1L):i])) {{
        est_mr <- c(est_mr, mr[i])
      }}
    }}
  }}
  if (length(est_mr) == 0L && est_method %in% c("amr", "mmr")) {{
    sigma_within <- if (length(est_obs) > 1L) sd(est_obs) else 0.0
    mr_center <- d2_val * sigma_within
  }} else if (est_method == "mmr") {{
    med_mr <- median(est_mr)
    d4_eff <- if (unbiasing) d4_val else 1.0
    sigma_within <- if (d4_eff > 0) med_mr / d4_eff else 0.0
    mr_center <- med_mr
  }} else if (est_method == "srmssd") {{
    sq_diffs <- numeric(0)
    if (n_total >= 2L) {{
      for (i in seq(2L, n_total)) {{
        if (!omitted[i] && !omitted[i - 1L] && !is.na(value[i]) && !is.na(value[i - 1L])) {{
          sq_diffs <- c(sq_diffs, (value[i] - value[i - 1L])^2)
        }}
      }}
    }}
    sigma_within <- if (length(sq_diffs) > 0L) sqrt(sum(sq_diffs) / (2.0 * length(sq_diffs))) else if (length(est_obs) > 1L) sd(est_obs) else 0.0
    mr_center <- d2_val * sigma_within
  }} else {{
    avg_mr <- mean(est_mr)
    d2_eff <- if (unbiasing || use_nelson) d2_val else 1.0
    sigma_within <- if (d2_eff > 0) avg_mr / d2_eff else 0.0
    mr_center <- avg_mr
  }}
}}

i_lcl <- if (display_lower) i_center - k_sigma * sigma_within else NA_real_
i_ucl <- if (display_upper) i_center + k_sigma * sigma_within else NA_real_
d3_factor <- if (d2_val > 0) max(0.0, 1.0 - k_sigma * (d3_val / d2_val)) else 0.0
d4_factor <- if (d2_val > 0) 1.0 + k_sigma * (d3_val / d2_val) else 1.0
mr_lcl <- if (display_lower) max(0.0, d3_factor * mr_center) else NA_real_
mr_ucl <- if (display_upper) d4_factor * mr_center else NA_real_

i_signals <- which(!is.na(value) & ((!is.na(i_lcl) & value < i_lcl) | (!is.na(i_ucl) & value > i_ucl)))
mr_signals <- which(!is.na(mr) & ((!is.na(mr_lcl) & mr < mr_lcl) | (!is.na(mr_ucl) & mr > mr_ucl)))

cat("Runtime\\n")
print(sessionInfo())

cat("\\nStatCraft versus R\\n")
reference <- {ref_vector}
actual <- {actual_expr}
difference <- actual - reference
limit <- 1e-7 + 1e-6 * abs(reference)
matches <- is.finite(difference) & abs(difference) <= limit
comparison <- data.frame(Metric = {metric_labels}, StatCraft = reference,
                         R = actual, Difference = difference, WithinTolerance = matches)
print(comparison, row.names = FALSE, digits = 10)
cat(if (all(matches)) "Verification: PASS\\n" else "Verification: DIFFERENCES FOUND\\n")
print(data.frame(WorksheetRow = worksheet_row, Value = value, MovingRange = mr, Omitted = omitted), row.names = FALSE)

old <- par(mfrow = c(2, 1), mar = c(4, 4, 3, 1))
i_ylim <- range(c(value, i_lcl, i_center, i_ucl), na.rm = TRUE)
if (diff(i_ylim) == 0) i_ylim <- i_ylim + c(-1, 1)
plot(worksheet_row, value, type = "b", pch = 19, ylim = i_ylim,
     main = paste("Individuals Chart:", {json.dumps(col.name, ensure_ascii=False)}),
     xlab = "Observation", ylab = {json.dumps(col.name, ensure_ascii=False)})
abline(h = i_center, col = "darkgreen", lty = 1)
if (!is.na(i_ucl)) abline(h = i_ucl, col = "firebrick", lty = 2)
if (!is.na(i_lcl)) abline(h = i_lcl, col = "firebrick", lty = 2)
if (length(i_signals) > 0L) points(worksheet_row[i_signals], value[i_signals], col = "firebrick", pch = 17, cex = 1.3)

mr_ylim <- range(c(mr, mr_lcl, mr_center, mr_ucl), na.rm = TRUE)
if (diff(mr_ylim) == 0) mr_ylim <- mr_ylim + c(0, 1)
plot(worksheet_row, mr, type = "b", pch = 19, ylim = mr_ylim,
     main = paste("Moving Range Chart (Span =", span, ")"),
     xlab = "Observation", ylab = "Moving Range")
abline(h = mr_center, col = "darkgreen", lty = 1)
if (!is.na(mr_ucl)) abline(h = mr_ucl, col = "firebrick", lty = 2)
if (!is.na(mr_lcl)) abline(h = mr_lcl, col = "firebrick", lty = 2)
if (length(mr_signals) > 0L) points(worksheet_row[mr_signals], mr[mr_signals], col = "firebrick", pch = 17, cex = 1.3)
par(old)
"""


def _extract_subgroup_rows(sheet, params):
    from .subgroup_control import _parse_row_indices

    stacked = bool(params.get('stacked', True))
    exclude_set = set(_parse_row_indices((params.get('options') or {}).get('exclude_rows', [])))
    subgroups_with_rows = []
    if stacked:
        resp_idx = params.get('response_index')
        if resp_idx is None or resp_idx < 0 or resp_idx >= len(sheet.columns):
            raise ValueError('The saved subgroup chart response column is unavailable.')
        resp_col = sheet.columns[resp_idx]
        vals = [normalize_numeric(v) for v in resp_col.values]
        fac_idx = params.get('factor_index')
        if fac_idx is not None:
            if fac_idx < 0 or fac_idx >= len(sheet.columns):
                raise ValueError('The saved subgroup ID column is unavailable.')
            fac_col = sheet.columns[fac_idx]
            group_dict = {}
            for r in range(max(len(resp_col.values), len(fac_col.values))):
                if (r + 1) in exclude_set:
                    continue
                lvl = fac_col.values[r] if r < len(fac_col.values) else None
                if lvl is None or lvl == '':
                    continue
                val = vals[r] if r < len(vals) else None
                group_dict.setdefault(lvl, []).append((r + 1, val))
            for idx, (lvl, items) in enumerate(group_dict.items(), 1):
                subgroups_with_rows.append((idx, str(lvl), items))
        else:
            sz = int(params.get('subgroup_size') or 5)
            for idx, start in enumerate(range(0, len(vals), sz), 1):
                items = [
                    (r + 1, None if (r + 1) in exclude_set else vals[r])
                    for r in range(start, min(start + sz, len(vals)))
                ]
                subgroups_with_rows.append((idx, str(idx), items))
    else:
        indices = params.get('indices') or []
        if not indices or any(i < 0 or i >= len(sheet.columns) for i in indices):
            raise ValueError('The saved subgroup columns are unavailable on the worksheet.')
        cols = [sheet.columns[i] for i in indices]
        n_rows = max(len(c.values) for c in cols)
        sg_idx = 0
        for r in range(n_rows):
            if (r + 1) in exclude_set:
                continue
            sg_idx += 1
            items = [(r + 1, normalize_numeric(c.values[r] if r < len(c.values) else None)) for c in cols]
            subgroups_with_rows.append((sg_idx, str(r + 1), items))
    return subgroups_with_rows


def _build_subgroup_script(sheet, entry):
    params = entry['recipe']['parameters']
    result = entry['result']
    chart_type = params.get('chart_type', result.get('chart_type', 'xbar_r'))
    if chart_type not in ('xbar_r', 'xbar_s'):
        raise ValueError('R verification supports Xbar-R and Xbar-S subgroup control charts.')

    subgroups_with_rows = _extract_subgroup_rows(sheet, params)
    opts = result['options']
    k_sigma = float(opts['k_sigma'])
    method = str(opts['estimation_method']).lower()
    unbiasing = bool(opts['unbiasing'])
    omitted_set = {int(x) for x in opts.get('omit_subgroups', [])}
    hist_mean = opts.get('historical_mean')
    hist_sigma = opts.get('historical_sigma')
    display_upper = bool(opts.get('display_upper', True))
    display_lower = bool(opts.get('display_lower', True))
    t1_cfg = opts.get('tests', {}).get('test1', {})
    t1_enabled = bool(t1_cfg.get('enabled', True))
    t1_k = float(t1_cfg.get('k', 3.0))

    obs_rows = []
    obs_subgroup = []
    obs_values = []
    subgroup_labels = []
    subgroup_omitted = []
    max_n = 2
    for sg_idx, sg_label, items in subgroups_with_rows:
        subgroup_labels.append(sg_label)
        subgroup_omitted.append(sg_idx in omitted_set)
        clean_count = sum(1 for _, v in items if v is not None and math.isfinite(v))
        max_n = max(max_n, clean_count)
        for row_num, val in items:
            obs_rows.append(row_num)
            obs_subgroup.append(sg_idx)
            obs_values.append(val)

    d2_vec = [_sub_d2(n) for n in range(1, max_n + 1)]
    d3_vec = [_sub_d3(n) for n in range(1, max_n + 1)]

    xbar_t1_count = sum(1 for rules in result.get('test_failures', {}).values() if 1 in rules)
    disp_sig_count = len(result.get('disp_signals', []))

    metrics = [
        ('Subgroups (K)', float(result['k_subgroups']), 'as.numeric(k_subgroups)'),
        ('Xbar Center', result['xbar_center'], 'xbar_center'),
        ('Within Sigma', result['within_stdev'], 'sigma_hat'),
        ('Dispersion Center', result['disp_center'], 'disp_center'),
        ('Xbar LCL Max Dev', 0.0, 'max_dev(xbar_lcl, ref_xbar_lcl)'),
        ('Xbar UCL Max Dev', 0.0, 'max_dev(xbar_ucl, ref_xbar_ucl)'),
        ('Disp LCL Max Dev', 0.0, 'max_dev(disp_lcl, ref_disp_lcl)'),
        ('Disp UCL Max Dev', 0.0, 'max_dev(disp_ucl, ref_disp_ucl)'),
        ('Xbar Test 1 Signals', float(xbar_t1_count), 'as.numeric(xbar_t1_signals)'),
        ('Dispersion Signals', float(disp_sig_count), 'as.numeric(disp_signals)'),
    ]

    settings_json = json.dumps({
        'variable': result.get('variable_name', 'Data'),
        'chart_type': chart_type,
        'estimation_method': method,
        'unbiasing': unbiasing,
        'k_sigma': k_sigma,
        'historical_mean': hist_mean,
        'historical_sigma': hist_sigma,
        'display_upper': display_upper,
        'display_lower': display_lower,
        'omitted_subgroups': sorted(omitted_set),
    }, ensure_ascii=False)

    disp_label = 'Range' if chart_type == 'xbar_r' else 'StDev'

    return f"""# StatCraft independent base-R {chart_type.upper()} Control Chart verification
# Saved settings: {settings_json}

worksheet_row <- {_r_int_vector(obs_rows)}
obs_subgroup <- {_r_int_vector(obs_subgroup)}
obs_value <- {_r_num_vector(obs_values)}
subgroup_label <- {_r_str_vector(subgroup_labels)}
subgroup_omitted <- {_r_bool_vector(subgroup_omitted)}
k_subgroups <- length(subgroup_label)

chart_type <- {json.dumps(chart_type)}
est_method <- {json.dumps(method)}
unbiasing <- {_r_bool(unbiasing)}
k_sigma <- {repr(float(k_sigma))}
hist_mean <- {_r_num(hist_mean)}
hist_sigma <- {_r_num(hist_sigma)}
display_upper <- {_r_bool(display_upper)}
display_lower <- {_r_bool(display_lower)}
t1_enabled <- {_r_bool(t1_enabled)}
t1_k <- {repr(float(t1_k))}

d2_table <- {_vector(d2_vec)}
d3_table <- {_vector(d3_vec)}
d2_fn <- function(n) ifelse(n >= 1L & n <= length(d2_table), d2_table[n], 3.0 * sqrt(log(n)))
d3_fn <- function(n) ifelse(n >= 1L & n <= length(d3_table), d3_table[n], 0.65)
c4_fn <- function(n) ifelse(n < 2L, 1.0, sqrt(2.0 / (n - 1.0)) * exp(lgamma(n / 2.0) - lgamma((n - 1.0) / 2.0)))
c5_fn <- function(n) ifelse(n < 2L, 0.0, sqrt(max(0.0, 1.0 - c4_fn(n)^2)))

subgroup_sizes <- integer(k_subgroups)
means <- rep(NA_real_, k_subgroups)
ranges <- rep(NA_real_, k_subgroups)
stdevs <- rep(NA_real_, k_subgroups)

for (i in seq_len(k_subgroups)) {{
  vals <- obs_value[obs_subgroup == i & !is.na(obs_value)]
  n <- length(vals)
  subgroup_sizes[i] <- n
  if (n >= 1L) {{
    means[i] <- mean(vals)
    if (n >= 2L) {{
      ranges[i] <- max(vals) - min(vals)
      stdevs[i] <- sd(vals)
    }}
  }}
}}

est_indices <- which(!subgroup_omitted & subgroup_sizes >= 1L)
xbar_center <- if (!is.na(hist_mean)) hist_mean else sum(subgroup_sizes[est_indices] * means[est_indices]) / sum(subgroup_sizes[est_indices])

disp_indices <- which(!subgroup_omitted & subgroup_sizes >= 2L)
has_unequal_disp <- length(unique(subgroup_sizes[disp_indices])) > 1L

if (!is.na(hist_sigma)) {{
  sigma_hat <- hist_sigma
}} else if (length(disp_indices) == 0L) {{
  sigma_hat <- 0.0
}} else if (est_method == "pooled_stdev") {{
  total_df <- sum(subgroup_sizes[disp_indices] - 1L)
  sum_ss <- sum((subgroup_sizes[disp_indices] - 1L) * (stdevs[disp_indices]^2))
  if (total_df > 0L) {{
    sp <- sqrt(sum_ss / total_df)
    c4_val <- if (unbiasing) c4_fn(total_df + 1L) else 1.0
    sigma_hat <- if (c4_val > 0) sp / c4_val else sp
  }} else {{
    sigma_hat <- 0.0
  }}
}} else if (chart_type == "xbar_r") {{
  if (has_unequal_disp && unbiasing) {{
    ns <- subgroup_sizes[disp_indices]
    rs <- ranges[disp_indices]
    d2s <- sapply(ns, d2_fn)
    d3s <- sapply(ns, d3_fn)
    fs <- ifelse(d3s > 0, (d2s^2) / (d3s^2), 1.0)
    sigma_hat <- sum(fs * ifelse(d2s > 0, rs / d2s, rs)) / sum(fs)
  }} else {{
    rbar <- mean(ranges[disp_indices])
    avg_n <- as.integer(round(mean(subgroup_sizes[disp_indices])))
    d2_val <- if (unbiasing) d2_fn(avg_n) else 1.0
    sigma_hat <- if (d2_val > 0) rbar / d2_val else 0.0
  }}
}} else {{
  if (has_unequal_disp && unbiasing) {{
    ns <- subgroup_sizes[disp_indices]
    ss <- stdevs[disp_indices]
    c4s <- sapply(ns, c4_fn)
    c5sq <- pmax(1e-12, 1.0 - c4s^2)
    fs <- (c4s^2) / c5sq
    sigma_hat <- sum(fs * ifelse(c4s > 0, ss / c4s, ss)) / sum(fs)
  }} else {{
    sbar <- mean(stdevs[disp_indices])
    avg_n <- as.integer(round(mean(subgroup_sizes[disp_indices])))
    c4_val <- if (unbiasing) c4_fn(avg_n) else 1.0
    sigma_hat <- if (c4_val > 0) sbar / c4_val else 0.0
  }}
}}

all_disp_sizes <- unique(subgroup_sizes[subgroup_sizes >= 2L])
varying_disp_sizes <- length(all_disp_sizes) > 1L
if (chart_type == "xbar_r") {{
  if (!is.na(hist_sigma) || varying_disp_sizes) {{
    avg_n <- if (length(all_disp_sizes) > 0L) as.integer(round(mean(subgroup_sizes[subgroup_sizes >= 2L]))) else 2L
    disp_center <- d2_fn(avg_n) * sigma_hat
  }} else {{
    r_valid <- ranges[est_indices]
    r_valid <- r_valid[!is.na(r_valid)]
    disp_center <- if (length(r_valid) > 0L) mean(r_valid) else 0.0
  }}
}} else {{
  if (!is.na(hist_sigma) || varying_disp_sizes) {{
    avg_n <- if (length(all_disp_sizes) > 0L) as.integer(round(mean(subgroup_sizes[subgroup_sizes >= 2L]))) else 2L
    disp_center <- (if (unbiasing) c4_fn(avg_n) else 1.0) * sigma_hat
  }} else {{
    s_valid <- stdevs[est_indices]
    s_valid <- s_valid[!is.na(s_valid)]
    disp_center <- if (length(s_valid) > 0L) mean(s_valid) else 0.0
  }}
}}

xbar_se <- rep(NA_real_, k_subgroups)
xbar_lcl <- rep(NA_real_, k_subgroups)
xbar_ucl <- rep(NA_real_, k_subgroups)
disp_centers <- rep(NA_real_, k_subgroups)
disp_lcl <- rep(NA_real_, k_subgroups)
disp_ucl <- rep(NA_real_, k_subgroups)

for (i in seq_len(k_subgroups)) {{
  n <- subgroup_sizes[i]
  if (n >= 1L) {{
    se <- sigma_hat / sqrt(n)
    xbar_se[i] <- se
    if (display_lower) xbar_lcl[i] <- xbar_center - k_sigma * se
    if (display_upper) xbar_ucl[i] <- xbar_center + k_sigma * se
  }}
  if (n >= 2L) {{
    if (chart_type == "xbar_r") {{
      r_cl <- if (!is.na(hist_sigma) || varying_disp_sizes) d2_fn(n) * sigma_hat else disp_center
      disp_centers[i] <- r_cl
      if (display_lower) disp_lcl[i] <- max(0.0, r_cl - k_sigma * d3_fn(n) * sigma_hat)
      if (display_upper) disp_ucl[i] <- r_cl + k_sigma * d3_fn(n) * sigma_hat
    }} else {{
      s_cl <- if (!is.na(hist_sigma) || varying_disp_sizes) (if (unbiasing) c4_fn(n) else 1.0) * sigma_hat else disp_center
      disp_centers[i] <- s_cl
      if (display_lower) disp_lcl[i] <- max(0.0, s_cl - k_sigma * c5_fn(n) * sigma_hat)
      if (display_upper) disp_ucl[i] <- s_cl + k_sigma * c5_fn(n) * sigma_hat
    }}
  }}
}}

xbar_t1_signals <- if (t1_enabled) sum(!is.na(means) & !is.na(xbar_se) & xbar_se > 0 & abs((means - xbar_center) / xbar_se) > t1_k) else 0L
disp_vals <- if (chart_type == "xbar_r") ranges else stdevs
disp_signals <- sum(!is.na(disp_vals) & ((!is.na(disp_lcl) & disp_vals < disp_lcl) | (!is.na(disp_ucl) & disp_vals > disp_ucl)))

ref_xbar_lcl <- {_r_num_vector(result['xbar_lcl'])}
ref_xbar_ucl <- {_r_num_vector(result['xbar_ucl'])}
ref_disp_lcl <- {_r_num_vector(result['disp_lcl'])}
ref_disp_ucl <- {_r_num_vector(result['disp_ucl'])}
max_dev <- function(a, b) {{
  if (!identical(is.na(a), is.na(b))) return(Inf)
  ok <- !is.na(a)
  if (!any(ok)) 0.0 else max(abs(a[ok] - b[ok]))
}}

cat("Runtime\\n")
print(sessionInfo())

cat("\\nStatCraft versus R\\n")
reference <- {_vector([m[1] for m in metrics])}
actual <- c({', '.join(m[2] for m in metrics)})
difference <- actual - reference
limit <- 1e-7 + 1e-6 * abs(reference)
matches <- is.finite(difference) & abs(difference) <= limit
comparison <- data.frame(Metric = {_r_str_vector([m[0] for m in metrics])}, StatCraft = reference,
                         R = actual, Difference = difference, WithinTolerance = matches)
print(comparison, row.names = FALSE, digits = 10)
cat(if (all(matches)) "Verification: PASS\\n" else "Verification: DIFFERENCES FOUND\\n")
print(data.frame(Subgroup = seq_len(k_subgroups), Label = subgroup_label, Size = subgroup_sizes,
                 Mean = means, {disp_label} = disp_vals, Xbar_LCL = xbar_lcl, Xbar_UCL = xbar_ucl,
                 Disp_LCL = disp_lcl, Disp_UCL = disp_ucl), row.names = FALSE)

sg_idx <- seq_len(k_subgroups)
step_line <- function(x, y, ...) {{
  for (j in seq_along(x)) {{
    if (!is.na(y[j])) segments(x[j] - 0.5, y[j], x[j] + 0.5, y[j], ...)
    if (j < length(x) && !is.na(y[j]) && !is.na(y[j + 1L])) {{
      segments(x[j] + 0.5, y[j], x[j] + 0.5, y[j + 1L], ...)
    }}
  }}
}}
old <- par(mfrow = c(2, 1), mar = c(4, 4, 3, 1))
x_ylim <- range(c(means, xbar_lcl, xbar_center, xbar_ucl), na.rm = TRUE)
if (diff(x_ylim) == 0) x_ylim <- x_ylim + c(-1, 1)
plot(sg_idx, means, type = "b", pch = 19, xlim = c(0.5, k_subgroups + 0.5), ylim = x_ylim,
     main = paste("Xbar Chart:", {json.dumps(result.get('variable_name', 'Data'), ensure_ascii=False)}),
     xlab = "Subgroup", ylab = "Sample Mean")
abline(h = xbar_center, col = "darkgreen", lty = 1)
step_line(sg_idx, xbar_ucl, col = "firebrick", lty = 2)
step_line(sg_idx, xbar_lcl, col = "firebrick", lty = 2)

d_ylim <- range(c(disp_vals, disp_lcl, disp_centers, disp_ucl), na.rm = TRUE)
if (diff(d_ylim) == 0) d_ylim <- d_ylim + c(0, 1)
plot(sg_idx, disp_vals, type = "b", pch = 19, xlim = c(0.5, k_subgroups + 0.5), ylim = d_ylim,
     main = paste({json.dumps(disp_label)}, "Chart"),
     xlab = "Subgroup", ylab = {json.dumps(disp_label)})
step_line(sg_idx, disp_centers, col = "darkgreen", lty = 1)
step_line(sg_idx, disp_ucl, col = "firebrick", lty = 2)
step_line(sg_idx, disp_lcl, col = "firebrick", lty = 2)
par(old)
"""


def _extract_capability_rows(sheet, params, result):
    if 'settings' not in params:
        col_idx = params['index']
        if col_idx < 0 or col_idx >= len(sheet.columns):
            raise ValueError('The saved capability variable column is unavailable.')
        col = sheet.columns[col_idx]
        rows = []
        sg_id = 0
        for r, raw in enumerate(col.numeric_values(True), 1):
            if raw is None or not math.isfinite(raw):
                continue
            sg_id += 1
            rows.append((r, sg_id, float(raw)))
        return col.name, rows, {}

    settings = params['settings']
    single = settings.get('single_column', True)
    opts = settings.get('options', {})
    if single:
        col_idx = settings.get('column_index')
        col_ref = settings.get('column_name')
        col = None
        if isinstance(col_idx, int) and 0 <= col_idx < len(sheet.columns):
            col = sheet.columns[col_idx]
        elif isinstance(col_ref, int) and 0 <= col_ref < len(sheet.columns):
            col = sheet.columns[col_ref]
        else:
            for c in sheet.columns:
                if c.name == col_ref:
                    col = c
                    break
        if col is None:
            raise ValueError('The saved capability variable column is unavailable.')
        raw_vals = col.numeric_values(True)
        exclude_set = set()
        if settings.get('exclude_rows'):
            from .imr_engine import parse_subgroup_omission
            exclude_set = parse_subgroup_omission(settings.get('exclude_rows'))
        sub_col_idx = settings.get('subgroup_col_index')
        sub_spec = settings.get('subgroup_spec', 1)
        sub_col = None
        if isinstance(sub_col_idx, int) and 0 <= sub_col_idx < len(sheet.columns):
            sub_col = sheet.columns[sub_col_idx]
        elif isinstance(sub_spec, str):
            try:
                sub_size = int(sub_spec)
            except ValueError:
                sub_col = next((c for c in sheet.columns if c.name == sub_spec), None)
                if sub_col is None:
                    raise ValueError(f"Subgroup column '{sub_spec}' is unavailable on the worksheet.")
        else:
            sub_size = 1 if sub_spec is None else int(sub_spec)

        rows = []
        if sub_col is not None:
            sg_id = 0
            current_id = None
            has_started = False
            for r, (v, g) in enumerate(zip(raw_vals, sub_col.values), 1):
                if r in exclude_set or v is None or not math.isfinite(v):
                    continue
                if not has_started or g != current_id:
                    sg_id += 1
                    current_id = g
                    has_started = True
                rows.append((r, sg_id, float(v)))
        else:
            clean = [
                (r, float(v))
                for r, v in enumerate(raw_vals, 1)
                if r not in exclude_set and v is not None and math.isfinite(v)
            ]
            if sub_size <= 1:
                rows = [(r, idx, v) for idx, (r, v) in enumerate(clean, 1)]
            else:
                rows = [(r, (idx // sub_size) + 1, v) for idx, (r, v) in enumerate(clean)]
        return col.name, rows, opts

    ca_indices = settings.get('cols_across_indices')
    if ca_indices is None:
        ca_indices = []
        for name in settings.get('cols_across', []):
            idx = next((i for i, c in enumerate(sheet.columns) if c.name == name), None)
            if idx is None:
                raise ValueError(f"Column '{name}' is unavailable on the worksheet.")
            ca_indices.append(idx)
    if not ca_indices or any(i < 0 or i >= len(sheet.columns) for i in ca_indices):
        raise ValueError('The saved capability subgroup columns are unavailable.')
    cols = [sheet.columns[i] for i in ca_indices]
    n_rows = max((len(c.values) for c in cols), default=0)
    exclude_set = set()
    if settings.get('exclude_rows'):
        from .imr_engine import parse_subgroup_omission
        exclude_set = parse_subgroup_omission(settings.get('exclude_rows'))
    rows = []
    sg_id = 0
    for r in range(n_rows):
        if (r + 1) in exclude_set:
            continue
        row_items = []
        for c in cols:
            v = c.values[r] if r < len(c.values) else None
            nv = normalize_numeric(v)
            if nv is not None and math.isfinite(nv):
                row_items.append(float(nv))
        if row_items:
            sg_id += 1
            for val in row_items:
                rows.append((r + 1, sg_id, val))
    return ', '.join(c.name for c in cols), rows, opts


def _build_capability_script(sheet, entry):
    result = entry['result']
    if result.get('analysis_mode', 'normal') != 'normal':
        raise ValueError('R verification supports standard Normal Capability (not Between/Within mode).')
    params = entry['recipe']['parameters']
    var_name, cap_rows, opts = _extract_capability_rows(sheet, params, result)
    if len(cap_rows) < 2:
        raise ValueError('Capability verification requires at least two numeric observations.')

    ws_rows = [r for r, _, _ in cap_rows]
    sg_ids = [sg for _, sg, _ in cap_rows]
    values = [v for _, _, v in cap_rows]

    sg_sizes = {}
    for sg in sg_ids:
        sg_sizes[sg] = sg_sizes.get(sg, 0) + 1
    max_sg_size = max(sg_sizes.values())
    span = max(2, int(opts.get('moving_range_len', 2)))
    max_d = max(max_sg_size, span, 2)
    d2_vec = [_cap_d2(n) for n in range(1, max_d + 1)]
    d4_vec = [_cap_d4(n) for n in range(1, max_d + 1)]

    lsl = result.get('lsl')
    usl = result.get('usl')
    target = result.get('target')
    tolerance_k = float(result.get('tolerance_k', 6.0))
    display_unit = str(result.get('display_unit', 'ppm')).lower()
    est_gt1 = str(opts.get('estimate_method_gt1', 'pooled')).lower()
    est_eq1 = str(opts.get('estimate_method_eq1', 'amr')).lower()
    unbiased_within = bool(opts.get('unbiased_within', True))
    unbiased_overall = bool(opts.get('unbiased_overall', False))
    settings_dict = params.get('settings', {})
    hist_mean = settings_dict.get('historical_mean')
    hist_stdev = settings_dict.get('historical_stdev')

    metrics = [
        ('Sample N', float(result['sample_n']), 'as.numeric(n_total)'),
        ('Mean', result['mean'], 'proc_mean'),
        ('StDev (Within)', result['stdev_within'], 'stdev_within'),
        ('StDev (Overall)', result['stdev_overall'], 'stdev_overall'),
    ]
    for label, key in [
        ('Cp', 'cp'), ('CPL', 'cpl'), ('CPU', 'cpu'), ('Cpk', 'cpk'), ('Cpm', 'cpm'),
        ('Pp', 'pp'), ('PPL', 'ppl'), ('PPU', 'ppu'), ('Ppk', 'ppk'),
    ]:
        if result.get(key) is not None:
            metrics.append((label, result[key], key))
    unit_tag = '%' if display_unit == 'percent' else 'PPM'
    metrics.extend([
        (f'Observed Total ({unit_tag})', result['within_perf']['observed_total'], 'obs_total_rate'),
        (f'Expected Within Total ({unit_tag})', result['within_perf']['expected_total'], 'exp_within_rate'),
        (f'Expected Overall Total ({unit_tag})', result['overall_perf']['expected_total'], 'exp_overall_rate'),
    ])

    settings_json = json.dumps({
        'variable': var_name,
        'lsl': lsl,
        'usl': usl,
        'target': target,
        'tolerance_k': tolerance_k,
        'display_unit': display_unit,
        'estimate_method_gt1': est_gt1,
        'estimate_method_eq1': est_eq1,
        'moving_range_len': span,
        'unbiased_within': unbiased_within,
        'unbiased_overall': unbiased_overall,
        'historical_mean': hist_mean,
        'historical_stdev': hist_stdev,
    }, ensure_ascii=False)

    return f"""# StatCraft independent base-R Normal Capability verification
# Saved settings: {settings_json}

worksheet_row <- {_r_int_vector(ws_rows)}
subgroup_id <- {_r_int_vector(sg_ids)}
value <- {_r_num_vector(values)}

lsl <- {_r_num(lsl)}
usl <- {_r_num(usl)}
target_val <- {_r_num(target)}
hist_mean <- {_r_num(hist_mean)}
hist_stdev <- {_r_num(hist_stdev)}
est_gt1 <- {json.dumps(est_gt1)}
est_eq1 <- {json.dumps(est_eq1)}
mr_len <- {span}L
unbiased_within <- {_r_bool(unbiased_within)}
unbiased_overall <- {_r_bool(unbiased_overall)}
tolerance_k <- {repr(float(tolerance_k))}
scale_factor <- {100.0 if display_unit == 'percent' else 1_000_000.0}

d2_table <- {_vector(d2_vec)}
d4_table <- {_vector(d4_vec)}
d2_fn <- function(n) if (n >= 1L && n <= length(d2_table)) d2_table[n] else sqrt(2 * log(n)) - (log(log(n)) + log(4 * pi)) / (2 * sqrt(2 * log(n)))
d4_fn <- function(n) if (n >= 1L && n <= length(d4_table)) d4_table[n] else d2_fn(n)
c4_fn <- function(n) ifelse(n <= 1L, 1.0, exp(0.5 * log(2.0 / (n - 1.0)) + lgamma(n / 2.0) - lgamma((n - 1.0) / 2.0)))

n_total <- length(value)
sample_mean <- mean(value)
proc_mean <- if (!is.na(hist_mean)) hist_mean else sample_mean
sample_sd_overall <- sd(value)
stdev_overall <- if (!is.na(hist_stdev)) hist_stdev else if (unbiased_overall && n_total > 1L) sample_sd_overall / c4_fn(n_total) else sample_sd_overall

groups <- split(value, factor(subgroup_id, levels = unique(subgroup_id)))
group_sizes <- vapply(groups, length, integer(1))
max_size <- max(group_sizes)
min_size <- min(group_sizes)

if (max_size == 1L) {{
  span_eff <- max(2L, mr_len)
  if (n_total >= span_eff) {{
    mrs <- vapply(seq(span_eff, n_total), function(i) {{
      win <- value[(i - span_eff + 1L):i]
      max(win) - min(win)
    }}, numeric(1))
  }} else {{
    mrs <- abs(diff(value))
  }}
  if (est_eq1 == "mmr") {{
    d4_val <- d4_fn(span_eff)
    stdev_within <- if (d4_val > 0) median(mrs) / d4_val else sample_sd_overall
  }} else if (est_eq1 == "srmssd") {{
    stdev_within <- sqrt(sum(diff(value)^2) / (2.0 * (n_total - 1L)))
  }} else {{
    d2_val <- d2_fn(span_eff)
    stdev_within <- if (d2_val > 0) mean(mrs) / d2_val else sample_sd_overall
  }}
}} else if (est_gt1 == "rbar") {{
  gt1 <- groups[group_sizes > 1L]
  if (length(gt1) > 0L) {{
    ranges <- vapply(gt1, function(g) max(g) - min(g), numeric(1))
    if (min_size == max_size) {{
      stdev_within <- mean(ranges) / d2_fn(max_size)
    }} else {{
      d2_sum <- sum(vapply(gt1, function(g) d2_fn(length(g)), numeric(1)))
      stdev_within <- if (d2_sum > 0) sum(ranges) / d2_sum else sample_sd_overall
    }}
  }} else {{
    stdev_within <- sample_sd_overall
  }}
}} else if (est_gt1 == "sbar") {{
  gt1 <- groups[group_sizes > 1L]
  if (length(gt1) > 0L) {{
    stdevs <- vapply(gt1, sd, numeric(1))
    if (min_size == max_size) {{
      c4_val <- if (unbiased_within) c4_fn(max_size) else 1.0
      stdev_within <- if (c4_val > 0) mean(stdevs) / c4_val else sample_sd_overall
    }} else {{
      c4_sum <- sum(vapply(gt1, function(g) c4_fn(length(g)), numeric(1)))
      stdev_within <- if (c4_sum > 0) sum(stdevs) / c4_sum else sample_sd_overall
    }}
  }} else {{
    stdev_within <- sample_sd_overall
  }}
}} else {{
  gt1 <- groups[group_sizes > 1L]
  df_total <- sum(group_sizes - 1L)
  if (df_total > 0L) {{
    sum_ss <- sum(vapply(gt1, function(g) (length(g) - 1L) * var(g), numeric(1)))
    s_pooled <- sqrt(sum_ss / df_total)
    c4_pool <- if (unbiased_within) c4_fn(df_total + 1L) else 1.0
    stdev_within <- if (c4_pool > 0) s_pooled / c4_pool else s_pooled
  }} else {{
    stdev_within <- sample_sd_overall
  }}
}}

if (stdev_within <= 0) stdev_within <- 1e-9
if (stdev_overall <= 0) stdev_overall <- 1e-9

half_k <- tolerance_k / 2.0
cap_indices <- function(sd_val) {{
  p <- if (!is.na(lsl) && !is.na(usl)) (usl - lsl) / (tolerance_k * sd_val) else NA_real_
  pl <- if (!is.na(lsl)) (proc_mean - lsl) / (half_k * sd_val) else NA_real_
  pu <- if (!is.na(usl)) (usl - proc_mean) / (half_k * sd_val) else NA_real_
  pk <- min(c(pl, pu), na.rm = TRUE)
  pm <- NA_real_
  if (!is.na(target_val)) {{
    denom <- 3.0 * sqrt(sd_val^2 + (proc_mean - target_val)^2)
    if (denom > 0) {{
      if (!is.na(lsl) && !is.na(usl)) pm <- (usl - lsl) / (2.0 * denom)
      else if (!is.na(lsl)) pm <- (proc_mean - lsl) / denom
      else if (!is.na(usl)) pm <- (usl - proc_mean) / denom
    }}
  }}
  list(p = p, pl = pl, pu = pu, pk = pk, pm = pm)
}}

w_idx <- cap_indices(stdev_within)
o_idx <- cap_indices(stdev_overall)
cp <- w_idx$p; cpl <- w_idx$pl; cpu <- w_idx$pu; cpk <- w_idx$pk; cpm <- w_idx$pm
pp <- o_idx$p; ppl <- o_idx$pl; ppu <- o_idx$pu; ppk <- o_idx$pk

obs_below <- if (!is.na(lsl)) sum(value < lsl) else 0L
obs_above <- if (!is.na(usl)) sum(value > usl) else 0L
obs_total_rate <- ((obs_below + obs_above) / n_total) * scale_factor

exp_rate <- function(sd_val) {{
  pb <- if (!is.na(lsl)) pnorm((lsl - proc_mean) / sd_val) else 0.0
  pa <- if (!is.na(usl)) pnorm((usl - proc_mean) / sd_val, lower.tail = FALSE) else 0.0
  (pb + pa) * scale_factor
}}
exp_within_rate <- exp_rate(stdev_within)
exp_overall_rate <- exp_rate(stdev_overall)

cat("Runtime\\n")
print(sessionInfo())

cat("\\nStatCraft versus R\\n")
reference <- {_vector([m[1] for m in metrics])}
actual <- c({', '.join(m[2] for m in metrics)})
difference <- actual - reference
limit <- 1e-7 + 1e-6 * abs(reference)
matches <- is.finite(difference) & abs(difference) <= limit
comparison <- data.frame(Metric = {_r_str_vector([m[0] for m in metrics])}, StatCraft = reference,
                         R = actual, Difference = difference, WithinTolerance = matches)
print(comparison, row.names = FALSE, digits = 10)
cat(if (all(matches)) "Verification: PASS\\n" else "Verification: DIFFERENCES FOUND\\n")
print(data.frame(WorksheetRow = worksheet_row, Subgroup = subgroup_id, Value = value), row.names = FALSE)

x_span <- range(c(value, lsl, target_val, usl), na.rm = TRUE)
pad <- 0.5 * max(stdev_overall, stdev_within, diff(x_span) * 0.1, 1e-3)
xlim_vals <- c(x_span[1] - pad, x_span[2] + pad)
h <- hist(value, plot = FALSE)
y_peak <- max(h$density, dnorm(proc_mean, proc_mean, stdev_within), dnorm(proc_mean, proc_mean, stdev_overall), na.rm = TRUE)
hist(value, prob = TRUE, xlim = xlim_vals, ylim = c(0, y_peak * 1.18), col = "#DCE8F2", border = "#25729C",
     main = paste("Normal Capability:", {json.dumps(var_name, ensure_ascii=False)}),
     xlab = {json.dumps(var_name, ensure_ascii=False)})
xs <- seq(xlim_vals[1], xlim_vals[2], length.out = 200)
lines(xs, dnorm(xs, proc_mean, stdev_within), col = "#193354", lwd = 2)
lines(xs, dnorm(xs, proc_mean, stdev_overall), col = "#B45309", lwd = 2, lty = 2)
if (!is.na(lsl)) abline(v = lsl, col = "firebrick", lty = 2, lwd = 1.5)
if (!is.na(usl)) abline(v = usl, col = "firebrick", lty = 2, lwd = 1.5)
if (!is.na(target_val)) abline(v = target_val, col = "darkgreen", lty = 3, lwd = 1.5)
legend("topright", legend = c("Within", "Overall"), col = c("#193354", "#B45309"), lty = c(1, 2), lwd = 2, bty = "n")
"""


def _extract_attribute_rows(sheet, params, result):
    from .imr_engine import parse_subgroup_omission

    settings = params.get('settings', {})
    chart_type = str(
        result.get('chart_type', result.get('chart', settings.get('chart_type', 'P')))
    ).upper().strip().replace('′', "'")
    if chart_type not in ('P', 'NP', 'C', 'U', "P'", "U'"):
        raise ValueError("R verification supports P, NP, C, U, P', and U' attribute charts.")

    vars_list = settings.get('variables') or []
    if not vars_list or vars_list[0] < 0 or vars_list[0] >= len(sheet.columns):
        raise ValueError('The saved attribute count column is unavailable.')
    count_col = sheet.columns[vars_list[0]]
    if count_col.kind != 'number':
        raise ValueError('The saved attribute count column must be numeric.')
    raw_counts = count_col.numeric_values(True)
    n_rows = len(raw_counts)

    opts = result.get('options') or settings.get('options') or {}
    omit_set = parse_subgroup_omission(opts.get('omit_subgroups'))
    exclude_set = parse_subgroup_omission(opts.get('exclude_rows'))

    is_sub_col = bool(settings.get('is_subgroup_col', False))
    sub_col_idx = settings.get('subgroup_col_idx')
    const_size = settings.get('subgroup_size')
    if chart_type == 'C':
        raw_sizes = [1.0] * n_rows
        size_name = 'Constant (1)'
    elif is_sub_col and sub_col_idx is not None:
        if sub_col_idx < 0 or sub_col_idx >= len(sheet.columns):
            raise ValueError('The saved attribute subgroup size column is unavailable.')
        size_col = sheet.columns[sub_col_idx]
        raw_sizes = size_col.numeric_values(True)
        if len(raw_sizes) != n_rows:
            raise ValueError('Attribute count and subgroup size columns must have the same length.')
        size_name = size_col.name
    elif const_size is not None:
        raw_sizes = [float(const_size)] * n_rows
        size_name = f'Constant ({float(const_size):g})'
    else:
        raise ValueError(f'{chart_type} Chart verification requires subgroup sizes.')

    rows = []
    for r, (c_raw, s_raw) in enumerate(zip(raw_counts, raw_sizes), 1):
        if r in exclude_set:
            rows.append((r, None, None, False))
            continue
        c_val = None if c_raw is None or not math.isfinite(float(c_raw)) else float(c_raw)
        s_val = None if s_raw is None or not math.isfinite(float(s_raw)) else float(s_raw)
        if c_val is not None and c_val < 0:
            raise ValueError(f'Row {r}: attribute counts cannot be negative.')
        if s_val is not None and s_val <= 0:
            raise ValueError(f'Row {r}: subgroup sizes must be positive.')
        if chart_type in ('P', "P'", 'NP') and c_val is not None and s_val is not None and c_val > s_val:
            raise ValueError(f'Row {r}: defective count ({c_val}) cannot exceed subgroup size ({s_val}).')
        rows.append((r, c_val, s_val, r not in omit_set))
    return chart_type, count_col.name, size_name, rows, opts


def _build_attribute_script(sheet, entry):
    params = entry['recipe']['parameters']
    result = entry['result']
    chart_type, var_name, size_name, attr_rows, opts = _extract_attribute_rows(sheet, params, result)
    k_sigma = float(result.get('k_sigma', opts.get('k_sigma', 3.0)))
    display_upper = bool(result.get('display_upper', opts.get('display_upper', True)))
    display_lower = bool(result.get('display_lower', opts.get('display_lower', True)))
    hist_p = opts.get('historical_p')
    hist_mean = opts.get('historical_mean')
    tests_cfg = result.get('tests_cfg') or opts.get('tests') or {}
    t1_cfg = tests_cfg.get('test1', {})
    t1_enabled = bool(t1_cfg.get('enabled', True))
    t1_k = float(t1_cfg.get('k', 3.0))

    ws_rows = [r for r, _, _, _ in attr_rows]
    counts = [c for _, c, _, _ in attr_rows]
    sizes = [s for _, _, s, _ in attr_rows]
    in_est = [e for _, _, _, e in attr_rows]

    metrics = [
        ('Complete Subgroups', float(result['n_subgroups']), 'as.numeric(n_complete)'),
        ('Center', float(result['center']), 'param_value'),
    ]
    if chart_type in ("P'", "U'"):
        metrics.append(('Sigma Z', float(result.get('sigma_z', 1.0)), 'sigma_z'))
    metrics.extend([
        ('CL Max Dev', 0.0, 'max_dev(cl_vals, ref_cl)'),
        ('LCL Max Dev', 0.0, 'max_dev(lcl_vals, ref_lcl)'),
        ('UCL Max Dev', 0.0, 'max_dev(ucl_vals, ref_ucl)'),
        ('Test 1 Signals', float(len(result.get('signals', []))), 'as.numeric(t1_signals)'),
    ])

    settings_json = json.dumps({
        'chart_type': chart_type,
        'variable': var_name,
        'subgroup_size': size_name,
        'k_sigma': k_sigma,
        'display_upper': display_upper,
        'display_lower': display_lower,
        'historical_p': hist_p,
        'historical_mean': hist_mean,
        'omitted_subgroups': result.get('omitted_subgroups', []),
    }, ensure_ascii=False)

    y_label = 'Proportion' if chart_type in ('P', "P'") else ('Defective Count' if chart_type == 'NP' else ('Defects' if chart_type == 'C' else 'Defects per Unit'))

    return f"""# StatCraft independent base-R {chart_type} Attribute Control Chart verification
# Saved settings: {settings_json}

worksheet_row <- {_r_int_vector(ws_rows)}
counts <- {_r_num_vector(counts)}
sizes <- {_r_num_vector(sizes)}
in_est <- {_r_bool_vector(in_est)}

chart_type <- {json.dumps(chart_type)}
k_sigma <- {repr(float(k_sigma))}
display_upper <- {_r_bool(display_upper)}
display_lower <- {_r_bool(display_lower)}
hist_p <- {_r_num(hist_p)}
hist_mean <- {_r_num(hist_mean)}
t1_enabled <- {_r_bool(t1_enabled)}
t1_k <- {repr(float(t1_k))}
d2_2 <- 1.128

complete <- !is.na(counts) & !is.na(sizes) & sizes > 0
est_mask <- complete & in_est
n_complete <- sum(complete)

if (chart_type %in% c("P", "P'", "NP")) {{
  param_value <- if (!is.na(hist_p)) hist_p else sum(counts[est_mask]) / sum(sizes[est_mask])
}} else {{
  param_value <- if (!is.na(hist_mean)) hist_mean else sum(counts[est_mask]) / sum(sizes[est_mask])
}}

sigma_z <- 1.0
if (chart_type %in% c("P'", "U'")) {{
  z_vals <- numeric(0)
  for (i in which(est_mask)) {{
    obs_k <- counts[i] / sizes[i]
    se_k <- if (chart_type == "P'") {{
      if (param_value * (1.0 - param_value) > 0) sqrt(param_value * (1.0 - param_value) / sizes[i]) else 0.0
    }} else {{
      if (param_value > 0) sqrt(param_value / sizes[i]) else 0.0
    }}
    if (se_k > 0) z_vals <- c(z_vals, (obs_k - param_value) / se_k)
  }}
  if (length(z_vals) >= 2L) {{
    sigma_z <- mean(abs(diff(z_vals))) / d2_2
    if (!is.finite(sigma_z) || sigma_z <= 0) sigma_z <- 1.0
  }}
}}

n_pts <- length(counts)
obs <- rep(NA_real_, n_pts)
cl_vals <- rep(NA_real_, n_pts)
sig_vals <- rep(NA_real_, n_pts)
lcl_vals <- rep(NA_real_, n_pts)
ucl_vals <- rep(NA_real_, n_pts)

for (i in which(complete)) {{
  c_i <- counts[i]
  s_i <- sizes[i]
  if (chart_type %in% c("P", "P'")) {{
    obs[i] <- c_i / s_i
    cl_vals[i] <- param_value
    sig_base <- if (param_value * (1.0 - param_value) > 0) sqrt(param_value * (1.0 - param_value) / s_i) else 0.0
    sig_vals[i] <- if (chart_type == "P'") sig_base * sigma_z else sig_base
    if (display_upper) ucl_vals[i] <- min(1.0, cl_vals[i] + k_sigma * sig_vals[i])
    if (display_lower) lcl_vals[i] <- max(0.0, cl_vals[i] - k_sigma * sig_vals[i])
  }} else if (chart_type == "NP") {{
    obs[i] <- c_i
    cl_vals[i] <- s_i * param_value
    sig_vals[i] <- if (param_value * (1.0 - param_value) > 0) sqrt(s_i * param_value * (1.0 - param_value)) else 0.0
    if (display_upper) ucl_vals[i] <- min(s_i, cl_vals[i] + k_sigma * sig_vals[i])
    if (display_lower) lcl_vals[i] <- max(0.0, cl_vals[i] - k_sigma * sig_vals[i])
  }} else if (chart_type == "C") {{
    obs[i] <- c_i
    cl_vals[i] <- param_value
    sig_vals[i] <- if (param_value > 0) sqrt(param_value) else 0.0
    if (display_upper) ucl_vals[i] <- cl_vals[i] + k_sigma * sig_vals[i]
    if (display_lower) lcl_vals[i] <- max(0.0, cl_vals[i] - k_sigma * sig_vals[i])
  }} else {{
    obs[i] <- c_i / s_i
    cl_vals[i] <- param_value
    sig_base <- if (param_value > 0) sqrt(param_value / s_i) else 0.0
    sig_vals[i] <- if (chart_type == "U'") sig_base * sigma_z else sig_base
    if (display_upper) ucl_vals[i] <- cl_vals[i] + k_sigma * sig_vals[i]
    if (display_lower) lcl_vals[i] <- max(0.0, cl_vals[i] - k_sigma * sig_vals[i])
  }}
}}

sig_mask <- !is.na(obs) & !is.na(cl_vals) & !is.na(sig_vals) & sig_vals > 0
t1_failed <- if (t1_enabled) sig_mask & (abs(obs - cl_vals) > t1_k * sig_vals) else rep(FALSE, n_pts)
t1_signals <- sum(t1_failed)

ref_cl <- {_r_num_vector(result['center_lines'])}
ref_lcl <- {_r_num_vector(result['lcl'])}
ref_ucl <- {_r_num_vector(result['ucl'])}
max_dev <- function(a, b) {{
  if (!identical(is.na(a), is.na(b))) return(Inf)
  ok <- !is.na(a)
  if (!any(ok)) 0.0 else max(abs(a[ok] - b[ok]))
}}

cat("Runtime\\n")
print(sessionInfo())

cat("\\nStatCraft versus R\\n")
reference <- {_vector([m[1] for m in metrics])}
actual <- c({', '.join(m[2] for m in metrics)})
difference <- actual - reference
limit <- 1e-7 + 1e-6 * abs(reference)
matches <- is.finite(difference) & abs(difference) <= limit
comparison <- data.frame(Metric = {_r_str_vector([m[0] for m in metrics])}, StatCraft = reference,
                         R = actual, Difference = difference, WithinTolerance = matches)
print(comparison, row.names = FALSE, digits = 10)
cat(if (all(matches)) "Verification: PASS\\n" else "Verification: DIFFERENCES FOUND\\n")
print(data.frame(Row = worksheet_row, Count = counts, Size = sizes, Value = obs, CL = cl_vals, LCL = lcl_vals, UCL = ucl_vals, Signal = t1_failed), row.names = FALSE)

step_line <- function(x, y, ...) {{
  for (j in seq_along(x)) {{
    if (!is.na(y[j])) segments(x[j] - 0.5, y[j], x[j] + 0.5, y[j], ...)
    if (j < length(x) && !is.na(y[j]) && !is.na(y[j + 1L])) {{
      segments(x[j] + 0.5, y[j], x[j] + 0.5, y[j + 1L], ...)
    }}
  }}
}}
x_idx <- seq_len(n_pts)
ylim_vals <- range(c(obs, cl_vals, lcl_vals, ucl_vals), na.rm = TRUE)
if (diff(ylim_vals) == 0) ylim_vals <- ylim_vals + c(0, 1)
plot(x_idx, obs, type = "b", pch = 19, col = ifelse(t1_failed, "firebrick", "#193354"),
     xlim = c(0.5, n_pts + 0.5), ylim = ylim_vals,
     main = paste({json.dumps(f'{chart_type} Chart: {var_name}', ensure_ascii=False)}),
     xlab = "Subgroup", ylab = {json.dumps(y_label)})
step_line(x_idx, cl_vals, col = "darkgreen", lty = 1)
step_line(x_idx, ucl_vals, col = "firebrick", lty = 2)
step_line(x_idx, lcl_vals, col = "firebrick", lty = 2)
"""


def _build_gage_rr_script(sheet, entry):
    params = entry['recipe']['parameters']
    result = entry['result']
    indices = [params['measurement_index'], params['part_index'], params['operator_index']]
    if any(not isinstance(i, int) or i < 0 or i >= len(sheet.columns) for i in indices) or len(set(indices)) != 3:
        raise ValueError('The saved Gage R&R measurement, part, or operator column is unavailable.')
    m_col, p_col, o_col = [sheet.columns[i] for i in indices]
    if m_col.kind != 'number' or any(c.kind not in ('number', 'text') for c in (p_col, o_col)):
        raise ValueError('Gage R&R measurement must be numeric; parts and operators must be numeric or text.')

    rows = list(result['row_indices'])
    meas_vals = []
    part_vals = []
    op_vals = []
    for r in rows:
        if r >= len(m_col.values) or r >= len(p_col.values) or r >= len(o_col.values):
            raise ValueError('The worksheet no longer contains all analyzed Gage R&R rows.')
        mv = normalize_numeric(m_col.values[r])
        pv = p_col.values[r]
        ov = o_col.values[r]
        if mv is None or not math.isfinite(float(mv)) or pv is None or ov is None:
            raise ValueError('Analyzed Gage R&R rows contain missing values; rerun first.')
        meas_vals.append(float(mv))
        part_vals.append(str(pv))
        op_vals.append(str(ov))

    part_levels = [str(v) for v in result['parts']]
    op_levels = [str(v) for v in result['operators']]
    opts = result.get('options', result.get('settings', {}))
    study_mult = float(opts.get('study_multiplier', 6.0))
    tolerance = opts.get('tolerance')
    process_stdev = opts.get('process_stdev')
    interaction_alpha = float(opts.get('interaction_alpha', 0.05))
    remove_interaction = bool(opts.get('remove_interaction', True))

    anova_full = {row['source']: row for row in result['anova_with_interaction']}
    vc_map = {row['source']: row for row in result['variance_components']}

    metrics = [
        ('SS Part', anova_full['Part']['ss'], 'ss_part'),
        ('SS Operator', anova_full['Operator']['ss'], 'ss_op'),
        ('SS Interaction', anova_full['Part * Operator']['ss'], 'ss_int'),
        ('SS Repeatability', anova_full['Repeatability']['ss'], 'ss_err'),
        ('SS Total', anova_full['Total']['ss'], 'ss_total'),
    ]
    for src, r_var_expr, r_sd_expr, r_sv_expr in [
        ('Total Gage R&R', 'grr_var', 'sqrt(grr_var)', 'grr_sv'),
        ('Repeatability', 'repeat_var', 'sqrt(repeat_var)', 'repeat_sv'),
        ('Reproducibility', 'repro_var', 'sqrt(repro_var)', 'repro_sv'),
        ('Operator', 'op_var', 'sqrt(op_var)', 'op_sv'),
        ('Part * Operator', 'int_var', 'sqrt(int_var)', 'int_sv'),
        ('Part-To-Part', 'part_var', 'sqrt(part_var)', 'part_sv'),
        ('Total Variation', 'total_var', 'sqrt(total_var)', 'total_sv'),
    ]:
        if src not in vc_map:
            continue
        row = vc_map[src]
        metrics.append((f'{src} Var', float(row['variance']), r_var_expr))
        metrics.append((f'{src} StudyVar', float(row['study_variation']), r_sv_expr))
        if row.get('percent_study_variation') is not None:
            pct_sv_expr = f'100.0 * {r_sd_expr} / sqrt(total_var)'
            metrics.append((f'{src} %StudyVar', float(row['percent_study_variation']), pct_sv_expr))
        if tolerance is not None and row.get('percent_tolerance') is not None:
            metrics.append((f'{src} %Tol', float(row['percent_tolerance']), f'100.0 * {r_sv_expr} / tol'))
        if process_stdev is not None and row.get('percent_process') is not None:
            metrics.append((f'{src} %Process', float(row['percent_process']), f'100.0 * {r_sd_expr} / proc_sd'))
    if result.get('ndc') is not None:
        metrics.append(('ndc', float(result['ndc']), 'as.numeric(ndc)'))

    settings_json = json.dumps({
        'measurement': m_col.name,
        'part': p_col.name,
        'operator': o_col.name,
        'parts': len(part_levels),
        'operators': len(op_levels),
        'replicates': result['repeats'],
        'study_multiplier': study_mult,
        'interaction_alpha': interaction_alpha,
        'remove_interaction': remove_interaction,
        'tolerance': tolerance,
        'process_stdev': process_stdev,
    }, ensure_ascii=False)

    return f"""# StatCraft independent base-R Balanced Crossed Gage R&R verification
# Saved settings: {settings_json}

worksheet_row <- {_r_int_vector([r + 1 for r in rows])}
part_f <- factor({_r_str_vector(part_vals)}, levels = {_r_str_vector(part_levels)})
op_f <- factor({_r_str_vector(op_vals)}, levels = {_r_str_vector(op_levels)})
measurement <- {_vector(meas_vals)}

study_mult <- {repr(float(study_mult))}
interaction_alpha <- {repr(float(interaction_alpha))}
remove_interaction <- {_r_bool(remove_interaction)}
tol <- {_r_num(tolerance)}
proc_sd <- {_r_num(process_stdev)}

n_parts <- nlevels(part_f)
n_ops <- nlevels(op_f)
cell_counts <- table(part_f, op_f)
repeats <- as.integer(cell_counts[1L, 1L])
if (any(cell_counts != repeats) || repeats < 2L) {{
  stop("Balanced crossed Gage R&R requires at least 2 equal replicates per cell.")
}}

# Center measurements before squaring sums of squares
centered <- measurement - measurement[1L]
grand <- mean(centered)
part_means <- as.numeric(tapply(centered, part_f, mean))
op_means <- as.numeric(tapply(centered, op_f, mean))
cell_means <- matrix(as.numeric(tapply(centered, list(part_f, op_f), mean)), nrow = n_parts, ncol = n_ops)

pm_mat <- matrix(part_means, nrow = n_parts, ncol = n_ops)
om_mat <- matrix(op_means, nrow = n_parts, ncol = n_ops, byrow = TRUE)

ss_part <- n_ops * repeats * sum((part_means - grand)^2)
ss_op <- n_parts * repeats * sum((op_means - grand)^2)
ss_int <- repeats * sum((cell_means - pm_mat - om_mat + grand)^2)
cell_vals <- cell_means[cbind(as.integer(part_f), as.integer(op_f))]
ss_err <- sum((centered - cell_vals)^2)
ss_total <- sum((centered - grand)^2)

df_part <- n_parts - 1L
df_op <- n_ops - 1L
df_int <- (n_parts - 1L) * (n_ops - 1L)
df_err <- n_parts * n_ops * (repeats - 1L)

ms_part <- ss_part / df_part
ms_op <- ss_op / df_op
ms_int <- ss_int / df_int
ms_err <- ss_err / df_err

p_int <- if (ms_err == 0) {{ if (ms_int > 0) 0.0 else NA_real_ }} else pf(ms_int / ms_err, df_int, df_err, lower.tail = FALSE)
pooled <- isTRUE(remove_interaction) && !is.na(p_int) && (p_int >= interaction_alpha)

if (pooled) {{
  denom <- (ss_int + ss_err) / (df_int + df_err)
  repeat_var <- denom
  int_var <- 0.0
}} else {{
  denom <- ms_int
  repeat_var <- ms_err
  int_var <- max(0.0, (ms_int - ms_err) / repeats)
}}
op_var <- max(0.0, (ms_op - denom) / (n_parts * repeats))
part_var <- max(0.0, (ms_part - denom) / (n_ops * repeats))
repro_var <- op_var + int_var
grr_var <- repeat_var + repro_var
total_var <- grr_var + part_var

grr_sv <- study_mult * sqrt(grr_var)
repeat_sv <- study_mult * sqrt(repeat_var)
repro_sv <- study_mult * sqrt(repro_var)
op_sv <- study_mult * sqrt(op_var)
int_sv <- study_mult * sqrt(int_var)
part_sv <- study_mult * sqrt(part_var)
total_sv <- study_mult * sqrt(total_var)

ndc <- if (grr_var > 0) max(1L, as.integer(floor(1.41 * sqrt(part_var) / sqrt(grr_var)))) else if (part_var == 0) 1L else NA_integer_

cat("Runtime\\n")
print(sessionInfo())

cat("\\nStatCraft versus R\\n")
reference <- {_vector([m[1] for m in metrics])}
actual <- c({', '.join(m[2] for m in metrics)})
difference <- actual - reference
limit <- 1e-7 + 1e-6 * abs(reference)
matches <- is.finite(difference) & abs(difference) <= limit
comparison <- data.frame(Metric = {_r_str_vector([m[0] for m in metrics])}, StatCraft = reference,
                         R = actual, Difference = difference, WithinTolerance = matches)
print(comparison, row.names = FALSE, digits = 10)
cat(if (all(matches)) "Verification: PASS\\n" else "Verification: DIFFERENCES FOUND\\n")

old <- par(mfrow = c(2, 1), mar = c(4, 4, 3, 1))
if (total_var > 0) {{
  comp_vars <- c(grr_var, repeat_var, repro_var, part_var)
  pct_contrib <- 100.0 * comp_vars / total_var
  pct_sv <- 100.0 * sqrt(comp_vars) / sqrt(total_var)
  bar_mat <- rbind(pct_contrib, pct_sv)
  colnames(bar_mat) <- c("Total GRR", "Repeat", "Reprod", "Part-to-Part")
  barplot(bar_mat, beside = TRUE, col = c("#25729C", "#B45309"),
          main = paste("Components of Variation:", {json.dumps(m_col.name, ensure_ascii=False)}),
          ylab = "Percent (%)", ylim = c(0, max(100, max(bar_mat) * 1.15)))
  legend("topright", legend = c("%Contribution", "%Study Var"), fill = c("#25729C", "#B45309"), bty = "n")
}} else {{
  plot.new(); title(main = "Components of Variation (Zero Variation)")
}}
interaction.plot(part_f, op_f, measurement, type = "b", pch = 19,
                 col = seq_len(n_ops), xlab = {json.dumps(p_col.name, ensure_ascii=False)},
                 ylab = paste("Mean of", {json.dumps(m_col.name, ensure_ascii=False)}),
                 trace.label = {json.dumps(o_col.name, ensure_ascii=False)},
                 main = "Part * Operator Interaction")
par(old)
"""


def build_script(presenter, entry):
    recipe = entry.get('recipe', {})
    action = recipe.get('action')
    if action not in SUPPORTED:
        raise ValueError(
            'R verification supports OLS regression, two-level factorial DOE, I-MR, Xbar-R/S, '
            'Attribute charts (P/NP/C/U/P\'/U\'), Normal Capability, and Crossed Gage R&R.'
        )
    if presenter.result_stale(entry) is not False:
        raise ValueError('Rerun the result on its source worksheet before exporting verification inputs.')
    sheet = presenter.result_worksheet(entry)
    if action == 'imr_chart':
        return _build_imr_script(sheet, entry)
    if action == 'subgroup_control_chart':
        return _build_subgroup_script(sheet, entry)
    if action == 'attribute_control_chart':
        return _build_attribute_script(sheet, entry)
    if action == 'normal_capability':
        return _build_capability_script(sheet, entry)
    if action == 'gage_rr':
        return _build_gage_rr_script(sheet, entry)
    return _build_ols_script(sheet, entry)
