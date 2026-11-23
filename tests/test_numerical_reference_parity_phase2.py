"""External Numerical Reference Parity Suite (Phase 2) for StatCraft statistical engines.

Verifies exact numerical parity against independent analytical/MLE oracles:
  1. Binary Logistic Regression (MLE) vs scipy.optimize.minimize exact Bernoulli MLE
  2. Poisson Regression (MLE) vs scipy.optimize.minimize exact Poisson GLM MLE
  3. EWMA Control Chart vs exact recursive EWMA & time-varying control limits
  4. One-Way ANOVA + Tukey HSD vs exact analytical ANOVA & studentized_range oracle
"""
import math
import unittest
import numpy as np
from scipy import optimize, special, stats
from scipy.stats import studentized_range

from statcraft.logistic import fit as fit_binary_logistic
from statcraft.model import Column, Worksheet
from statcraft.oneway import fit as fit_oneway
from statcraft.poisson_regression import fit_poisson_regression
from statcraft.time_weighted_control_engine import run_ewma_control


class BinaryLogisticParityTests(unittest.TestCase):
    """Binary Logistic Regression MLE parity against independent Bernoulli MLE oracle."""

    def test_binary_logistic_two_predictors_mle_oracle(self):
        # Overlapping binary outcome dataset (24 observations, 2 continuous predictors)
        # Designed with clear interior overlap so finite MLE exists without separation.
        x1 = [
            -2.1, -1.8, -1.5, -1.2, -0.9, -0.7, -0.5, -0.3,
            -0.1,  0.1,  0.2,  0.4,  0.5,  0.7,  0.8,  1.0,
             1.2,  1.4,  1.6,  1.8,  2.0,  2.2, -0.4,  0.6,
        ]
        x2 = [
             1.2, -0.5,  0.8, -1.1,  0.3,  1.5, -0.8,  0.2,
             1.1, -1.3,  0.6, -0.4,  1.4, -0.9,  0.5, -1.2,
             0.9, -0.3,  1.3, -0.7,  0.4, -1.0, -0.2,  0.7,
        ]
        y = [
            0, 0, 0, 0, 0, 1, 0, 0,
            1, 0, 1, 0, 1, 0, 1, 0,
            1, 1, 1, 1, 1, 1, 1, 0,
        ]

        sheet = Worksheet(
            "BinaryLogisticParity",
            [
                Column("y", values=y),
                Column("x1", values=x1),
                Column("x2", values=x2),
            ],
        )

        res = fit_binary_logistic(
            sheet,
            response_index=0,
            continuous_indices=[1, 2],
            categorical_indices=[],
            event=1,
        )

        # Independent Bernoulli MLE oracle via scipy.optimize.minimize (BFGS)
        y_arr = np.asarray(y, dtype=float)
        X = np.column_stack([np.ones(len(y)), np.asarray(x1, dtype=float), np.asarray(x2, dtype=float)])

        def neg_loglik(beta):
            eta = X @ beta
            # log(1 + exp(eta)) = logaddexp(0, eta)
            return -float(np.sum(y_arr * eta - np.logaddexp(0.0, eta)))

        def grad_neg_loglik(beta):
            p = special.expit(X @ beta)
            return -X.T @ (y_arr - p)

        def hess_neg_loglik(beta):
            p = special.expit(X @ beta)
            w = p * (1.0 - p)
            return (X.T * w) @ X

        opt = optimize.minimize(
            neg_loglik,
            np.zeros(X.shape[1]),
            jac=grad_neg_loglik,
            hess=hess_neg_loglik,
            method="trust-ncg",
            options={"gtol": 1e-10, "maxiter": 200},
        )
        self.assertTrue(opt.success, f"Oracle optimization failed: {opt.message}")
        self.assertLess(float(np.max(np.abs(grad_neg_loglik(opt.x)))), 1e-8)

        beta_ref = opt.x
        p_ref = special.expit(X @ beta_ref)
        w_ref = p_ref * (1.0 - p_ref)
        cov_ref = np.linalg.inv((X.T * w_ref) @ X)
        se_ref = np.sqrt(np.diag(cov_ref))
        ll_ref = -float(opt.fun)
        deviance_ref = -2.0 * ll_ref  # ungrouped binary saturated loglik = 0

        self.assertEqual(len(res["coefficients"]), 3)
        for j, coef in enumerate(res["coefficients"]):
            self.assertAlmostEqual(coef["estimate"], float(beta_ref[j]), places=5)
            self.assertAlmostEqual(coef["standard_error"], float(se_ref[j]), places=5)

        self.assertAlmostEqual(res["log_likelihood"], ll_ref, places=6)
        self.assertAlmostEqual(res["deviance"], deviance_ref, places=6)


