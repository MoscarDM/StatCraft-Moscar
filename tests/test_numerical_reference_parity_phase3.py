"""External Numerical Reference Parity Suite (Phase 3) for StatCraft statistical/ML engines.

Verifies exact numerical parity against independent analytical/SciPy/NumPy oracles:
  1. Mixed Effects Model (REML) vs closed-form balanced RCBD ANOVA/REML & SciPy REML oracle
  2. Seasonal ARIMA (CLS & ML) vs independent SciPy/NumPy CLS & exact Gaussian ML oracles
  3. Nonnormal Capability (Weibull & Box-Cox) vs analytical Weibull quantiles & Box-Cox formulas
  4. Predictive ML (FastDecisionTree CART & Random Forest) vs analytical splits, MSE/R2, & importance
"""
import math
import unittest
import numpy as np
from scipy import optimize, signal, stats

from statcraft.arima import fit_arima
from statcraft.capability_nonnormal_engine import run_nonnormal_capability
from statcraft.mixed_reml import fit_mixed_reml
from statcraft.model import Column, Worksheet
from statcraft.predictive_ml import FastDecisionTree, _predict_forest, random_forest_fit


class MixedModelsRemlParityTests(unittest.TestCase):
    """Mixed Effects Model (REML) parity against closed-form RCBD & SciPy REML oracle."""

    def test_balanced_rcbd_reml_closed_form_and_scipy_oracle(self):
        # Balanced RCBD: a=3 fixed treatments, b=5 random blocks, n=15 observations
        treatments = ["T1", "T2", "T3"] * 5
        blocks = [f"B{b}" for b in range(1, 6) for _ in range(3)]
        # Designed so MS_Block > MS_Error > 0
        y_vals = [
            10.2, 13.1, 16.0,   # B1 (low)
            11.4, 14.6, 17.2,   # B2
            12.5, 15.1, 18.8,   # B3
            13.2, 16.4, 19.1,   # B4
            14.1, 17.0, 20.2,   # B5 (high)
        ]

        sheet = Worksheet(
            "RCBD_REML",
            [
                Column("y", values=y_vals),
                Column("Treatment", values=treatments, kind="text"),
                Column("Block", values=blocks, kind="text"),
            ],
        )

        res = fit_mixed_reml(sheet, response_index=0, fixed_indices=[1], random_indices=[2])

        # 1. Closed-form balanced RCBD ANOVA/REML estimators
        a, b = 3, 5
        n = a * b
        y = np.asarray(y_vals, dtype=float)
        y_mat = y.reshape(b, a)  # rows = blocks, cols = treatments
        grand_mean = float(np.mean(y))
        block_means = np.mean(y_mat, axis=1)
        treat_means = np.mean(y_mat, axis=0)

        ss_block = float(a * np.sum((block_means - grand_mean) ** 2))
        ss_treat = float(b * np.sum((treat_means - grand_mean) ** 2))
        ss_total = float(np.sum((y - grand_mean) ** 2))
        ss_error = ss_total - ss_block - ss_treat

        ms_block = ss_block / (b - 1)
        ms_error = ss_error / ((a - 1) * (b - 1))

        sigma_e2_ref = ms_error
        sigma_b2_ref = (ms_block - ms_error) / a
        self.assertGreater(sigma_b2_ref, 0.0)
        self.assertGreater(sigma_e2_ref, 0.0)

        # 2. Construct X, Z, V and verify GLS fixed effects, BLUPs, and REML log-likelihood
        # fit_mixed_reml sorts categorical levels: ["T1", "T2", "T3"], reference = "T1"
        X = np.zeros((n, a), dtype=float)
        X[:, 0] = 1.0
        for i, tr in enumerate(treatments):
            if tr == "T2":
                X[i, 1] = 1.0
            elif tr == "T3":
                X[i, 2] = 1.0

        Z = np.zeros((n, b), dtype=float)
        for i, blk in enumerate(blocks):
            Z[i, int(blk[1:]) - 1] = 1.0

        V = sigma_e2_ref * np.eye(n) + sigma_b2_ref * (Z @ Z.T)
        V_inv = np.linalg.inv(V)
        XtVinvX = X.T @ V_inv @ X
        cov_beta = np.linalg.inv(XtVinvX)
        beta_ref = cov_beta @ (X.T @ V_inv @ y)
        se_ref = np.sqrt(np.diag(cov_beta))

        resid_ref = y - X @ beta_ref
        blup_ref = sigma_b2_ref * (Z.T @ V_inv @ resid_ref)

        _, logdet_V = np.linalg.slogdet(V)
        _, logdet_X = np.linalg.slogdet(XtVinvX)
        p = X.shape[1]
        neg2_rell_ref = float(
            logdet_V + logdet_X + resid_ref @ V_inv @ resid_ref + (n - p) * math.log(2.0 * math.pi)
        )

        # Cross-check against independent SciPy REML optimization oracle
        def reml_obj(lv):
            se2, sb2 = np.exp(lv)
            Vm = se2 * np.eye(n) + sb2 * (Z @ Z.T)
            L = np.linalg.cholesky(Vm)
            ldV = 2.0 * float(np.sum(np.log(np.diag(L))))
            ViX = np.linalg.solve(L.T, np.linalg.solve(L, X))
            XtViX = X.T @ ViX
            Lx = np.linalg.cholesky(XtViX)
            ldX = 2.0 * float(np.sum(np.log(np.diag(Lx))))
            Viy = np.linalg.solve(L.T, np.linalg.solve(L, y))
            bh = np.linalg.solve(Lx.T, np.linalg.solve(Lx, X.T @ Viy))
            r = y - X @ bh
            Vir = np.linalg.solve(L.T, np.linalg.solve(L, r))
            return ldV + ldX + float(r @ Vir)

        opt = optimize.minimize(reml_obj, [0.0, 0.0], method="L-BFGS-B")
        self.assertTrue(opt.success)
        self.assertAlmostEqual(math.exp(opt.x[0]), sigma_e2_ref, places=4)
        self.assertAlmostEqual(math.exp(opt.x[1]), sigma_b2_ref, places=4)

        # Assertions on fit_mixed_reml output
        vc_map = {row["source"]: row for row in res["variance_components"]}
        self.assertAlmostEqual(vc_map["Block"]["var_comp"], sigma_b2_ref, places=4)
        self.assertAlmostEqual(vc_map["Error"]["var_comp"], sigma_e2_ref, places=4)
        self.assertAlmostEqual(res["total_variance"], sigma_b2_ref + sigma_e2_ref, places=4)

        self.assertEqual(len(res["fixed_effects"]), 3)
        for j, fe in enumerate(res["fixed_effects"]):
            self.assertAlmostEqual(fe["coef"], float(beta_ref[j]), places=4)
            self.assertAlmostEqual(fe["se_coef"], float(se_ref[j]), places=4)
            t_ref = float(beta_ref[j] / se_ref[j])
            p_ref = float(2.0 * (1.0 - stats.t.cdf(abs(t_ref), n - p)))
            self.assertAlmostEqual(fe["t_value"], t_ref, places=4)
            self.assertAlmostEqual(fe["p_value"], p_ref, places=5)

        blup_map = {row["level"]: row["blup"] for row in res["blups"]["Block"]}
        for b_idx in range(b):
            self.assertAlmostEqual(blup_map[f"B{b_idx + 1}"], float(blup_ref[b_idx]), places=4)

        self.assertAlmostEqual(res["neg2_rell"], neg2_rell_ref, places=4)
        self.assertAlmostEqual(res["aic"], neg2_rell_ref + 4.0, places=4)
        self.assertAlmostEqual(res["bic"], neg2_rell_ref + 2.0 * math.log(n - p), places=4)


