"""Equal variance tests (Levene/Brown-Forsythe, Bartlett, Bonett, Multiple Comparisons) and variance CIs."""
import math
from scipy import stats
from .engine import normalize_numeric
from .inference import _summary


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    return ordered[n // 2] if n % 2 else math.fsum((ordered[n // 2 - 1] / 2, ordered[n // 2] / 2))


def _bonett_se_log_sd(clean, mean, median, sd, center="mean", bounded=False):
    """Scale-invariant Bonett standard error of ln(s) for n >= 2."""
    n = len(clean)
    if sd <= 0 or n < 2:
        return 0.0
    u = [(x - mean) / sd for x in clean]
    m2 = math.fsum(v * v for v in u) / n
    v4 = [(x - median) / sd for x in clean] if center == "median" else u
    m4 = math.fsum(v ** 4 for v in v4) / n
    gamma = (m4 / (m2 ** 2)) if m2 > 0 else 3.0
    if bounded:
        gamma = max(1.2, min(50.0, gamma))
    var_log_s = max(1e-12, (gamma - (n - 3.0) / n) / (4.0 * (n - 1.0)))
    return math.sqrt(var_log_s)


def _weighted_log_sd_test(sds, se_logs, k):
    """Inverse-variance weighted chi-square test on log standard deviations."""
    if any(sd <= 0 for sd in sds) or any(se <= 0 for se in se_logs):
        return None, None
    reference = max(sds)
    log_sds = [math.log(sd) - math.log(reference) for sd in sds]
    weights = [1.0 / (se ** 2) for se in se_logs]
    w_sum = math.fsum(weights)
    w_mean = math.fsum(w * l for w, l in zip(weights, log_sds)) / w_sum
    stat = max(0.0, math.fsum(w * ((l - w_mean) ** 2) for w, l in zip(weights, log_sds)))
    p = float(stats.chi2.sf(stat, k - 1))
    return stat, p


def _group_confidence_intervals(clean_groups, summaries, se_bonett_list, alpha):
    """Compute per-group Bonferroni-adjusted Bonett and Chi-square CIs for stdev and variance."""
    k = len(clean_groups)
    tail = alpha / (2.0 * k)
    z_crit = float(stats.norm.ppf(1.0 - tail))
    intervals = []
    for s, se_bonett in zip(summaries, se_bonett_list):
        n = s["count"]
        sd = s["sample_stdev"]
        var = sd ** 2
        df = n - 1
        if sd <= 0 or df < 1:
            intervals.append({
                "group": s["group"],
                "count": n,
                "stdev": sd,
                "variance": var,
                "bonett_ci_stdev": (0.0, 0.0),
                "bonett_ci_variance": (0.0, 0.0),
                "chi2_ci_stdev": (0.0, 0.0),
                "chi2_ci_variance": (0.0, 0.0),
            })
            continue
        b_lo = sd * math.exp(-z_crit * se_bonett)
        b_hi = sd * math.exp(z_crit * se_bonett)
        q_low = float(stats.chi2.ppf(tail, df))
        q_high = float(stats.chi2.ppf(1.0 - tail, df))
        c_lo = sd * math.sqrt(df / q_high) if q_high > 0 else 0.0
        c_hi = sd * math.sqrt(df / q_low) if q_low > 0 else math.inf
        intervals.append({
            "group": s["group"],
            "count": n,
            "stdev": sd,
            "variance": var,
            "bonett_ci_stdev": (b_lo, b_hi),
            "bonett_ci_variance": (b_lo ** 2, b_hi ** 2),
            "chi2_ci_stdev": (c_lo, c_hi),
            "chi2_ci_variance": (c_lo ** 2, c_hi ** 2),
        })
    return intervals


def equal_variances(groups, method='Levene', alpha=0.05):
    """Independent groups, each >=2 nonmissing observations; no pairing.

    Supports Levene (median-centered Brown-Forsythe), Bartlett, Bonett,
    and MultipleComparisons, along with per-group Bonferroni-adjusted
    Bonett and Chi-square confidence intervals for stdev and variance.
    Numeric missing normalization omits None/sentinel/NaN/infinities per group.
    """
    if isinstance(alpha, bool):
        raise ValueError('Alpha must be a finite number strictly between 0 and 1.')
    try:
        alpha = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError('Alpha must be a finite number strictly between 0 and 1.') from exc
    if not math.isfinite(alpha) or alpha <= 0.0 or alpha >= 1.0:
        raise ValueError('Alpha must be strictly between 0 and 1.')

    if not isinstance(method, str):
        raise ValueError('Method must be Levene, Bartlett, Bonett, or MultipleComparisons.')
    selected = method.strip().lower()
    if selected in ('levene', 'brown-forsythe'):
        selected = 'levene'
    elif selected in ('multiplecomparisons', 'multiple_comparisons', 'multiple comparisons', 'mci'):
        selected = 'multiplecomparisons'
    elif selected not in ('bartlett', 'bonett'):
        raise ValueError('Method must be Levene, Bartlett, Bonett, or MultipleComparisons.')

    groups = list(groups)
    if len(groups) < 2:
        raise ValueError('At least two groups are required.')
    clean_groups = []
    summaries = []
    try:
        for index, group in enumerate(groups):
            raw = list(group)
            clean = []
            for value in raw:
                value = normalize_numeric(value)
                if value is not None:
                    clean.append(value)
            if len(clean) < 2:
                raise ValueError(f'Group {index + 1} requires at least two finite nonmissing observations.')
            n, mean, sd, _ = _summary(clean)
            median = _median(clean)
            clean_groups.append(clean)
            summaries.append(dict(group=index + 1, count=n, missing=len(raw) - n,
                                  mean=mean, median=median, sample_stdev=sd))
        k = len(groups)
        total = sum(s['count'] for s in summaries)
        sds = [s['sample_stdev'] for s in summaries]

        se_bonett_list = [
            _bonett_se_log_sd(g, s['mean'], s['median'], s['sample_stdev'], center="mean", bounded=False)
            for g, s in zip(clean_groups, summaries)
        ]
        se_mc_list = [
            _bonett_se_log_sd(g, s['mean'], s['median'], s['sample_stdev'], center="median", bounded=True)
            for g, s in zip(clean_groups, summaries)
        ]
        bonett_stat, bonett_p = _weighted_log_sd_test(sds, se_bonett_list, k)
        mc_stat, mc_p = _weighted_log_sd_test(sds, se_mc_list, k)
        confidence_intervals = _group_confidence_intervals(clean_groups, summaries, se_bonett_list, alpha)

        if selected == 'levene':
            deviations = [[abs(v - s['median']) for v in g] for g, s in zip(clean_groups, summaries)]
            scale = max(v for g in deviations for v in g)
            if not math.isfinite(scale):
                raise ValueError('Absolute deviations exceed the supported numeric range.')
            if scale == 0:
                raise ValueError('Levene inference is undefined without residual variation in absolute deviations.')
            z = [[v / scale for v in g] for g in deviations]
            means = [math.fsum(g) / len(g) for g in z]
            grand = math.fsum(s['count'] / total * m for s, m in zip(summaries, means))
            between = math.fsum(s['count'] * (m - grand) ** 2 for s, m in zip(summaries, means))
            within = math.fsum((v - m) ** 2 for g, m in zip(z, means) for v in g)
            if within <= 0:
                raise ValueError('Levene inference is undefined without residual variation in absolute deviations.')
            statistic = (between / (k - 1)) / (within / (total - k))
            p = float(stats.f.sf(statistic, k - 1, total - k))
            label = 'Levene (median-centered Brown-Forsythe F test)'
            df = [k - 1, total - k]
            denominator = total - k
            assumptions = 'Independent observations and groups; common population variances under the null. Median-centered absolute deviations are compared using an approximate F distribution; this method is less sensitive to nonnormality than Bartlett.'
        elif selected == 'bartlett':
            if any(sd <= 0 for sd in sds):
                raise ValueError('Bartlett requires positive sample variance in every group.')
            # Common scaling cancels from the log likelihood; no variance squaring overflow.
            reference = max(sds)
            log_ratios = [2 * (math.log(sd) - math.log(reference)) for sd in sds]
            pooled = math.fsum((s['count'] - 1) / (total - k) * math.exp(lr)
                               for s, lr in zip(summaries, log_ratios))
            correction = 1 + (math.fsum(1 / (s['count'] - 1) for s in summaries) - 1 / (total - k)) / (3 * (k - 1))
            numerator = (total - k) * math.log(pooled) - math.fsum((s['count'] - 1) * lr for s, lr in zip(summaries, log_ratios))
            statistic = max(0., numerator / correction)
            p = float(stats.chi2.sf(statistic, k - 1))
            label = 'Bartlett (corrected chi-square test)'
            df = k - 1
            denominator = None
            assumptions = 'Independent observations and groups from normal populations; equal population variances under the null. Bartlett is sensitive to departures from normality; its chi-square reference is approximate.'
        elif selected == 'bonett':
            if bonett_stat is None:
                raise ValueError('Bonett requires positive sample variance in every group.')
            statistic = bonett_stat
            p = bonett_p
            label = 'Bonett (kurtosis-adjusted chi-square test)'
            df = k - 1
            denominator = None
            assumptions = 'Independent observations and groups; equal population variances under the null. Bonett adjusts for sample kurtosis and is robust to nonnormality.'
        else:
            if mc_stat is None:
                raise ValueError('Multiple Comparisons requires positive sample variance in every group.')
            statistic = mc_stat
            p = mc_p
            label = 'Multiple Comparisons (kurtosis-adjusted chi-square test)'
            df = k - 1
            denominator = None
            assumptions = 'Independent observations and groups; equal population variances under the null. Multiple Comparisons uses bounded kurtosis-adjusted log standard errors.'

        if not math.isfinite(statistic) or not math.isfinite(p):
            raise ValueError('Variance-test arithmetic exceeds the supported numeric range.')
    except OverflowError as exc:
        raise ValueError('Variance-test arithmetic exceeds the supported numeric range.') from exc

    return dict(
        method=label,
        test_statistic=statistic,
        p_value=p,
        df=df,
        df_numerator=k - 1,
        df_denominator=denominator,
        alpha=alpha,
        bonett_p_value=bonett_p,
        multiple_comparisons_p_value=mc_p,
        confidence_intervals=confidence_intervals,
        group_statistics=summaries,
        count=total,
        missing=sum(s['missing'] for s in summaries),
        assumptions=assumptions,
        warnings=[],
        missing_policy='Numeric missing values (None, sentinel, NaN and infinities) are omitted independently within each group.',
    )