class PoissonRegressionParityTests(unittest.TestCase):
    """Poisson Regression MLE parity against independent Poisson GLM MLE oracle."""

    def test_poisson_regression_two_predictors_mle_oracle(self):
        # Count dataset (20 observations, 2 continuous predictors)
        x1 = [
            0.2, 0.5, 0.8, 1.0, 1.2, 1.5, 1.7, 2.0, 2.2, 2.5,
            0.3, 0.7, 1.1, 1.4, 1.8, 2.1, 2.4, 2.7, 2.9, 3.1,
        ]
        x2 = [
            1.0, 0.4, 1.2, 0.2, 0.9, 0.5, 1.4, 0.3, 1.1, 0.6,
            0.1, 1.3, 0.4, 1.0, 0.2, 1.2, 0.5, 0.8, 0.3, 1.1,
        ]
        y = [
            2, 2, 4, 3, 5, 6, 9, 8, 12, 14,
            1, 4, 4, 7, 7, 12, 13, 18, 19, 27,
        ]

        res = fit_poisson_regression(
            response=y,
            continuous_predictors=[x1, x2],
            continuous_names=["x1", "x2"],
            response_name="counts",
        )

        # Independent Poisson GLM MLE oracle via scipy.optimize.minimize (BFGS)
        y_arr = np.asarray(y, dtype=float)
        X = np.column_stack([np.ones(len(y)), np.asarray(x1, dtype=float), np.asarray(x2, dtype=float)])
        log_fact_y = special.gammaln(y_arr + 1.0)

        def neg_loglik(beta):
            eta = X @ beta
            mu = np.exp(eta)
            return -float(np.sum(y_arr * eta - mu - log_fact_y))

        def grad_neg_loglik(beta):
            mu = np.exp(X @ beta)
            return -X.T @ (y_arr - mu)

        def hess_neg_loglik(beta):
            mu = np.exp(X @ beta)
            return (X.T * mu) @ X

        opt = optimize.minimize(
            neg_loglik,
            np.array([math.log(float(np.mean(y_arr))), 0.0, 0.0]),
            jac=grad_neg_loglik,
            hess=hess_neg_loglik,
            method="trust-ncg",
            options={"gtol": 1e-8, "maxiter": 200},
        )
        self.assertTrue(opt.success, f"Oracle optimization failed: {opt.message}")
        self.assertLess(float(np.max(np.abs(grad_neg_loglik(opt.x)))), 1e-7)

        beta_ref = opt.x
        mu_ref = np.exp(X @ beta_ref)
        cov_ref = np.linalg.inv((X.T * mu_ref) @ X)
        se_ref = np.sqrt(np.diag(cov_ref))
        ll_ref = -float(opt.fun)
        deviance_ref = float(
            2.0 * np.sum(np.where(y_arr > 0, y_arr * np.log(y_arr / mu_ref), 0.0) - (y_arr - mu_ref))
        )

        self.assertEqual(len(res["coefficients"]), 3)
        for j, coef in enumerate(res["coefficients"]):
            self.assertAlmostEqual(coef["coef"], float(beta_ref[j]), places=5)
            self.assertAlmostEqual(coef["se_coef"], float(se_ref[j]), places=5)

        self.assertAlmostEqual(res["log_likelihood"], ll_ref, places=6)
        self.assertAlmostEqual(res["deviance"], deviance_ref, places=6)


class EwmaControlParityTests(unittest.TestCase):
    """EWMA Control Chart parity against exact recursive & time-varying limit formulas."""

    def test_ewma_exact_points_and_time_varying_limits(self):
        # Reference sequence with known historical parameters:
        # lambda = 0.2, L = 3.0, mu0 = 10.0, sigma = 1.0
        data = [
            10.2, 9.8, 10.5, 10.1, 9.6, 10.4, 10.8, 9.9, 10.3, 10.7,
            11.0, 10.6, 11.2, 10.9, 11.4, 10.5, 10.1, 9.7, 10.0, 10.3,
        ]
        lam = 0.2
        L = 3.0
        mu0 = 10.0
        sigma = 1.0

        res = run_ewma_control(
            data=data,
            subgroup_size=1,
            weight=lam,
            options={
                "weight": lam,
                "k_sigma": L,
                "historical_mean": mu0,
                "historical_sigma": sigma,
            },
        )

        self.assertAlmostEqual(res["center_line"], mu0, places=6)
        self.assertAlmostEqual(res["sigma"], sigma, places=6)
        self.assertEqual(len(res["values"]), len(data))

        z_prev = mu0
        for idx, x_i in enumerate(data, start=1):
            z_ref = lam * x_i + (1.0 - lam) * z_prev
            z_prev = z_ref
            sd_ref = sigma * math.sqrt((lam / (2.0 - lam)) * (1.0 - (1.0 - lam) ** (2 * idx)))
            ucl_ref = mu0 + L * sd_ref
            lcl_ref = mu0 - L * sd_ref

            self.assertAlmostEqual(res["values"][idx - 1], z_ref, places=6)
            self.assertAlmostEqual(res["se"][idx - 1], sd_ref, places=6)
            self.assertAlmostEqual(res["ucl"][idx - 1], ucl_ref, places=6)
            self.assertAlmostEqual(res["lcl"][idx - 1], lcl_ref, places=6)


