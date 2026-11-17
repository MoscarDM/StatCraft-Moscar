# Task 13: External Numerical Reference Parity Phase 3 (Mixed Models, ARIMA, Nonnormal Capability, Predictive ML)

**Goal:** Verify exact numerical parity of four StatCraft statistical/ML engines against independent closed-form analytical and SciPy/NumPy optimization oracles in `tests/test_numerical_reference_parity_phase3.py`.

## Scope & Target Signatures

1. **Mixed Models (REML)** — `statcraft.mixed_reml.fit_mixed_reml(worksheet, response_index, fixed_indices, random_indices)`
   - **Fixture:** Balanced Randomized Complete Block Design (RCBD) with 3 fixed treatments (`a = 3`), 5 random blocks (`b = 5`, `n = 15`), and `MS_Block > MS_Error`.
   - **Oracle:** Closed-form ANOVA/REML variance components (`sigma_e^2 = MS_Error`, `sigma_block^2 = (MS_Block - MS_Error) / a`), GLS fixed-effect estimates and standard errors from `(X^T V^-1 X)^-1`, EBLUPs `sigma_block^2 * Z^T V^-1 (y - X beta)`, and `-2 * REML log-likelihood` (`neg2_rell`, `aic`, `bic`) verified against both closed-form formulas and an independent `scipy.optimize.minimize` REML log-likelihood oracle.

2. **Seasonal ARIMA (`CLS` & `ML`)** — `statcraft.arima.fit_arima(values, p, d, q, P, D, Q, S, include_constant, forecasts, method, ...)`
   - **Fixtures:**
     - Stationary AR(1) series (`p=1, d=0, q=0, include_constant=True`) tested with both `method="CLS"` and `method="ML"`.
     - Seasonal differenced ARIMA `(1, 1, 0) x (1, 1, 0)_4` (`method="CLS"`, `forecasts=4`).
   - **Oracle:** Independent SciPy/NumPy optimization oracle minimizing conditional sum of squares (CLS via `scipy.signal.lfilter`) and exact Gaussian innovations likelihood (ML via Kalman state-space recursion), verifying parameter estimates (`estimates[*]["coef"]`), residual variance (`ms`), `log_likelihood`, and multi-step `forecasts[*]["forecast"]` / `forecasts[*]["se"]`.

3. **Nonnormal Capability (Box-Cox & Weibull)** — `statcraft.capability_nonnormal_engine.run_nonnormal_capability(values, dist_or_transform, lsl, usl, ...)`
   - **Fixtures:**
     - Right-skewed positive dataset fitted with `dist_or_transform="weibull"`.
     - Same skewed positive dataset fitted with `dist_or_transform="box_cox"` (estimated optimal `lambda` and explicit `box_cox_lambda=0.0` log transform).
   - **Oracle:** Independent `scipy.stats.weibull_min.fit(..., floc=0)` and `scipy.stats.boxcox` / normal percentile formulas (`X_0.135%`, `X_50%`, `X_99.865%` for Weibull; `mu +/- 3*sigma` in transformed space for Box-Cox), verifying `fit_info`, `p_lower`, `p_median`, `p_upper`, `indices["pp"]`, `indices["ppk"]`, `indices["ppl"]`, `indices["ppu"]`, and `expected_ppm`.

4. **Predictive ML (CART / Random Forest)** — `statcraft.predictive_ml.FastDecisionTree` & `random_forest_fit(worksheet, response_index, predictor_indices, ...)`
   - **Fixtures:**
     - Deterministic step-function regression dataset where `x1` splits cleanly at `0.5` and `x2` splits at `0.5` (zero within-leaf variance after 2 levels), plus an irrelevant noise feature `x3`.
     - Deterministic 2-class classification dataset for `FastDecisionTree`.
   - **Oracle:** Exact analytical CART split thresholds, SSE/Gini gain, exact leaf predictions (`MSE = 0`, `R^2 = 1.0`), and `random_forest_fit` regression/OOB metrics (`r2`, `mse`, `rmse`) and `variable_importance` ordering (`x1 > x2 > x3`).

## Execution Steps

1. Create `tests/test_numerical_reference_parity_phase3.py` with the four parity test classes.
2. Run the targeted test suite (`test_numerical_reference_parity_phase3`, `test_numerical_reference_parity_phase2`, `test_numerical_reference_parity`).
3. If any genuine numerical bug is uncovered in the engines, fix it minimally and re-verify; otherwise keep engine files untouched.