class SeasonalArimaParityTests(unittest.TestCase):
    """Seasonal ARIMA (CLS & ML) parity against independent SciPy/NumPy oracles."""

    @staticmethod
    def _ar1_series(n: int = 45, phi: float = 0.65, c: float = 10.0) -> np.ndarray:
        rng = np.random.default_rng(2026)
        eps = rng.normal(0.0, 0.5, size=n)
        y = np.empty(n, dtype=float)
        y[0] = c + eps[0] / math.sqrt(1.0 - phi * phi)
        for t in range(1, n):
            y[t] = c + phi * (y[t - 1] - c) + eps[t]
        return y

    def test_ar1_cls_and_ml_parity(self):
        y = self._ar1_series()
        n = len(y)

        # --- CLS ---
        res_cls = fit_arima(y, p=1, d=0, q=0, include_constant=True, forecasts=3, method="CLS")

        def cls_obj(params):
            phi, c = params
            e = signal.lfilter([1.0, -phi], [1.0], y - c)
            return float(np.dot(e, e))

        opt_cls = optimize.minimize(cls_obj, [0.0, float(np.mean(y))], method="L-BFGS-B")
        self.assertTrue(opt_cls.success)
        phi_cls, c_cls = opt_cls.x
        e_cls = signal.lfilter([1.0, -phi_cls], [1.0], y - c_cls)
        ss_cls = float(np.dot(e_cls, e_cls))
        ms_cls = ss_cls / (n - 2)
        ll_cls = -0.5 * n * (math.log(2.0 * math.pi) + 1.0 + math.log(ss_cls / n))

        est_cls = {row["type"]: row["coef"] for row in res_cls["estimates"]}
        self.assertAlmostEqual(est_cls["AR  1"], float(phi_cls), places=5)
        self.assertAlmostEqual(est_cls["Constant"], float(c_cls), places=5)
        self.assertAlmostEqual(res_cls["ss"], ss_cls, places=5)
        self.assertAlmostEqual(res_cls["ms"], ms_cls, places=5)
        self.assertAlmostEqual(res_cls["log_likelihood"], ll_cls, places=5)

        # Multi-step AR(1) forecasts: y_{n+h} = c + phi^h * (y_n - c)
        for h, fc in enumerate(res_cls["forecasts"], start=1):
            fc_ref = float(c_cls + (phi_cls ** h) * (y[-1] - c_cls))
            self.assertAlmostEqual(fc["forecast"], fc_ref, places=5)

        # --- ML (exact Gaussian innovations likelihood for AR(1)) ---
        res_ml = fit_arima(y, p=1, d=0, q=0, include_constant=True, forecasts=3, method="ML")

        def ml_obj(params):
            phi, c = params
            if abs(phi) >= 0.999:
                return 1e100
            yc = y - c
            v = np.empty(n, dtype=float)
            f = np.ones(n, dtype=float)
            v[0] = yc[0]
            f[0] = 1.0 / (1.0 - phi * phi)
            v[1:] = yc[1:] - phi * yc[:-1]
            sigma2 = float(np.mean((v ** 2) / f))
            return float(n * math.log(sigma2) + np.sum(np.log(f)))

        opt_ml = optimize.minimize(ml_obj, [phi_cls, c_cls], method="L-BFGS-B")
        self.assertTrue(opt_ml.success)
        phi_ml, c_ml = opt_ml.x
        yc_ml = y - c_ml
        v_ml = np.empty(n, dtype=float)
        f_ml = np.ones(n, dtype=float)
        v_ml[0] = yc_ml[0]
        f_ml[0] = 1.0 / (1.0 - phi_ml * phi_ml)
        v_ml[1:] = yc_ml[1:] - phi_ml * yc_ml[:-1]
        ss_ml = float(np.sum((v_ml ** 2) / f_ml))
        sigma2_ml = ss_ml / n
        ll_ml = -0.5 * n * (math.log(2.0 * math.pi) + 1.0 + math.log(sigma2_ml)) - 0.5 * float(np.sum(np.log(f_ml)))

        est_ml = {row["type"]: row["coef"] for row in res_ml["estimates"]}
        self.assertAlmostEqual(est_ml["AR  1"], float(phi_ml), places=4)
        self.assertAlmostEqual(est_ml["Constant"], float(c_ml), places=4)
        self.assertAlmostEqual(res_ml["log_likelihood"], ll_ml, places=4)
        self.assertTrue(res_ml["stationary"])

    def test_seasonal_arima_110_110_4_cls_parity(self):
        # Quarterly series with linear trend + seasonal cycle + AR(1)/SAR(1) dynamics
        rng = np.random.default_rng(77)
        n_orig = 40
        seasonal = [2.0, -1.0, -3.0, 2.0]
        y = np.empty(n_orig, dtype=float)
        for t in range(n_orig):
            y[t] = 50.0 + 0.8 * t + seasonal[t % 4] + 0.3 * rng.normal()

        res = fit_arima(
            y,
            order=(1, 1, 0),
            seasonal_order=(1, 1, 0, 4),
            include_constant=False,
            forecasts=4,
            method="CLS",
        )

        # Independent differencing: d=1 then D=1, S=4
        w = np.diff(y, n=1)
        w = w[4:] - w[:-4]
        N = len(w)
        self.assertEqual(res["N"], N)

        def sarima_cls_obj(params):
            phi, Phi = params
            ar_poly = np.convolve([1.0, -phi], [1.0, 0.0, 0.0, 0.0, -Phi])
            e = signal.lfilter(ar_poly, [1.0], w)
            return float(np.dot(e, e))

        opt = optimize.minimize(sarima_cls_obj, [0.0, 0.0], method="L-BFGS-B")
        self.assertTrue(opt.success)
        phi_ref, Phi_ref = opt.x
        ar_ref = np.convolve([1.0, -phi_ref], [1.0, 0.0, 0.0, 0.0, -Phi_ref])
        e_ref = signal.lfilter(ar_ref, [1.0], w)
        ss_ref = float(np.dot(e_ref, e_ref))
        ms_ref = ss_ref / (N - 2)

        est = {row["type"]: row["coef"] for row in res["estimates"]}
        self.assertAlmostEqual(est["AR  1"], float(phi_ref), places=5)
        self.assertAlmostEqual(est["SAR 1"], float(Phi_ref), places=5)
        self.assertAlmostEqual(res["ss"], ss_ref, places=5)
        self.assertAlmostEqual(res["ms"], ms_ref, places=5)

        # Independent multi-step forecast & undifferencing
        w_ext = list(w)
        w_fc = []
        for _ in range(4):
            pred = -sum(ar_ref[lag] * w_ext[-lag] for lag in range(1, len(ar_ref)))
            w_fc.append(pred)
            w_ext.append(pred)

        # Invert D=1, S=4 then d=1
        d1_hist = list(np.diff(y, n=1))
        for val in w_fc:
            d1_hist.append(val + d1_hist[-4])
        y_hist = list(y)
        for val in d1_hist[-(4):]:
            y_hist.append(val + y_hist[-1])
        y_fc_ref = y_hist[-4:]

        # Forecast SEs via impulse response
        denom = np.convolve(ar_ref, [1.0, -1.0])
        denom = np.convolve(denom, [1.0, 0.0, 0.0, 0.0, -1.0])
        imp = np.array([1.0, 0.0, 0.0, 0.0])
        psi = signal.lfilter([1.0], denom, imp)
        se_ref = math.sqrt(ms_ref) * np.sqrt(np.cumsum(psi ** 2))

        self.assertEqual(len(res["forecasts"]), 4)
        for h, fc in enumerate(res["forecasts"]):
            self.assertAlmostEqual(fc["forecast"], float(y_fc_ref[h]), places=5)
            self.assertAlmostEqual(fc["se"], float(se_ref[h]), places=5)