class OneWayAnovaTukeyParityTests(unittest.TestCase):
    """One-Way ANOVA + Tukey HSD parity against balanced 3-group Montgomery reference."""

    def test_balanced_three_group_anova_and_tukey_hsd(self):
        # Balanced 3-group dataset (Montgomery, Design and Analysis of Experiments,
        # Cotton Weight% / Tensile Strength style: 3 levels x 5 replicates = 15 obs)
        groups = {
            "15%": [7, 7, 15, 11, 9],
            "20%": [12, 17, 12, 18, 18],
            "25%": [14, 18, 18, 19, 19],
        }
        levels = list(groups.keys())
        resp_vals, factor_vals = [], []
        for lv in levels:
            for v in groups[lv]:
                resp_vals.append(float(v))
                factor_vals.append(lv)

        sheet = Worksheet(
            "OneWayTukeyParity",
            [
                Column("Strength", values=resp_vals),
                Column("Cotton", "text", factor_vals),
            ],
        )

        res = fit_oneway(
            sheet,
            response_index=0,
            factor_index=1,
            options={
                "confidence": 0.95,
                "comparisons": {"tukey": True, "error_rate": 0.05},
            },
        )

        # Independent analytical One-Way ANOVA & Tukey HSD oracle
        arr = np.array([groups[lv] for lv in levels], dtype=float)  # (k=3, n=5)
        k, n = arr.shape
        N = k * n
        grand_mean = float(np.mean(arr))
        group_means = np.mean(arr, axis=1)

        ss_between_ref = float(n * np.sum((group_means - grand_mean) ** 2))
        ss_within_ref = float(np.sum((arr - group_means[:, None]) ** 2))
        df_between = k - 1
        df_within = N - k
        ms_between_ref = ss_between_ref / df_between
        ms_within_ref = ss_within_ref / df_within
        f_ref = ms_between_ref / ms_within_ref
        p_ref = float(stats.f.sf(f_ref, df_between, df_within))

        anova = res["anova_table"]
        self.assertEqual(anova["df_factor"], df_between)
        self.assertEqual(anova["df_error"], df_within)
        self.assertAlmostEqual(anova["ss_factor"], ss_between_ref, places=5)
        self.assertAlmostEqual(anova["ss_error"], ss_within_ref, places=5)
        self.assertAlmostEqual(anova["f_value"], f_ref, places=5)
        self.assertAlmostEqual(anova["p_value"], p_ref, places=5)

        # Tukey HSD simultaneous 95% confidence intervals
        s_pooled_ref = math.sqrt(ms_within_ref)
        se_diff_ref = s_pooled_ref * math.sqrt(2.0 / n)
        q_crit_ref = float(studentized_range.ppf(0.95, k, df_within))
        margin_ref = (q_crit_ref / math.sqrt(2.0)) * se_diff_ref

        tukey_tests = {
            (t["level_i"], t["level_j"]): t
            for t in res["comparisons"]["tukey"]["tests"]
        }
        self.assertEqual(len(tukey_tests), 3)

        for i in range(k):
            for j in range(i + 1, k):
                lv_i, lv_j = levels[i], levels[j]
                t_row = tukey_tests[(lv_i, lv_j)]
                diff_ref = float(group_means[i] - group_means[j])
                ci_low_ref = diff_ref - margin_ref
                ci_high_ref = diff_ref + margin_ref
                q_val_ref = abs(diff_ref) * math.sqrt(2.0) / se_diff_ref
                adj_p_ref = float(studentized_range.sf(q_val_ref, k, df_within))

                self.assertAlmostEqual(t_row["difference"], diff_ref, places=5)
                self.assertAlmostEqual(t_row["se_difference"], se_diff_ref, places=5)
                self.assertAlmostEqual(t_row["ci_low"], ci_low_ref, places=5)
                self.assertAlmostEqual(t_row["ci_high"], ci_high_ref, places=5)
                self.assertAlmostEqual(t_row["adjusted_p"], adj_p_ref, places=5)


if __name__ == "__main__":
    unittest.main()
