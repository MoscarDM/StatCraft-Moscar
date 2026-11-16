"""Computational engine for Box-Jenkins ARIMA (Autoregressive Integrated Moving Average) modeling.

Supported modeling operations (numerical equivalence with Minitab is unverified):
- ARIMA(p, d, q) x (P, D, Q)_s models.
- Nonseasonal and seasonal differencing: (1 - B)^d (1 - B^S)^D.
- Optional constant term estimation.
- Conditional least squares (CLS) parameter estimation with analytical/numerical Jacobians.
- Coefficient standard errors, t-statistics, and p-values.
- Residual Sum of Squares (SS), Mean Squared Error (MS), and Degrees of Freedom.
- Recursive multi-step forecasts with standard errors and confidence intervals.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np
from scipy import stats, optimize, signal

def _arima_observations(values):
    """Preserve time positions: missing values must never close up the series."""
    observations = []
    for row, value in enumerate(values, 1):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            number = float('nan')
        if not math.isfinite(number):
            raise ValueError(
                f"ARIMA requires a finite numeric observation at row {row}; "
                "resolve missing or invalid values before fitting the series."
            )
        observations.append(number)
    return np.asarray(observations, dtype=float)


def difference_series(
    y: np.ndarray,
    d: int = 0,
    D: int = 0,
    S: int = 1,
) -> np.ndarray:
    """Apply nonseasonal differencing (1 - B)^d and seasonal differencing (1 - B^S)^D."""
    w = np.copy(y)
    for _ in range(d):
        w = w[1:] - w[:-1]
    for _ in range(D):
        if len(w) <= S:
            raise ValueError(f"Series too short for seasonal differencing with period {S}.")
        w = w[S:] - w[:-S]
    return w


def undifference_forecasts(
    y_history: np.ndarray,
    diff_forecasts: Sequence[float],
    d: int = 0,
    D: int = 0,
    S: int = 1,
) -> List[float]:
    """Invert seasonal and nonseasonal differencing to convert differenced forecasts back to levels."""
    fc = list(diff_forecasts)
    if not fc:
        return []
    if d == 0 and D == 0:
        return fc

    # W_t = delta(B) Y_t. Solve for each new Y_t using the complete
    # differencing polynomial, including overlapping seasonal lags.
    delta = np.array([1.0])
    for _ in range(d):
        delta = np.convolve(delta, [1.0, -1.0])
    if D:
        seasonal = np.zeros(S + 1)
        seasonal[0], seasonal[-1] = 1.0, -1.0
        for _ in range(D):
            delta = np.convolve(delta, seasonal)
    if len(y_history) < len(delta) - 1:
        raise ValueError("Insufficient history to invert the requested differencing orders.")
    full = list(y_history)
    for value in fc:
        restored = value - math.fsum(
            coefficient * full[-lag]
            for lag, coefficient in enumerate(delta[1:], 1)
        )
        full.append(float(restored))
    return full[-len(fc):]


def fit_arima(
    values: Any,
    p: int = 1,
    d: int = 0,
    q: int = 0,
    P: int = 0,
    D: int = 0,
    Q: int = 0,
    S: int = 1,
    include_constant: Optional[bool] = None,
    forecasts: int = 0,
    conf_level: float = 95.0,
    max_iter: int = 50,
    variable_name: str = "Series",
    title: str = "",
) -> Dict[str, Any]:
    """Fit ARIMA(p,d,q)x(P,D,Q)_s model to time series values."""
    for name, order in (("p", p), ("d", d), ("q", q), ("P", P), ("D", D), ("Q", Q)):
        if type(order) is not int or order < 0:
            raise ValueError(f"ARIMA order {name} must be a nonnegative integer.")
    if type(S) is not int or S < 1 or (S == 1 and (P or D or Q)):
        raise ValueError("Seasonal models require an integer period of at least 2.")
    if type(forecasts) is not int or forecasts < 0:
        raise ValueError("Number of forecasts must be a nonnegative integer.")
    if type(max_iter) is not int or max_iter < 1:
        raise ValueError("Maximum iterations must be a positive integer.")
    try:
        conf_level = float(conf_level)
    except (TypeError, ValueError):
        raise ValueError("Confidence level must be between 0 and 100 percent.") from None
    if not 0 < conf_level < 100:
        raise ValueError("Confidence level must be between 0 and 100 percent.")
    y = _arima_observations(values)
    n_orig = len(y)
    if n_orig < (p + q + P + Q + d + D * S + 5):
        raise ValueError(f"Series too short for requested ARIMA specification (length {n_orig}).")

    if include_constant is None:
        include_constant = (d == 0 and D == 0)

    # 1. Differencing
    w = difference_series(y, d=d, D=D, S=S)
    N = len(w)

    param_names = []
    for i in range(1, p + 1):
        param_names.append(f"AR  {i}")
    for j in range(1, q + 1):
        param_names.append(f"MA  {j}")
    for i in range(1, P + 1):
        param_names.append(f"SAR {i}")
    for j in range(1, Q + 1):
        param_names.append(f"SMA {j}")
    if include_constant:
        param_names.append("Constant")

    num_params = len(param_names)

    def polynomials(params):
        phi = params[:p]
        theta = params[p:p + q]
        seasonal_ar = np.zeros(P * S + 1)
        seasonal_ma = np.zeros(Q * S + 1)
        seasonal_ar[0] = seasonal_ma[0] = 1
        if P:
            seasonal_ar[S::S] = -params[p + q:p + q + P]
        if Q:
            seasonal_ma[S::S] = -params[p + q + P:p + q + P + Q]
        ar = np.convolve(np.r_[1, -phi], seasonal_ar)
        ma = np.convolve(np.r_[1, -theta], seasonal_ma)
        return ar, ma

    def compute_residuals(params):
        ar, ma = polynomials(params)
        center = params[-1] if include_constant else 0.0
        with np.errstate(over="ignore", invalid="ignore"):
            return signal.lfilter(ar, ma, w - center)

    def objective(params):
        with np.errstate(over="ignore", invalid="ignore"):
            residuals = compute_residuals(params)
            ss = np.dot(residuals, residuals)
        return float(ss) if np.isfinite(ss) else 1e100

    x0 = np.zeros(num_params, dtype=float)
    if include_constant:
        x0[-1] = float(np.mean(w))
    converged = True
    if num_params:
        optimum = optimize.minimize(objective, x0, method="L-BFGS-B",
                                    options={"maxiter": max_iter})
        opt_params = optimum.x
        converged = bool(optimum.success)
    else:
        opt_params = x0
    opt_residuals = compute_residuals(opt_params)
    ar, ma = polynomials(opt_params)

    # Degrees of freedom and SS / MS
    ss = float(np.sum(opt_residuals ** 2))
    df = max(1, N - num_params)
    ms = ss / df
    s_err = math.sqrt(ms)

    # Approximate covariance matrix from numerical Jacobian
    eps = 1e-5
    J = np.zeros((N, num_params), dtype=float)
    r0 = opt_residuals
    for j in range(num_params):
        step = np.zeros(num_params, dtype=float)
        step[j] = eps
        rj = compute_residuals(opt_params + step)
        J[:, j] = (rj - r0) / eps

    try:
        jt_j = J.T @ J
        cov = np.linalg.inv(jt_j) * ms
        se_params = np.sqrt(np.maximum(1e-12, np.diag(cov)))
    except np.linalg.LinAlgError:
        se_params = np.full(num_params, s_err / math.sqrt(N))

    estimates = []
    for name, coef, se in zip(param_names, opt_params, se_params):
        t_stat = coef / se if se > 0 else 0.0
        p_val = float(2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=df)))
        estimates.append({
            "type": name,
            "coef": float(coef),
            "se": float(se),
            "t": float(t_stat),
            "p": float(p_val),
        })

    # Within-sample fitted values on original scale
    # Fit on differenced series: w - residuals
    w_fit = w - opt_residuals
    # Align fitted values to original series length
    diff_loss = n_orig - N
    fitted_vals = [None] * diff_loss
    for t in range(N):
        # Y_t = fitted
        fitted_vals.append(float(y[diff_loss + t] - opt_residuals[t]))

    # Out-of-sample Forecasts
    forecast_list = []
    if forecasts > 0:
        alpha_signif = 1.0 - (conf_level / 100.0)
        z_crit = float(stats.norm.ppf(1.0 - alpha_signif / 2.0))

        const = opt_params[-1] if include_constant else 0.0
        w_ext = list(w)
        a_ext = list(opt_residuals)
        w_fc = []
        for _ in range(forecasts):
            pred_w = const
            pred_w -= sum(coef * (w_ext[-lag] - const)
                          for lag, coef in enumerate(ar[1:], 1) if lag <= len(w_ext))
            pred_w += sum(coef * a_ext[-lag]
                          for lag, coef in enumerate(ma[1:], 1) if lag <= len(a_ext))
            w_fc.append(pred_w)
            w_ext.append(pred_w)
            a_ext.append(0.0)

        # Forecast variance accumulates squared impulse responses on the original scale.
        denominator = ar
        for _ in range(d):
            denominator = np.convolve(denominator, [1, -1])
        if D:
            seasonal_difference = np.zeros(S + 1)
            seasonal_difference[0], seasonal_difference[-1] = 1, -1
            for _ in range(D):
                denominator = np.convolve(denominator, seasonal_difference)
        impulse = np.zeros(forecasts)
        impulse[0] = 1
        responses = signal.lfilter(ma, denominator, impulse)
        standard_errors = s_err * np.sqrt(np.cumsum(responses ** 2))

        # Invert differencing
        y_fc = undifference_forecasts(y, w_fc, d=d, D=D, S=S)

        for h, f_val in enumerate(y_fc):
            period_num = n_orig + (h + 1)
            se_h = standard_errors[h]
            low = float(f_val - z_crit * se_h)
            upp = float(f_val + z_crit * se_h)
            forecast_list.append({
                "period": period_num,
                "forecast": float(f_val),
                "lower": low,
                "upper": upp,
                "se": float(se_h),
            })

    return {
        "analysis": "arima",
        "variable_name": variable_name,
        "title": title or f"ARIMA: {variable_name}",
        "p": p,
        "d": d,
        "q": q,
        "P": P,
        "D": D,
        "Q": Q,
        "S": S,
        "include_constant": include_constant,
        "n_orig": n_orig,
        "N": N,
        "ss": float(ss),
        "converged": converged,
        "stationary": bool(np.all(np.abs(np.roots(ar)) < 1)),
        "invertible": bool(np.all(np.abs(np.roots(ma)) < 1)),
        "ms": float(ms),
        "df": df,
        "estimates": estimates,
        "actual": y.tolist(),
        "fitted": fitted_vals,
        "residuals": [None if v is None else float(y[i] - v) for i, v in enumerate(fitted_vals)],
        "forecasts": forecast_list,
        "conf_level": conf_level,
    }



def forecast_best_arima(values, *, d=0, D=0, S=1, max_p=2, max_q=2, max_P=0, max_Q=0,
                        include_constant=True, forecasts=5, conf_level=95.0, criterion="AICc",
                        variable_name="Series"):
    """Rank candidate models at fixed differencing orders using conditional likelihood."""
    from itertools import product
    from .time_series import autocorrelation, partial_autocorrelation

    maxima = (max_p, max_q, max_P, max_Q)
    if any(type(v) is not int or not 0 <= v <= 4 for v in maxima) or math.prod(v + 1 for v in maxima) > 150:
        raise ValueError("Choose orders from 0 to 4 and at most 150 candidate combinations.")
    if (criterion not in ("AICc", "AIC", "BIC") or type(d) is not int or not 0 <= d <= 2
            or type(D) is not int or not 0 <= D <= 1 or type(S) is not int or not 1 <= S <= 365
            or type(forecasts) is not int or not 1 <= forecasts <= 150 or not 0 < conf_level < 100):
        raise ValueError("Choose valid differencing, season, forecast and criterion settings.")
    if S == 1 and (D or max_P or max_Q):
        raise ValueError("Seasonal models require a period of at least 2.")
    values = _arima_observations(values)
    if len(values) > 20_000:
        raise ValueError("Automatic ARIMA search supports up to 20,000 observations.")

    ranked = []
    failures = 0
    for p, q, P, Q in product(*(range(v + 1) for v in maxima)):
        if p == q == P == Q == 0 and (S > 1 or d != 1):
            continue
        settings = dict(p=p, q=q, P=P, Q=Q, d=d, D=D, S=S,
                        include_constant=bool(include_constant and d + D <= 1))
        for constant in ((True, False) if settings["include_constant"] else (False,)):
            settings["include_constant"] = constant
            try:
                model = fit_arima(values, **settings)
            except (ValueError, ArithmeticError, np.linalg.LinAlgError):
                continue
            if model["converged"] and model["stationary"] and model["invertible"] and model["ss"] > 0:
                break
        else:
            failures += 1
            continue
        n = model["N"]
        k = len(model["estimates"]) + 1
        if n <= k + 1:
            failures += 1
            continue
        log_likelihood = -.5 * n * (math.log(2 * math.pi) + 1 + math.log(model["ss"] / n))
        aic = -2 * log_likelihood + 2 * k
        ranked.append(dict(**settings, log_likelihood=log_likelihood, AIC=aic,
                           AICc=aic + 2 * k * (k + 1) / (n - k - 1),
                           BIC=-2 * log_likelihood + k * math.log(n)))

    if not ranked:
        raise ValueError("No candidate ARIMA model could be estimated.")
    ranked.sort(key=lambda row: row[criterion])
    selected = {key: ranked[0][key] for key in ("p", "q", "P", "Q", "d", "D", "S", "include_constant")}
    result = fit_arima(values, **selected, forecasts=forecasts, conf_level=conf_level,
                       variable_name=variable_name, title=f"Forecast with Best ARIMA Model: {variable_name}")
    residuals = [v for v in result["residuals"] if v is not None]
    acf = autocorrelation(residuals)["lags"]
    pacf = partial_autocorrelation(residuals)["lags"]
    model_df = sum(selected[key] for key in ("p", "q", "P", "Q"))
    diagnostics = []
    for a, b in zip(acf, pacf):
        lag = a["lag"]
        q_stat = a["lbq"]
        p_value = float(stats.chi2.sf(q_stat, lag - model_df)) if q_stat is not None and lag > model_df else None
        diagnostics.append(dict(lag=lag, acf=a["correlation"], pacf=b["pacf"], p_value=p_value))
    result.update(model_selection=ranked, criterion=criterion, candidate_failures=failures,
                  residual_diagnostics=diagnostics, likelihood_method="Conditional Gaussian likelihood")
    return result