class NonnormalCapabilityParityTests(unittest.TestCase):
    """Nonnormal Capability (Weibull & Box-Cox) parity against analytical percentiles."""

    SKEWED_DATA = [
        2.1, 2.5, 2.8, 3.1, 3.3, 3.6, 3.9, 4.2, 4.4, 4.7,
        5.0, 5.3, 5.7, 6.1, 6.5, 7.0, 7.6, 8.2, 8.9, 9.7,
        10.6, 11.8, 13.1, 14.8, 16.9, 19.5, 22.4,
    ]

    def test_weibull_capability_analytical_percentiles(self):
        lsl, usl = 1.0, 25.0
        res = run_nonnormal_capability(self.SKEWED_DATA, dist_or_transform="weibull", lsl=lsl, usl=usl)

        arr = np.asarray(self.SKEWED_DATA, dtype=float)
        shape_ref, _, scale_ref = stats.weibull_min.fit(arr, floc=0)

        # Analytical Weibull quantile: Q(p) = scale * (-ln(1 - p))^(1 / shape)
        def weibull_q(p):
            return float(scale_ref * ((-math.log(1.0 - p)) ** (1.0 / shape_ref)))

        q_low = weibull_q(0.00135)
        q_med = weibull_q(0.5)
        q_upp = weibull_q(0.99865)

        pp_ref = (usl - lsl) / (q_upp - q_low)
        ppu_ref = (usl - q_med) / (q_upp - q_med)
        ppl_ref = (q_med - lsl) / (q_med - q_low)
        ppk_ref = min(ppu_ref, ppl_ref)

        # Analytical Weibull CDF: F(x) = 1 - exp(-(x / scale)^shape)
        exp_below_ref = (1.0 - math.exp(-((lsl / scale_ref) ** shape_ref))) * 1e6
        exp_above_ref = math.exp(-((usl / scale_ref) ** shape_ref)) * 1e6

        params = res["fit_info"]["parameters"]
        self.assertAlmostEqual(params["shape"], float(shape_ref), places=6)
        self.assertAlmostEqual(params["scale"], float(scale_ref), places=6)
        self.assertAlmostEqual(res["p_lower"], q_low, places=6)
        self.assertAlmostEqual(res["p_median"], q_med, places=6)
        self.assertAlmostEqual(res["p_upper"], q_upp, places=6)
        self.assertAlmostEqual(res["indices"]["pp"], pp_ref, places=6)
        self.assertAlmostEqual(res["indices"]["ppu"], ppu_ref, places=6)
        self.assertAlmostEqual(res["indices"]["ppl"], ppl_ref, places=6)
        self.assertAlmostEqual(res["indices"]["ppk"], ppk_ref, places=6)
        self.assertAlmostEqual(res["expected_ppm"]["below"], exp_below_ref, places=4)
        self.assertAlmostEqual(res["expected_ppm"]["above"], exp_above_ref, places=4)

    def test_boxcox_capability_optimal_and_log_lambda(self):
        lsl, usl = 1.0, 25.0
        arr = np.asarray(self.SKEWED_DATA, dtype=float)

        # 1. Optimal Box-Cox lambda
        res_opt = run_nonnormal_capability(self.SKEWED_DATA, dist_or_transform="box_cox", lsl=lsl, usl=usl)
        trans_ref, lam_ref = stats.boxcox(arr)
        mu_ref = float(np.mean(trans_ref))
        sd_ref = float(np.std(trans_ref, ddof=1))
        lsl_t = (lsl ** lam_ref - 1.0) / lam_ref
        usl_t = (usl ** lam_ref - 1.0) / lam_ref

        pp_ref = (usl_t - lsl_t) / (6.0 * sd_ref)
        ppu_ref = (usl_t - mu_ref) / (3.0 * sd_ref)
        ppl_ref = (mu_ref - lsl_t) / (3.0 * sd_ref)
        ppk_ref = min(ppu_ref, ppl_ref)

        self.assertAlmostEqual(res_opt["fit_info"]["lambda"], float(lam_ref), places=6)
        self.assertAlmostEqual(res_opt["fit_info"]["mean_trans"], mu_ref, places=6)
        self.assertAlmostEqual(res_opt["fit_info"]["std_trans"], sd_ref, places=6)
        self.assertAlmostEqual(res_opt["indices"]["pp"], pp_ref, places=6)
        self.assertAlmostEqual(res_opt["indices"]["ppk"], ppk_ref, places=6)

        # 2. Explicit lambda = 0.0 (log transform)
        res_log = run_nonnormal_capability(
            self.SKEWED_DATA, dist_or_transform="box_cox", lsl=lsl, usl=usl, box_cox_lambda=0.0
        )
        log_arr = np.log(arr)
        mu_log = float(np.mean(log_arr))
        sd_log = float(np.std(log_arr, ddof=1))
        pp_log = (math.log(usl) - math.log(lsl)) / (6.0 * sd_log)
        ppk_log = min((math.log(usl) - mu_log) / (3.0 * sd_log), (mu_log - math.log(lsl)) / (3.0 * sd_log))

        self.assertAlmostEqual(res_log["fit_info"]["lambda"], 0.0, places=9)
        self.assertAlmostEqual(res_log["indices"]["pp"], pp_log, places=6)
        self.assertAlmostEqual(res_log["indices"]["ppk"], ppk_log, places=6)


