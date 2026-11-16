"""Standalone Minitab-style Box-Cox Power Transformation for Quality Tools."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import stats

from .capability_nonnormal_engine import fit_box_cox_transformation
from .model import Column

_STANDARD_LAMBDAS = (-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0)


def _anderson_normal(arr: np.ndarray) -> tuple[float, float]:
    try:
        res = stats.anderson(arr, dist="norm", method="interpolate")
    except TypeError:
        res = stats.anderson(arr, dist="norm")
    ad = float(res.statistic)
    n = len(arr)
    ad_adj = ad * (1.0 + 0.75 / n + 2.25 / (n * n))
    if ad_adj >= 0.6:
        p = math.exp(1.2937 - 5.709 * ad_adj + 0.0186 * ad_adj * ad_adj)
    elif ad_adj >= 0.34:
        p = math.exp(0.9177 - 4.279 * ad_adj - 1.38 * ad_adj * ad_adj)
    elif ad_adj > 0.2:
        p = 1.0 - math.exp(-8.318 + 42.796 * ad_adj - 59.938 * ad_adj * ad_adj)
    else:
        p = 1.0 - math.exp(-13.436 + 101.14 * ad_adj - 223.73 * ad_adj * ad_adj)
    return ad, max(0.0001, min(0.9999, float(p)))


def _boxcox_transform_array(arr: np.ndarray, lam: float) -> np.ndarray:
    if abs(lam) < 1e-9:
        return np.log(arr)
    return (np.power(arr, lam) - 1.0) / lam


def run_box_cox_transformation(
    worksheet: Any,
    col_index: int,
    use_rounded_lambda: bool = True,
    custom_lambda: float | None = None,
    store_column: bool = True,
    store_name: str | None = None,
) -> dict[str, Any]:
    """Fit Box-Cox power transformation, compute AD normality before/after, and optionally store column."""
    if not (0 <= col_index < len(worksheet.columns)):
        raise ValueError("Choose a valid numeric column for Box-Cox transformation.")
    col = worksheet.columns[col_index]
    if col.kind != "number":
        raise ValueError(f"Column '{col.name}' must be numeric.")

    valid_idx = []
    valid_vals = []
    for i, v in enumerate(col.values):
        if v is None:
            continue
        fv = float(v)
        if math.isfinite(fv):
            valid_idx.append(i)
            valid_vals.append(fv)

    if len(valid_vals) < 3:
        raise ValueError("Box-Cox transformation requires at least 3 finite observations.")
    arr = np.asarray(valid_vals, dtype=float)
    if np.any(arr <= 0):
        raise ValueError("Box-Cox transformation requires all observations to be strictly positive (> 0).")

    fit = fit_box_cox_transformation(arr, user_lambda=custom_lambda)
    opt_lambda = float(fit["lambda"])

    # Compute 95% confidence interval for lambda via profile log-likelihood
    n = len(arr)
    lmb_grid = np.linspace(max(-5.0, opt_lambda - 2.5), min(5.0, opt_lambda + 2.5), 101)
    llf_vals = np.asarray([float(stats.boxcox_llf(float(l), arr)) for l in lmb_grid], dtype=float)
    max_llf = float(np.max(llf_vals))
    cutoff = max_llf - 0.5 * float(stats.chi2.ppf(0.95, 1))
    inside = lmb_grid[llf_vals >= cutoff]
    ci_low = float(inside[0]) if len(inside) else opt_lambda
    ci_high = float(inside[-1]) if len(inside) else opt_lambda

    chosen_lambda = opt_lambda
    if custom_lambda is None and use_rounded_lambda:
        in_ci = [s for s in _STANDARD_LAMBDAS if ci_low <= s <= ci_high]
        if in_ci:
            chosen_lambda = min(in_ci, key=lambda s: abs(s - opt_lambda))
        else:
            chosen_lambda = round(opt_lambda, 2)

    transformed = _boxcox_transform_array(arr, chosen_lambda)
    ad_orig, p_orig = _anderson_normal(arr)
    ad_trans, p_trans = _anderson_normal(transformed)

    stored_col_name = None
    if store_column:
        target_name = (store_name or "").strip() or f"BoxCox_{col.name}"
        full_vals: list[float | None] = [None] * len(col.values)
        for pos, tval in zip(valid_idx, transformed):
            full_vals[pos] = float(tval)
        existing = next((i for i, c in enumerate(worksheet.columns) if c.name == target_name), None)
        if existing is not None:
            worksheet.columns[existing].values = full_vals
            worksheet.columns[existing].kind = "number"
        else:
            worksheet.columns.append(Column(name=target_name, kind="number", values=full_vals))
        stored_col_name = target_name

    lines = [
        f"Box-Cox Transformation: {col.name}",
        f"Optimal Lambda (estimate): {opt_lambda:.4f} (95% CI: [{ci_low:.4f}, {ci_high:.4f}])",
        f"Applied Lambda: {chosen_lambda:.4f}",
        f"Original AD = {ad_orig:.4f} (p = {p_orig:.4f})",
        f"Transformed AD = {ad_trans:.4f} (p = {p_trans:.4f})",
    ]
    if stored_col_name:
        lines.append(f"Stored transformed data in column '{stored_col_name}'.")

    # Build summary table + Lambda profile graph
    table = {
        "title": "Box-Cox Transformation Summary",
        "headers": ["Metric", "Original", "Transformed"],
        "rows": [
            ["N", str(n), str(n)],
            ["Optimal Lambda", "—", f"{opt_lambda:.4f}"],
            ["95% CI for Lambda", "—", f"({ci_low:.4f}, {ci_high:.4f})"],
            ["Rounded / Applied Lambda", "—", f"{chosen_lambda:.4f}"],
            ["Anderson-Darling (AD)", f"{ad_orig:.4f}", f"{ad_trans:.4f}"],
            ["Normality P-Value", f"{p_orig:.4f}", f"{p_trans:.4f}"],
        ],
    }

    graphs = [
        {
            "title": f"Box-Cox Plot of {col.name} (Optimal λ = {opt_lambda:.3f}, Applied λ = {chosen_lambda:.3f})",
            "x_label": "Lambda",
            "y_label": "Profile Log-Likelihood",
            "series": [
                {
                    "name": "Log-Likelihood",
                    "x": [round(float(x), 4) for x in lmb_grid],
                    "y": [round(float(y), 4) for y in llf_vals],
                }
            ],
        }
    ]

    return {
        "analysis": "box_cox_transformation",
        "response_name": col.name,
        "optimal_lambda": opt_lambda,
        "applied_lambda": chosen_lambda,
        "ci_lambda": (ci_low, ci_high),
        "ad_original": ad_orig,
        "p_original": p_orig,
        "ad_transformed": ad_trans,
        "p_transformed": p_trans,
        "stored_column": stored_col_name,
        "text": "\n".join(lines),
        "tables": [table],
        "graphs": graphs,
    }
