"""Extended Minitab Power and Sample Size Calculators.

Covers:
- 1 Variance (Chi-Square)
- 2 Variances (F-test)
- 1-Sample Poisson Rate
- 2-Sample Poisson Rates
- Equivalence Tests (TOST: 1-Sample, 2-Sample, Paired)
- Sample Size for Estimation (Mean, Proportion, Poisson Rate)
- Sample Size for Tolerance Intervals (Normal)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
import numpy as np
from scipy import stats


def _binary_search_n(calc_power_fn, target_power: float, low: int = 2, high: int = 100000) -> tuple[int, float]:
    while low < high:
        mid = (low + high) // 2
        if calc_power_fn(mid) >= target_power:
            high = mid
        else:
            low = mid + 1
    return low, float(calc_power_fn(low))


def one_variance_power(
    ratio: float = 1.5,
    sample_size: Optional[int] = None,
    target_power: Optional[float] = 0.80,
    alpha: float = 0.05,
    alternative: str = "two_sided",
) -> Dict[str, Any]:
    """1-Variance Chi-square test power/sample size (ratio = sigma_1 / sigma_0)."""
    if ratio <= 0 or abs(ratio - 1.0) < 1e-12:
        raise ValueError("Ratio (StDev1 / StDev0) must be positive and not equal to 1.0.")
    if not 0 < alpha < 1:
        raise ValueError("Alpha must be strictly between 0 and 1.")

    alt = alternative.strip().lower()
    r2 = float(ratio) ** 2

    def power_fn(n: int) -> float:
        df = max(1, n - 1)
        if alt in ("greater", "upper"):
            c_up = stats.chi2.ppf(1.0 - alpha, df)
            return float(1.0 - stats.chi2.cdf(c_up / r2, df))
        if alt in ("less", "lower"):
            c_lo = stats.chi2.ppf(alpha, df)
            return float(stats.chi2.cdf(c_lo / r2, df))
        c_lo = stats.chi2.ppf(alpha / 2.0, df)
        c_up = stats.chi2.ppf(1.0 - alpha / 2.0, df)
        return float(stats.chi2.cdf(c_lo / r2, df) + (1.0 - stats.chi2.cdf(c_up / r2, df)))

    if sample_size is not None and sample_size >= 2:
        n_res = int(sample_size)
        act_p = power_fn(n_res)
        tp = None
    else:
        tp = float(target_power or 0.80)
        if not alpha < tp < 1.0:
            raise ValueError("Target power must lie between alpha and 1.0.")
        n_res, act_p = _binary_search_n(power_fn, tp, 2, 50000)

    return {
        "analysis": "one_variance_power",
        "ratio": float(ratio),
        "sample_size": n_res,
        "target_power": tp,
        "actual_power": act_p,
        "alpha": float(alpha),
        "alternative": alt,
    }


def two_variances_power(
    ratio: float = 1.5,
    sample_size: Optional[int] = None,
    target_power: Optional[float] = 0.80,
    alpha: float = 0.05,
    alternative: str = "two_sided",
) -> Dict[str, Any]:
    """2-Variances F-test power/sample size (ratio = sigma_1 / sigma_2, equal n)."""
    if ratio <= 0 or abs(ratio - 1.0) < 1e-12:
        raise ValueError("Ratio (StDev1 / StDev2) must be positive and not equal to 1.0.")
    if not 0 < alpha < 1:
        raise ValueError("Alpha must be strictly between 0 and 1.")

    alt = alternative.strip().lower()
    r2 = float(ratio) ** 2

    def power_fn(n: int) -> float:
        df = max(1, n - 1)
        if alt in ("greater", "upper"):
            f_up = stats.f.ppf(1.0 - alpha, df, df)
            return float(1.0 - stats.f.cdf(f_up / r2, df, df))
        if alt in ("less", "lower"):
            f_lo = stats.f.ppf(alpha, df, df)
            return float(stats.f.cdf(f_lo / r2, df, df))
        f_lo = stats.f.ppf(alpha / 2.0, df, df)
        f_up = stats.f.ppf(1.0 - alpha / 2.0, df, df)
        return float(stats.f.cdf(f_lo / r2, df, df) + (1.0 - stats.f.cdf(f_up / r2, df, df)))

    if sample_size is not None and sample_size >= 2:
        n_res = int(sample_size)
        act_p = power_fn(n_res)
        tp = None
    else:
        tp = float(target_power or 0.80)
        n_res, act_p = _binary_search_n(power_fn, tp, 2, 50000)

    return {
        "analysis": "two_variances_power",
        "ratio": float(ratio),
        "sample_size_per_group": n_res,
        "target_power": tp,
        "actual_power": act_p,
        "alpha": float(alpha),
        "alternative": alt,
    }


def one_poisson_rate_power(
    baseline_rate: float = 2.0,
    comparison_rate: float = 3.0,
    sample_size: Optional[int] = None,
    target_power: Optional[float] = 0.80,
    alpha: float = 0.05,
    alternative: str = "two_sided",
) -> Dict[str, Any]:
    """1-Sample Poisson Rate power/sample size using score/normal approximation."""
    if baseline_rate <= 0 or comparison_rate <= 0 or abs(comparison_rate - baseline_rate) < 1e-12:
        raise ValueError("Baseline and comparison rates must be positive and distinct.")
    alt = alternative.strip().lower()
    z_crit = stats.norm.ppf(1.0 - alpha / 2.0 if alt == "two_sided" else 1.0 - alpha)

    def power_fn(n: int) -> float:
        se0 = math.sqrt(baseline_rate / n)
        se1 = math.sqrt(comparison_rate / n)
        diff = abs(comparison_rate - baseline_rate)
        z = (diff - z_crit * se0) / se1
        return float(stats.norm.cdf(z))

    if sample_size is not None and sample_size >= 1:
        n_res = int(sample_size)
        act_p = power_fn(n_res)
        tp = None
    else:
        tp = float(target_power or 0.80)
        n_res, act_p = _binary_search_n(power_fn, tp, 1, 100000)

    return {
        "analysis": "one_poisson_rate_power",
        "baseline_rate": float(baseline_rate),
        "comparison_rate": float(comparison_rate),
        "sample_size": n_res,
        "target_power": tp,
        "actual_power": act_p,
        "alpha": float(alpha),
        "alternative": alt,
    }


def two_poisson_rates_power(
    rate1: float = 3.0,
    rate2: float = 2.0,
    sample_size: Optional[int] = None,
    target_power: Optional[float] = 0.80,
    alpha: float = 0.05,
    alternative: str = "two_sided",
) -> Dict[str, Any]:
    """2-Sample Poisson Rates power/sample size (equal sample sizes)."""
    if rate1 <= 0 or rate2 <= 0 or abs(rate1 - rate2) < 1e-12:
        raise ValueError("Rates must be positive and distinct.")
    alt = alternative.strip().lower()
    z_crit = stats.norm.ppf(1.0 - alpha / 2.0 if alt == "two_sided" else 1.0 - alpha)

    def power_fn(n: int) -> float:
        r_pool = 0.5 * (rate1 + rate2)
        se0 = math.sqrt(2.0 * r_pool / n)
        se1 = math.sqrt((rate1 + rate2) / n)
        z = (abs(rate1 - rate2) - z_crit * se0) / se1
        return float(stats.norm.cdf(z))

    if sample_size is not None and sample_size >= 1:
        n_res = int(sample_size)
        act_p = power_fn(n_res)
        tp = None
    else:
        tp = float(target_power or 0.80)
        n_res, act_p = _binary_search_n(power_fn, tp, 1, 100000)

    return {
        "analysis": "two_poisson_rates_power",
        "rate1": float(rate1),
        "rate2": float(rate2),
        "sample_size_per_group": n_res,
        "target_power": tp,
        "actual_power": act_p,
        "alpha": float(alpha),
        "alternative": alt,
    }


def equivalence_tost_power(
    design: str = "2-Sample",
    lower_limit: float = -1.0,
    upper_limit: float = 1.0,
    difference: float = 0.0,
    stdev: float = 1.0,
    sample_size: Optional[int] = None,
    target_power: Optional[float] = 0.80,
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """Power and sample size for Equivalence Tests (TOST 1-Sample, 2-Sample, Paired)."""
    if lower_limit >= upper_limit:
        raise ValueError("Lower equivalence limit must be strictly less than upper limit.")
    if not (lower_limit < difference < upper_limit):
        raise ValueError("Assumed true difference must fall strictly inside equivalence limits.")
    if stdev <= 0:
        raise ValueError("Standard deviation must be positive.")

    d_low = design.strip().lower()
    is_two = "2" in d_low

    def power_fn(n: int) -> float:
        df = 2 * n - 2 if is_two else max(1, n - 1)
        se = stdev * math.sqrt(2.0 / n) if is_two else stdev / math.sqrt(n)
        t_crit = float(stats.t.ppf(1.0 - alpha, df))
        ncp_low = (difference - lower_limit) / se
        ncp_high = (upper_limit - difference) / se
        # Two one-sided t rejection region probability under noncentral t / normal approx with exact df
        p1 = float(1.0 - stats.t.cdf(t_crit - ncp_low, df))
        p2 = float(stats.t.cdf(-t_crit + ncp_high, df))
        return float(max(0.0, min(1.0, p1 + p2 - 1.0)))

    if sample_size is not None and sample_size >= 2:
        n_res = int(sample_size)
        act_p = power_fn(n_res)
        tp = None
    else:
        tp = float(target_power or 0.80)
        n_res, act_p = _binary_search_n(power_fn, tp, 3, 50000)

    return {
        "analysis": "equivalence_tost_power",
        "design": design,
        "lower_limit": float(lower_limit),
        "upper_limit": float(upper_limit),
        "difference": float(difference),
        "stdev": float(stdev),
        "sample_size": n_res,
        "target_power": tp,
        "actual_power": act_p,
        "alpha": float(alpha),
    }


def sample_size_estimation(
    parameter: str = "Mean (Normal)",
    planning_value: float = 1.0,
    margin_of_error: float = 0.2,
    confidence: float = 0.95,
) -> Dict[str, Any]:
    """Calculate Sample Size for Estimation given margin of error and confidence level."""
    if margin_of_error <= 0:
        raise ValueError("Margin of error must be strictly positive.")
    if not 0.5 < confidence < 1.0:
        raise ValueError("Confidence level must be between 0.50 and 1.00.")

    z = float(stats.norm.ppf(1.0 - (1.0 - confidence) / 2.0))
    p_low = parameter.strip().lower()
    if "proportion" in p_low:
        p = float(planning_value)
        if not 0.0 < p < 1.0:
            raise ValueError("Planning proportion must be strictly between 0 and 1.")
        n = int(math.ceil((z ** 2) * p * (1.0 - p) / (margin_of_error ** 2)))
    elif "poisson" in p_low:
        lam = float(planning_value)
        if lam <= 0:
            raise ValueError("Planning Poisson rate must be positive.")
        n = int(math.ceil((z ** 2) * lam / (margin_of_error ** 2)))
    else:
        sigma = float(planning_value)
        if sigma <= 0:
            raise ValueError("Planning standard deviation must be positive.")
        n = int(math.ceil((z * sigma / margin_of_error) ** 2))

    return {
        "analysis": "sample_size_estimation",
        "parameter": parameter,
        "planning_value": float(planning_value),
        "margin_of_error": float(margin_of_error),
        "confidence": float(confidence),
        "sample_size": max(2, n),
    }


EQUIVALENCE_DESIGNS = ("1-Sample", "2-Sample", "Paired", "2x2 Crossover Design")


def equivalence_difference_power(*, design="1-Sample", lower_limit=-1.0, upper_limit=1.0,
                                 difference=None, stdev=1.0, sample_size=None, target_power=None,
                                 alpha=.05, difference_side="Upper"):
    """Integrate the probability of passing both tests over the estimated variance."""
    from scipy.integrate import quad
    from scipy.optimize import brentq

    if design not in EQUIVALENCE_DESIGNS or difference_side not in ("Lower", "Upper"):
        raise ValueError("Choose a valid equivalence design and direction.")
    if not all(math.isfinite(v) for v in (lower_limit, upper_limit, stdev)) or lower_limit >= upper_limit or stdev <= 0:
        raise ValueError("Enter ordered finite equivalence limits and a positive standard deviation.")
    if not 0 < alpha < .5:
        raise ValueError("Significance level must be between 0 and 0.5.")
    if sum(v is not None for v in (difference, sample_size, target_power)) != 2:
        raise ValueError("Enter two of difference, sample size, and target power.")
    if difference is not None and not lower_limit < difference < upper_limit:
        raise ValueError("The assumed difference must be within the equivalence limits.")
    if sample_size is not None and (type(sample_size) is not int or not 2 <= sample_size <= 100_000):
        raise ValueError("Enter a whole sample size from 2 to 100,000.")
    if target_power is not None and not alpha < target_power < 1:
        raise ValueError("Target power must exceed significance level and be below 1.")

    def achieved(n, delta):
        df = 2 * n - 2 if design in ("2-Sample", "2x2 Crossover Design") else n - 1
        se = stdev * math.sqrt((2 if design == "2-Sample" else 1) / n)
        cutoff = stats.t.isf(alpha, df)
        lower = (lower_limit - delta) / se
        upper = (upper_limit - delta) / se
        end = stats.chi2.cdf(df * ((upper - lower) / (2 * cutoff)) ** 2, df)

        def conditional(p):
            margin = cutoff * math.sqrt(stats.chi2.ppf(p, df) / df)
            return max(0.0, stats.norm.cdf(upper - margin) - stats.norm.cdf(lower + margin))

        return float(quad(conditional, 0, end, epsabs=2e-9)[0])

    if difference is None:
        midpoint = (lower_limit + upper_limit) / 2
        if achieved(sample_size, midpoint) < target_power:
            raise ValueError("Target power is unattainable at this sample size.")
        edge = upper_limit if difference_side == "Upper" else lower_limit
        difference = brentq(lambda d: achieved(sample_size, d) - target_power, *sorted((edge, midpoint)))
    elif sample_size is None:
        low, high = 2, 2
        while high < 100_000 and achieved(high, difference) < target_power:
            high = min(100_000, high * 2)
        if achieved(high, difference) < target_power:
            raise ValueError("Required sample size exceeds 100,000.")
        sample_size, _ = _binary_search_n(lambda n: achieved(n, difference), target_power, low, high)

    units = {"2-Sample": "per group", "Paired": "pairs", "2x2 Crossover Design": "per sequence"}
    return dict(analysis="equivalence_difference_power", design=design, lower_limit=lower_limit,
                upper_limit=upper_limit, difference=difference, stdev=stdev, alpha=alpha,
                sample_size=sample_size, sample_size_units=units.get(design, "observations"),
                target_power=target_power, actual_power=achieved(sample_size, difference))


ESTIMATION_PARAMETERS = (
    "Mean (Normal)", "Standard Deviation (Normal)", "Variance (Normal)",
    "Proportion (Binomial)", "Poisson Rate", "Poisson Mean",
)


def estimation_planning(*, parameter="Mean (Normal)", planning_value=1.0,
                        confidence=.95, interval_type="Two-sided", known_stdev=False,
                        exposure=1.0, margins=None, sample_sizes=None):
    """Plan sample size or interval precision using the specified interval method."""
    if parameter not in ESTIMATION_PARAMETERS:
        raise ValueError("Choose a supported estimation parameter.")
    if not .5 < confidence < 1 or interval_type not in ("Two-sided", "Lower bound", "Upper bound"):
        raise ValueError("Choose a valid confidence level and interval type.")
    if not math.isfinite(planning_value) or planning_value <= 0:
        raise ValueError("Planning value must be finite and positive.")
    if parameter == "Proportion (Binomial)" and planning_value >= 1:
        raise ValueError("Planning proportion must be below 1.")
    if not math.isfinite(exposure) or exposure <= 0:
        raise ValueError("Length of observation must be finite and positive.")
    if (margins is None) == (sample_sizes is None):
        raise ValueError("Enter either margins of error or sample sizes.")
    tail = (1 - confidence) / (2 if interval_type == "Two-sided" else 1)
    minimum = 2 if parameter.endswith("(Normal)") and not (
        parameter == "Mean (Normal)" and known_stdev
    ) else 1
    cap = 1_000_000

    def errors(n):
        value = planning_value
        if parameter == "Mean (Normal)":
            critical = stats.norm.isf(tail) if known_stdev else stats.t.isf(tail, n - 1)
            error = float(critical * value / math.sqrt(n))
            lower_error, upper_error = error, error
        else:
            if parameter == "Proportion (Binomial)":
                events = n * value
                lo = stats.beta.ppf(tail, events, n - events + 1)
                hi = stats.beta.isf(tail, events + 1, n - events)
            elif parameter.startswith("Poisson"):
                time = n * (exposure if parameter == "Poisson Rate" else 1)
                events = value * time
                lo = stats.chi2.ppf(tail, 2 * events) / (2 * time)
                hi = stats.chi2.isf(tail, 2 * (events + 1)) / (2 * time)
            else:
                variance = value ** 2 if parameter.startswith("Standard Deviation") else value
                lo = (n - 1) * variance / stats.chi2.isf(tail, n - 1)
                hi = (n - 1) * variance / stats.chi2.ppf(tail, n - 1)
                if parameter.startswith("Standard Deviation"):
                    lo, hi = math.sqrt(lo), math.sqrt(hi)
            lower_error, upper_error = float(value - lo), float(hi - value)
        if interval_type == "Lower bound":
            upper_error = None
        if interval_type == "Upper bound":
            lower_error = None
        return lower_error, upper_error, max(v for v in (lower_error, upper_error) if v is not None)

    def row(n, target=None):
        lower, upper, margin = errors(n)
        return dict(sample_size=n, lower_margin=lower, upper_margin=upper, margin=margin,
                    target_margin=target)

    rows = []
    if margins is not None:
        if not margins or any(not math.isfinite(m) or m <= 0 for m in margins):
            raise ValueError("Enter positive, finite margins of error.")
        for margin in margins:
            lo, hi = minimum, minimum
            while hi < cap and errors(hi)[2] > margin:
                hi = min(cap, hi * 2)
            if errors(hi)[2] > margin:
                raise ValueError("The required sample size exceeds 1,000,000.")
            while lo < hi:
                mid = (lo + hi) // 2
                if errors(mid)[2] <= margin:
                    hi = mid
                else:
                    lo = mid + 1
            rows.append(row(lo, margin))
    else:
        if not sample_sizes or any(type(n) is not int or not minimum <= n <= cap for n in sample_sizes):
            raise ValueError(f"Enter whole sample sizes from {minimum} to 1,000,000.")
        rows = [row(n) for n in sample_sizes]
    return dict(analysis="estimation_planning", parameter=parameter, planning_value=planning_value,
                confidence=confidence, interval_type=interval_type,
                known_stdev=known_stdev if parameter == "Mean (Normal)" else None,
                exposure=exposure if parameter == "Poisson Rate" else None, rows=rows)


def _design_power(dfs, *, effect, replicates, target_power, stdev, alpha, center_points=0):
    from scipy.optimize import brentq

    if not math.isfinite(stdev) or stdev <= 0 or not 0 < alpha < 1:
        raise ValueError("Enter a positive standard deviation and significance level between 0 and 1.")
    if effect is not None and (not math.isfinite(effect) or effect <= 0):
        raise ValueError("Enter a finite positive effect.")
    if replicates is not None and (type(replicates) is not int or not 1 <= replicates <= 100_000):
        raise ValueError("Enter whole replicates from 1 to 100,000.")
    if target_power is not None and not alpha < target_power < 1:
        raise ValueError("Target power must exceed significance level and be below 1.")
    if sum(value is not None for value in (effect, replicates, target_power, center_points)) != 3:
        raise ValueError("Supply all settings except the quantity to calculate.")

    def achieved(r, e, c):
        numerator, denominator, multiplier, _ = dfs(r, c)
        if denominator <= 0:
            return 0.0
        if e == 0:
            return alpha
        critical = stats.f.isf(alpha, numerator, denominator)
        return float(stats.ncf.sf(critical, numerator, denominator, multiplier * (e / stdev) ** 2))

    if effect is None:
        if dfs(replicates, center_points)[1] <= 0:
            raise ValueError("The design has no error degrees of freedom.")
        high = stdev
        while achieved(replicates, high, center_points) < target_power:
            high *= 2
            if not math.isfinite(high):
                raise ValueError("The requested effect could not be calculated.")
        effect = brentq(lambda e: achieved(replicates, e, center_points) - target_power, 0, high)
    elif replicates is None or center_points is None:
        solving_replicates = replicates is None
        evaluate = (
            (lambda n: achieved(n, effect, center_points)) if solving_replicates
            else (lambda n: achieved(replicates, effect, n))
        )
        low, high = (1 if solving_replicates else 0), 100_000
        if evaluate(high) < target_power:
            raise ValueError("The target power is outside the supported search range.")
        while low < high:
            mid = (low + high) // 2
            if evaluate(mid) >= target_power:
                high = mid
            else:
                low = mid + 1
        if solving_replicates:
            replicates = low
        else:
            center_points = low
    _, error_df, _, runs = dfs(replicates, center_points)
    if error_df <= 0:
        raise ValueError("The design has no error degrees of freedom.")
    return dict(effect=effect, replicates=replicates, center_points=center_points, stdev=stdev,
                alpha=alpha, target_power=target_power,
                actual_power=achieved(replicates, effect, center_points),
                error_df=error_df, total_runs=runs)


def general_factorial_power(*, levels, stdev, effect=None, replicates=None, target_power=None,
                            order=None, blocked=False, alpha=.05):
    """Plan power for the factor with the most levels in a full factorial design."""
    from itertools import combinations

    if not 2 <= len(levels) <= 15 or any(type(k) is not int or not 2 <= k <= 100 for k in levels):
        raise ValueError("Enter 2 to 15 factors with 2 to 100 levels each.")
    order = len(levels) if order is None else order
    if type(order) is not int or not 1 <= order <= len(levels):
        raise ValueError("Model order must be between 1 and the number of factors.")
    runs = math.prod(levels)
    k = max(levels)
    df_model = sum(math.prod(term) for d in range(1, order + 1)
                   for term in combinations([v - 1 for v in levels], d))

    def dfs(r, _):
        n = runs * r
        return k - 1, n - 1 - df_model - (r - 1 if blocked else 0), n / (2 * k), n

    result = _design_power(dfs, effect=effect, replicates=replicates, target_power=target_power,
                           stdev=stdev, alpha=alpha)
    result.pop("center_points")
    return dict(analysis="general_factorial_power", levels=list(levels), order=order,
                blocked=blocked, **result)


def plackett_burman_power(*, factors, corner_points, stdev, effect=None, replicates=None,
                          target_power=None, center_points=0, include_center_term=True,
                          omitted_effects=0, alpha=.05, solve_center_points=False):
    """Plan power for a main effect in a Plackett–Burman design."""
    if solve_center_points:
        center_points = None
    if (type(corner_points) is not int or not 8 <= corner_points <= 48 or corner_points % 4
            or type(factors) is not int or not 2 <= factors < corner_points):
        raise ValueError("Choose 8 to 48 corner points in multiples of four and fewer factors than points.")
    if center_points is not None and (type(center_points) is not int or not 0 <= center_points <= 100_000):
        raise ValueError("Enter whole center points from 0 to 100,000.")
    if type(omitted_effects) is not int or not 0 <= omitted_effects < factors:
        raise ValueError("At least one main effect must remain in the model.")

    def dfs(r, c):
        corners = corner_points * r
        n = corners + c
        return 1, n - 1 - factors + omitted_effects - int(include_center_term and c > 0), corners / 4, n

    result = _design_power(dfs, effect=effect, replicates=replicates, target_power=target_power,
                           stdev=stdev, alpha=alpha, center_points=center_points)
    return dict(analysis="plackett_burman_power", factors=factors, corner_points=corner_points,
                include_center_term=include_center_term, omitted_effects=omitted_effects, **result)


def sample_size_tolerance_interval(
    coverage: float = 0.95,
    confidence: float = 0.95,
    margin_ratio: float = 1.25,
) -> Dict[str, Any]:
    """Sample Size for Normal Tolerance Intervals controlling two-sided k/k_inf precision."""
    if not (0.5 <= coverage < 1.0 and 0.5 <= confidence < 1.0):
        raise ValueError("Coverage and confidence must be between 0.50 and 1.00.")
    if margin_ratio <= 1.0:
        raise ValueError("Tolerance factor ratio (k / z_p) must exceed 1.0 (e.g., 1.15 or 1.25).")

    z_p = float(stats.norm.ppf((1.0 + coverage) / 2.0))
    # Approximate Howe-Guenther normal tolerance k(n, p, 1-alpha)
    def tol_k(n: int) -> float:
        df = n - 1
        chi_crit = float(stats.chi2.ppf(1.0 - confidence, df))
        return z_p * math.sqrt((1.0 + 1.0 / n) * df / max(chi_crit, 1e-12))

    n_req = 4
    while n_req < 50000 and tol_k(n_req) / z_p > margin_ratio:
        n_req += 1

    return {
        "analysis": "sample_size_tolerance_interval",
        "coverage": float(coverage),
        "confidence": float(confidence),
        "margin_ratio": float(margin_ratio),
        "asymptotic_z": z_p,
        "achieved_k": float(tol_k(n_req)),
        "sample_size": int(n_req),
    }


def tolerance_interval_planning(*, coverage=.95, confidence=.95, excess_probability=.05,
                                maximum_coverages=None, sample_sizes=None, interval_type="Two-sided"):
    """Solve tolerance-interval precision for normal and distribution-free methods."""
    from scipy.optimize import brentq

    if not all(0 < value < 1 for value in (coverage, confidence, excess_probability)):
        raise ValueError("Coverage, confidence, and excess probability must be between 0 and 1.")
    if not 0 < excess_probability < confidence:
        raise ValueError("Excess probability must be less than confidence.")
    if interval_type not in ("Two-sided", "Lower bound", "Upper bound"):
        raise ValueError("Choose two-sided, lower bound, or upper bound.")
    if (maximum_coverages is None) == (sample_sizes is None):
        raise ValueError("Enter maximum coverages or sample sizes.")
    limit = 100_000
    two_sided = interval_type == "Two-sided"
    nodes, weights = np.polynomial.hermite.hermgauss(32)
    weights = weights / math.sqrt(math.pi)

    def normal_parameters(n):
        if not two_sided:
            return stats.nct.ppf(confidence, n - 1, math.sqrt(n) * stats.norm.ppf(coverage))
        shifts = 2 * nodes ** 2 / n
        target_width_sq = stats.ncx2.ppf(coverage, 1, shifts)
        return brentq(
            lambda k: np.dot(weights, stats.chi2.sf((n - 1) * target_width_sq / k ** 2, n - 1)) - confidence,
            1e-10, math.sqrt(target_width_sq.max() * (n - 1) / stats.chi2.ppf(1 - confidence, n - 1)) * 2,
        )

    def normal_excess(n, factor, maximum):
        if maximum == 1:
            return 0.0
        if not two_sided:
            return stats.nct.cdf(factor, n - 1, math.sqrt(n) * stats.norm.ppf(maximum))
        width_sq = stats.ncx2.ppf(maximum, 1, 2 * nodes ** 2 / n)
        return np.dot(weights, stats.chi2.sf((n - 1) * width_sq / factor ** 2, n - 1))

    def spacing(n):
        # F(X_s)-F(X_r) has a beta distribution with shape parameters s-r and n+1-(s-r).
        required = stats.binom.ppf(confidence, n, coverage) + 1
        return np.minimum(required, n - int(two_sided))

    rows = []
    if maximum_coverages is not None:
        maximums = list(maximum_coverages)
        if not maximums or any(not coverage < value < 1 for value in maximums):
            raise ValueError("Maximum coverages must exceed minimum coverage and be below 1.")
        candidates = np.arange(2, limit + 1)
        distances = spacing(candidates)
        actual_confidences = stats.beta.sf(coverage, distances, candidates + 1 - distances)
        for maximum in maximums:
            errors = stats.beta.sf(maximum, distances, candidates + 1 - distances)
            qualified = np.flatnonzero(
                (actual_confidences >= confidence) & (errors <= excess_probability)
            )
            low, high = 2, limit
            while low < high:
                mid = (low + high) // 2
                if normal_excess(mid, normal_parameters(mid), maximum) <= excess_probability:
                    high = mid
                else:
                    low = mid + 1
            normal = low if normal_excess(low, normal_parameters(low), maximum) <= excess_probability else None
            index = qualified[0] if qualified.size else None
            rows.append(dict(input=float(maximum), normal=normal,
                             nonparametric=int(candidates[index]) if index is not None else None,
                             achieved_confidence=float(actual_confidences[index]) if index is not None else None,
                             achieved_error=float(errors[index]) if index is not None else None))
        mode = "sample_size"
    else:
        sizes = list(sample_sizes)
        if not sizes or any(type(n) is not int or not 2 <= n <= limit for n in sizes):
            raise ValueError("Sample sizes must be whole numbers from 2 to 100,000.")
        for n in sizes:
            factor = normal_parameters(n)
            maximum = brentq(lambda p: normal_excess(n, factor, p) - excess_probability, coverage, 1)
            distance = spacing(n)
            achieved = stats.beta.sf(coverage, distance, n + 1 - distance)
            nonparametric = stats.beta.isf(excess_probability, distance, n + 1 - distance)
            rows.append(dict(input=n, normal=float(maximum), nonparametric=float(nonparametric),
                             achieved_confidence=float(achieved), achieved_error=float(excess_probability)))
        mode = "maximum_coverage"
    return dict(analysis="tolerance_interval_planning", mode=mode, coverage=coverage,
                confidence=confidence, excess_probability=excess_probability,
                interval_type=interval_type, rows=rows)


def tolerance_planning_sections(result):
    solving_size = result["mode"] == "sample_size"

    def percent(value):
        return f"{value:.4%}" if value is not None else "—"

    def size(value):
        return value if value is not None else "Over 100,000"

    inputs = [
        ["Minimum population coverage", percent(result["coverage"])],
        ["Confidence level", percent(result["confidence"])],
        ["Excess coverage probability", percent(result["excess_probability"])],
        ["Interval", result["interval_type"]],
    ]
    format_result = size if solving_size else percent
    rows = [
        [percent(row["input"]) if solving_size else row["input"],
         format_result(row["normal"]), format_result(row["nonparametric"]),
         percent(row["achieved_confidence"]), percent(row["achieved_error"])]
        for row in result["rows"]
    ]
    return [
        ("Method", ["Setting", "Value"], inputs),
        ("Required Sample Sizes" if solving_size else "Maximum Population Coverage",
         ["Maximum coverage" if solving_size else "Sample size", "Normal", "Nonparametric",
          "Nonparametric confidence", "Nonparametric excess probability"], rows),
    ]


def estimation_planning_sections(result):
    method = [
        ["Parameter", result["parameter"]],
        ["Planning value", result["planning_value"]],
        ["Confidence", f"{result['confidence']:.2%}"],
        ["Interval", result["interval_type"]],
    ]
    if result["known_stdev"] is not None:
        method.append(["Population standard deviation", "Known" if result["known_stdev"] else "Estimated"])
    if result["exposure"] is not None:
        method.append(["Length of observation", result["exposure"]])
    keys = ("sample_size", "target_margin", "lower_margin", "upper_margin", "margin")
    return [
        ("Method", ["Setting", "Value"], method),
        ("Results", ["Sample size", "Target margin", "Lower margin", "Upper margin", "Margin of error"],
         [[row[key] if row[key] is not None else "—" for key in keys] for row in result["rows"]]),
    ]


def format_power_extended_report(result: Dict[str, Any]) -> str:
    planning_reports = {
        "estimation_planning": ("Sample Size for Estimation", estimation_planning_sections),
        "tolerance_interval_planning": ("Sample Size for Tolerance Intervals", tolerance_planning_sections),
    }
    if result.get("analysis") in planning_reports:
        title, sections = planning_reports[result["analysis"]]
        lines = [title]
        for heading, headers, rows in sections(result):
            lines.extend(["", heading, "\t".join(headers)])
            lines.extend("\t".join(map(str, row)) for row in rows)
        return "\n".join(lines)
    kind = result.get("analysis", "")
    lines = [f"Power and Sample Size: {kind.replace('_', ' ').title()}", "─" * 56]
    for k, v in result.items():
        if k == "analysis":
            continue
        lbl = k.replace("_", " ").title()
        if isinstance(v, float):
            lines.append(f"  {lbl:<24}: {v:.6g}")
        else:
            lines.append(f"  {lbl:<24}: {v}")
    return "\n".join(lines)