class PredictiveMlParityTests(unittest.TestCase):
    """Predictive ML (CART & Random Forest) parity against analytical splits & metrics."""

    def test_cart_deterministic_step_function_splits_and_importance(self):
        # 16 rows: y = 10 + 8 * I(x1 > 0.5) + 2 * I(x2 > 0.5) + 0 * x3
        # Exact 2-level tree achieves zero SSE and R^2 = 1.0
        rows_x1 = [0.0, 0.2, 0.3, 0.4, 0.0, 0.1, 0.3, 0.4, 0.6, 0.7, 0.8, 1.0, 0.6, 0.8, 0.9, 1.0]
        rows_x2 = [0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9, 0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9]
        rows_x3 = [float(i) for i in range(16)]
        X = np.column_stack([rows_x1, rows_x2, rows_x3])
        y = np.array([10.0 + 8.0 * (x1 > 0.5) + 2.0 * (x2 > 0.5) for x1, x2 in zip(rows_x1, rows_x2)])

        tree = FastDecisionTree(task="regression", max_depth=4, min_samples_leaf=2)
        tree.fit(X, y)

        # Root must split on x1 at midpoint (0.4 + 0.6)/2 = 0.5
        self.assertFalse(tree.root.is_leaf)
        self.assertEqual(tree.root.feature, 0)
        self.assertAlmostEqual(tree.root.threshold, 0.5, places=9)

        # Both children must split on x2 at midpoint (0.4 + 0.6)/2 = 0.5
        self.assertEqual(tree.root.left.feature, 1)
        self.assertAlmostEqual(tree.root.left.threshold, 0.5, places=9)
        self.assertEqual(tree.root.right.feature, 1)
        self.assertAlmostEqual(tree.root.right.threshold, 0.5, places=9)

        preds = tree.predict(X)
        mse = float(np.mean((y - preds) ** 2))
        self.assertAlmostEqual(mse, 0.0, places=12)

        # Analytical SSE reduction: root split reduces SSE by 16 * (4.0)^2 = 256.0;
        # each child split reduces SSE by 8 * (1.0)^2 = 8.0 -> total x2 gain = 16.0; x3 = 0.0
        imp = tree.feature_importances_
        self.assertAlmostEqual(float(imp[0]), 256.0, places=9)
        self.assertAlmostEqual(float(imp[1]), 16.0, places=9)
        self.assertAlmostEqual(float(imp[2]), 0.0, places=12)

    def test_cart_deterministic_classification_split(self):
        X = np.array([
            [0.1, 5.0], [0.2, 4.0], [0.3, 3.0], [0.4, 2.0],
            [0.6, 2.0], [0.7, 3.0], [0.8, 4.0], [0.9, 5.0],
        ])
        y = np.array([0, 0, 0, 0, 1, 1, 1, 1], dtype=int)
        tree = FastDecisionTree(task="classification", max_depth=3, min_samples_leaf=2, n_classes=2)
        tree.fit(X, y)

        self.assertEqual(tree.root.feature, 0)
        self.assertAlmostEqual(tree.root.threshold, 0.5, places=9)
        probs = tree.predict(X)
        pred_cls = np.argmax(probs, axis=1)
        self.assertTrue(np.array_equal(pred_cls, y))

    def test_random_forest_regression_metrics_and_importance_ordering(self):
        rng = np.random.default_rng(101)
        n = 40
        x1 = np.concatenate([np.linspace(0.0, 0.4, n // 2), np.linspace(0.6, 1.0, n // 2)])
        x2 = np.tile(np.array([0.1, 0.2, 0.8, 0.9]), n // 4)
        x3 = rng.uniform(0.0, 1.0, size=n)
        y = 10.0 + 12.0 * (x1 > 0.5) + 4.0 * (x2 > 0.5) + 0.05 * x3

        sheet = Worksheet(
            "RF_Parity",
            [
                Column("y", values=y.tolist()),
                Column("x1", values=x1.tolist()),
                Column("x2", values=x2.tolist()),
                Column("x3", values=x3.tolist()),
            ],
        )

        res = random_forest_fit(
            sheet,
            response_index=0,
            predictor_indices=[1, 2, 3],
            task="regression",
            n_trees=40,
            max_depth=6,
            min_samples_leaf=2,
            max_features="all",
            seed=42,
        )

        # Verify train_metrics consistency against _predict_forest
        X_mat = res["_ds"]["X"]
        y_pred = _predict_forest(res, X_mat)
        resid = y - y_pred
        mse_ref = float(np.mean(resid * resid))
        rmse_ref = math.sqrt(mse_ref)
        r2_ref = 1.0 - float(np.sum(resid * resid)) / float(np.sum((y - np.mean(y)) ** 2))

        self.assertAlmostEqual(res["train_metrics"]["mse"], mse_ref, places=10)
        self.assertAlmostEqual(res["train_metrics"]["rmse"], rmse_ref, places=10)
        self.assertAlmostEqual(res["train_metrics"]["r2"], r2_ref, places=10)
        self.assertGreater(res["train_metrics"]["r2"], 0.98)
        self.assertGreater(res["oob_metrics"]["r2"], 0.90)

        # Feature importance ordering must strictly be x1 > x2 > x3
        imp_order = [row["predictor"] for row in res["variable_importance"]]
        self.assertEqual(imp_order, ["x1", "x2", "x3"])
        self.assertAlmostEqual(res["variable_importance"][0]["relative_importance"], 100.0, places=9)
        self.assertGreater(
            res["variable_importance"][1]["raw_importance"],
            res["variable_importance"][2]["raw_importance"],
        )


if __name__ == "__main__":
    unittest.main()
