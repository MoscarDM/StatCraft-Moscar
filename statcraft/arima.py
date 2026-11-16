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
from scipy import linalg, optimize, signal, stats

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


def _normalize_method(method: Optional[str]) -> str:
    if not isinstance(method, str):
        raise ValueError("Estimation method must be 'CLS' or 'ML'.")
    norm = method.strip().upper()
    if norm not in ("CLS", "ML"):
        raise ValueError(f"Unsupported estimation method {method!r}; choose 'CLS' or 'ML'.")
    return norm


def _normalize_transform(
    transform: Optional[str],
    boxcox_lambda: Optional[float],
) -> Tuple[Optional[str], Optional[float]]:
    if transform is None:
        norm = None
    elif isinstance(transform, str):
        raw = transform.strip().lower()
        if raw in ("", "none"):
            norm = None
        elif raw == "log":
            norm = "log"
        elif raw in ("boxcox", "box-cox"):
            norm = "boxcox"
        else:
            raise ValueError(f"Unsupported transform {transform!r}; choose None, 'log', or 'boxcox'.")
    else:
        raise ValueError(f"Unsupported transform {transform!r}; choose None, 'log', or 'boxcox'.")

    lam: Optional[float] = None
    if boxcox_lambda is not None:
        if isinstance(boxcox_lambda, bool):
            raise ValueError("Box-Cox lambda must be a finite real number.")
        try:
            lam = float(boxcox_lambda)
        except (TypeError, ValueError):
            raise ValueError("Box-Cox lambda must be a finite real number.") from None
        if not math.isfinite(lam):
            raise ValueError("Box-Cox lambda must be a finite real number.")
    return norm, lam


def _apply_transform(
    y: np.ndarray,
    transform: Optional[str],
    boxcox_lambda: Optional[float],
) -> Tuple[np.ndarray, Optional[float]]:
    if transform is None:
        return y, None
    nonpos = np.where(y <= 0)[0]
    if len(nonpos) > 0:
        idx = int(nonpos[0])
        raise ValueError(
            f"ARIMA {transform} transform requires strictly positive observations "
            f"(found {y[idx]} at row {idx + 1})."
        )
    if transform == "log":
        return np.log(y), None
    if boxcox_lambda is None:
        if np.ptp(y) == 0:
            lam = 1.0
        else:
            _, lam_est = stats.boxcox(y)
            lam = float(lam_est)
    else:
        lam = float(boxcox_lambda)
    if abs(lam) < 1e-12:
        return np.log(y), lam
    return (np.power(y, lam) - 1.0) / lam, lam


def _invert_transform_quantile(z: float, transform: Optional[str], lam: Optional[float]) -> float:
    if transform is None:
        return float(z)
    if transform == "log" or (lam is not None and abs(lam) < 1e-12):
        return float(math.exp(z))
    assert lam is not None
    inner = max(lam * z + 1.0, 1e-12)
    return float(inner ** (1.0 / lam))


def _invert_transform_point(
    z: float,
    variance: float,
    transform: Optional[str],
    lam: Optional[float],
) -> float:
    if transform is None:
        return float(z)
    var = max(0.0, float(variance))
    if transform == "log" or (lam is not None and abs(lam) < 1e-12):
        return float(math.exp(z + 0.5 * var))
    assert lam is not None
    inner = max(lam * z + 1.0, 1e-12)
    adj = 1.0 + (var * (1.0 - lam)) / (2.0 * inner * inner)
    return float((inner ** (1.0 / lam)) * max(adj, 0.0))


