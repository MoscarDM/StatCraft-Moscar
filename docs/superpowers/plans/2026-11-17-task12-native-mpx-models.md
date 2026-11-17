# Task 12: Remaining Native MPX Model Recovery (Reliability, ARIMA, Mixed Models)

**Goal:** Extend `statcraft/native_mpx_models.py` and `Presenter.refit_native_model` in `statcraft/app.py` to recover, resolve, refit, and compare native MPX models for Parametric Distribution / Reliability, ARIMA, and Mixed-Effects Models (REML), while preserving explicit `supported: False` diagnostics for unsupported options.

**Backend Targets:**
- **Reliability:** `Presenter.reliability_distribution(settings)` (`statcraft/reliability_engine.py`, `statcraft/reliability_inputs.py`) — MLE for `weibull`, `lognormal`, `normal`, `exponential` with optional right-censoring column (`censor_index`, `censor_value`).
- **ARIMA:** `Presenter.arima(settings)` (`statcraft/arima.py`) — `ARIMA(p, d, q) x (P, D, Q)_S`, `include_constant`, `method` (`CLS` or `ML`), `conf_level`.
- **Mixed-Effects Models:** `Presenter.fit_mixed_reml(response_index, fixed_indices, random_indices)` (`statcraft/mixed_reml.py`) — REML with additive fixed factors/covariates and ≥1 random factor (variance components).

---

## TDD Plan

### Step 1: Write Failing Tests (`tests/test_native_mpx_models_phase2.py`)
Create `tests/test_native_mpx_models_phase2.py` with fixtures and unit tests covering:
1. **Parametric Distribution / Reliability (`DistributionAnalysis`, `ParametricDistributionAnalysis`)**
   - Recovery of Weibull, Lognormal, Normal, Exponential MLE with and without right-censoring column (`censor_index`, `censor_value`).
   - Worksheet column reordering/renaming via `resolve_model_recipe` and `resolve_entry_recipe` (preserving `column_index` and `censor_index`).
   - End-to-end `Presenter.refit_native_model` + `compare_native_model` matching parameters, log-likelihood, and MTTF.
   - Explicit `supported: False` diagnostics for arbitrary/interval/left censoring, non-MLE estimation (rank regression / least squares), unsupported distributions (e.g. `gamma`, `3p_weibull`), weights/frequency columns, thresholds, and row subsets.
2. **ARIMA (`ARIMA`, `BoxJenkinsARIMA`)**
   - Recovery of nonseasonal `(p, d, q)` and seasonal `(p, d, q) x (P, D, Q)_S`, `include_constant`, `method` (`CLS` / `ML`), `conf_level`.
   - Column reordering/renaming via `resolve_model_recipe` and `resolve_entry_recipe` (`series_index`).
   - End-to-end `Presenter.refit_native_model` + `compare_native_model` matching parameter estimates, SEs, MS, and error DF.
   - Explicit `supported: False` diagnostics for exogenous predictors, Box-Cox/log transforms, weights, invalid seasonal orders (`S=1` with `D>0`), unsupported methods, and row subsets.
3. **Mixed-Effects Models (`MixedEffectsModel`, `MixedModel`)**
   - Recovery of REML model with fixed factor/covariate + random factor(s).
   - Column reordering/renaming via `resolve_model_recipe` and `resolve_entry_recipe` (`response_index`, `fixed_indices`, `random_indices`).
   - End-to-end `Presenter.refit_native_model` + `compare_native_model` matching fixed-effect coefficients/SEs and variance components (random factors + Error).
   - Explicit `supported: False` diagnostics for ML estimation (unsupported by REML-only backend), interactions/nested random effects, non-VC covariance structures, missing random factors, weights, transforms, and row subsets.

Verify tests fail before implementation.

### Step 2: Implement Recovery & Refit Support
1. **`statcraft/native_mpx_models.py`:**
   - Add family constants and update `_FAMILY_MAP`, `_MODEL_TYPE_MAP`, `_OBJ_TYPE_MAP`.
   - Add dedicated family decoders `_decode_reliability`, `_decode_arima`, `_decode_mixed_reml` dispatched from `_decode` after common project/command/worksheet/model-ID validation (avoiding forced OLS-specific `termlist`/`constant` checks for Reliability/ARIMA).
   - Extend `compare_native_model` for `reliability_distribution`, `arima`, and `mixed_reml`.
   - Extend `resolve_model_recipe` and `resolve_entry_recipe` for `reliability_distribution`, `arima`, and `fit_mixed_reml`.
2. **`statcraft/app.py`:**
   - Extend `Presenter.refit_native_model` to dispatch `'reliability_distribution'`, `'arima'`, and `'fit_mixed_reml'`.

### Step 3: Verify
Run the targeted test suites:
- `tests.test_native_mpx_models_phase2`
- `tests.test_native_mpx_models`
- `tests.test_mpx_shared_blob_and_models`