def _kalman_arma_innovations(
    z: np.ndarray,
    ar: np.ndarray,
    ma: np.ndarray,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], bool]:
    """Compute exact one-step-ahead innovations v_t and scaled variances f_t via Kalman filter."""
    n = len(z)
    p_star = len(ar) - 1
    q_star = len(ma) - 1
    if p_star == 0 and q_star == 0:
        return np.copy(z), np.ones(n, dtype=float), True

    r = max(1, p_star, q_star + 1)
    T = np.zeros((r, r), dtype=float)
    if p_star > 0:
        T[:p_star, 0] = -ar[1:]
    if r > 1:
        T[:-1, 1:] = np.eye(r - 1)

    try:
        eigs = np.linalg.eigvals(T)
    except np.linalg.LinAlgError:
        return None, None, False
    if not np.all(np.isfinite(eigs)) or float(np.max(np.abs(eigs))) >= 1.0 - 1e-6:
        return None, None, False

    R = np.zeros(r, dtype=float)
    R[0] = 1.0
    if q_star > 0:
        R[1:q_star + 1] = ma[1:]
    Q_mat = np.outer(R, R)

    try:
        P = linalg.solve_discrete_lyapunov(T, Q_mat)
    except Exception:
        return None, None, False
    if not np.all(np.isfinite(P)):
        return None, None, False
    P = 0.5 * (P + P.T)

    a = np.zeros(r, dtype=float)
    v = np.empty(n, dtype=float)
    f = np.empty(n, dtype=float)
    for t in range(n):
        v_t = z[t] - a[0]
        f_t = max(float(P[0, 0]), 1e-12)
        v[t] = v_t
        f[t] = f_t
        K_t = (T @ P[:, 0]) / f_t
        a = T @ a + K_t * v_t
        P = T @ P @ T.T + Q_mat - f_t * np.outer(K_t, K_t)
        P = 0.5 * (P + P.T)
    return v, f, True


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
    method: str = "CLS",
    transform: Optional[str] = None,
    boxcox_lambda: Optional[float] = None,
    order: Optional[Tuple[int, int, int]] = None,
    seasonal_order: Optional[Tuple[int, int, int, int]] = None,
    forecast_steps: Optional[int] = None,
) -> Dict[str, Any]:
    """Fit ARIMA(p,d,q)x(P,D,Q)_s model to time series values."""
    if order is not None:
        p, d, q = order
    if seasonal_order is not None:
        P, D, Q, S = seasonal_order
    if forecast_steps is not None:
        forecasts = forecast_steps

    method_norm = _normalize_method(method)
    transform_norm, lam_arg = _normalize_transform(transform, boxcox_lambda)

    for name, order_val in (("p", p), ("d", d), ("q", q), ("P", P), ("D", D), ("Q", Q)):
        if type(order_val) is not int or order_val < 0:
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

    y_work, lam_used = _apply_transform(y, transform_norm, lam_arg)

    if include_constant is None:
        include_constant = (d == 0 and D == 0)

    # 1. Differencing
    w = difference_series(y_work, d=d, D=D, S=S)
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

    def compute_cls_residuals(params):
        ar_p, ma_p = polynomials(params)
        center = params[-1] if include_constant else 0.0
        with np.errstate(over="ignore", invalid="ignore"):
            return signal.lfilter(ar_p, ma_p, w - center)

    def cls_objective(params):
        with np.errstate(over="ignore", invalid="ignore"):
            residuals = compute_cls_residuals(params)
            ss_val = np.dot(residuals, residuals)
        return float(ss_val) if np.isfinite(ss_val) else 1e100

    def compute_ml_innovations(params):
        ar_p, ma_p = polynomials(params)
        center = params[-1] if include_constant else 0.0
        return _kalman_arma_innovations(w - center, ar_p, ma_p)

    def ml_objective(params):
        v, f, ok = compute_ml_innovations(params)
        if not ok or v is None or f is None:
            return 1e100
        sigma2 = float(np.mean((v ** 2) / f))
        if not np.isfinite(sigma2) or sigma2 <= 0:
            return 1e100
        obj = float(N * math.log(sigma2) + np.sum(np.log(f)))
        return obj if np.isfinite(obj) else 1e100

    x0 = np.zeros(num_params, dtype=float)
    if include_constant:
        x0[-1] = float(np.mean(w))
    converged = True
    if num_params:
        if method_norm == "CLS":
            optimum = optimize.minimize(cls_objective, x0, method="L-BFGS-B",
                                        options={"maxiter": max_iter})
            opt_params = optimum.x
            converged = bool(optimum.success)
        else:
            # Warm-start ML from CLS if stationary, else from x0
            cls_opt = optimize.minimize(cls_objective, x0, method="L-BFGS-B",
                                        options={"maxiter": max(15, max_iter // 2)})
            _, _, cls_ok = compute_ml_innovations(cls_opt.x)
            ml_x0 = cls_opt.x if cls_ok else x0
            optimum = optimize.minimize(ml_objective, ml_x0, method="L-BFGS-B",
                                        options={"maxiter": max_iter})
            opt_params = optimum.x
            converged = bool(optimum.success)
    else:
        opt_params = x0

    ar, ma = polynomials(opt_params)
    if method_norm == "ML":
        v_opt, f_opt, ok_opt = compute_ml_innovations(opt_params)
        if not ok_opt or v_opt is None or f_opt is None:
            opt_residuals = compute_cls_residuals(opt_params)
            e_opt = opt_residuals
            f_opt = np.ones(N, dtype=float)
        else:
            opt_residuals = v_opt
            e_opt = v_opt / np.sqrt(f_opt)
        ss = float(np.sum(e_opt ** 2))
        sigma2_ml = max(ss / N, 1e-12)
        log_likelihood = float(-0.5 * N * (math.log(2.0 * math.pi) + 1.0 + math.log(sigma2_ml)) - 0.5 * np.sum(np.log(f_opt)))
    else:
        opt_residuals = compute_cls_residuals(opt_params)
        e_opt = opt_residuals
        ss = float(np.sum(opt_residuals ** 2))
        sigma2_cls = max(ss / N, 1e-12)
        log_likelihood = float(-0.5 * N * (math.log(2.0 * math.pi) + 1.0 + math.log(sigma2_cls)))

    # Degrees of freedom and SS / MS
    df = max(1, N - num_params)
    ms = ss / df
    s_err = math.sqrt(ms)

    # Approximate covariance matrix from numerical Jacobian
    eps = 1e-5
    J = np.zeros((N, num_params), dtype=float)
    r0 = e_opt
    for j in range(num_params):
        step = np.zeros(num_params, dtype=float)
        step[j] = eps
        if method_norm == "ML":
            vj, fj, okj = compute_ml_innovations(opt_params + step)
            if okj and vj is not None and fj is not None:
                J[:, j] = (vj / np.sqrt(fj) - r0) / eps
            else:
                vj, fj, okj = compute_ml_innovations(opt_params - step)
                if okj and vj is not None and fj is not None:
                    J[:, j] = (r0 - vj / np.sqrt(fj)) / eps
        else:
            rj = compute_cls_residuals(opt_params + step)
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
    diff_loss = n_orig - N
    fitted_vals: List[Optional[float]] = [None] * diff_loss
    for t in range(N):
        z_fit = float(y_work[diff_loss + t] - opt_residuals[t])
        fitted_vals.append(_invert_transform_point(z_fit, ms, transform_norm, lam_used))

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

        # Forecast variance accumulates squared impulse responses on the working scale.
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

        # Invert differencing on working scale, then back-transform
        z_fc = undifference_forecasts(y_work, w_fc, d=d, D=D, S=S)

        for h, z_val in enumerate(z_fc):
            period_num = n_orig + (h + 1)
            se_h = float(standard_errors[h])
            z_low = z_val - z_crit * se_h
            z_upp = z_val + z_crit * se_h
            f_val = _invert_transform_point(z_val, se_h ** 2, transform_norm, lam_used)
            low = _invert_transform_quantile(z_low, transform_norm, lam_used)
            upp = _invert_transform_quantile(z_upp, transform_norm, lam_used)
            forecast_list.append({
                "period": period_num,
                "forecast": f_val,
                "lower": low,
                "upper": upp,
                "se": se_h,
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
        "method": method_norm,
        "transform": transform_norm,
        "boxcox_lambda": lam_used,
        "include_constant": include_constant,
        "n_orig": n_orig,
        "N": N,
        "ss": float(ss),
        "log_likelihood": log_likelihood,
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
