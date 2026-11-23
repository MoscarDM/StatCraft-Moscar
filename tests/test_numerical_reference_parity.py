"""External Numerical Reference Parity Suite for StatCraft statistical engines.

Verifies exact numerical parity against published external benchmarks and
independent analytical oracles:
  1. NIST StRD Norris (simple linear regression)
  2. NIST StRD Pontius (quadratic polynomial regression)
  3. Process Capability (Normal Cp, Cpk, Pp, Ppk, within/overall stdev)
  4. Crossed Gage R&R (balanced 3-operator x 10-part x 3-replicate ANOVA)
  5. Two-Way ANOVA / GLM (Montgomery Battery Life 3x3x4 balanced factorial)
  6. Weibull Reliability MLE (uncensored and right-censored beta, eta, B10, B50)
"""
import math
import unittest
import numpy as np
from scipy import optimize, special, stats

from statcraft.capability_engine import run_normal_capability
from statcraft.gage_rr import analyze as analyze_gage_rr
from statcraft.glm import fit as fit_glm
from statcraft.model import Column, Worksheet
from statcraft.regression import multiple_regression
from statcraft.reliability_engine import run_reliability_analysis


class NistRegressionParityTests(unittest.TestCase):
    """NIST StRD Linear Least Squares Regression certified benchmarks."""

    def test_nist_strd_norris_linear_regression(self):
        # NIST StRD Norris.dat (36 observations, calibration of ozone monitors)
        norris_rows = [
            (0.1, 0.2), (338.8, 337.4), (118.1, 118.2), (888.0, 884.6),
            (9.2, 10.1), (228.1, 226.5), (668.5, 666.3), (998.5, 996.3),
            (449.1, 448.6), (778.9, 777.0), (559.2, 558.2), (0.3, 0.4),
            (0.1, 0.6), (778.1, 775.5), (668.8, 666.9), (339.3, 338.0),
            (448.9, 447.5), (10.8, 11.6), (557.7, 556.0), (228.3, 228.1),
            (998.0, 995.8), (888.8, 887.6), (119.6, 120.2), (0.3, 0.3),
            (0.6, 0.3), (557.6, 556.8), (339.3, 339.1), (888.0, 887.2),
            (998.5, 999.0), (778.9, 779.0), (10.2, 11.1), (117.6, 118.3),
            (228.9, 229.2), (668.4, 669.1), (449.2, 448.9), (0.2, 0.5),
        ]
        y = [row[0] for row in norris_rows]
        x = [row[1] for row in norris_rows]

        res = multiple_regression([x], y, predictor_names=["x"], response_name="y")

        b0 = res["coefficients"][0]
        b1 = res["coefficients"][1]
        self.assertAlmostEqual(b0["estimate"], -0.262323073774029, places=10)
        self.assertAlmostEqual(b0["standard_error"], 0.232818234301152, places=10)
        self.assertAlmostEqual(b1["estimate"], 1.00211681802045, places=10)
        self.assertAlmostEqual(b1["standard_error"], 0.429796848199937e-3, places=10)
        self.assertAlmostEqual(res["residual_stdev"], 0.884796396144373, places=10)
        self.assertAlmostEqual(res["r_squared"], 0.999993745883712, places=10)
        self.assertEqual(res["df_regression"], 1)
        self.assertEqual(res["df_error"], 34)
        self.assertAlmostEqual(res["ss_regression"], 4255954.13232369, delta=1e-4)
        self.assertAlmostEqual(res["ss_error"], 26.6173985294224, places=8)
        self.assertAlmostEqual(res["f"], 5436385.54079785, delta=1e-4)

    def test_nist_strd_pontius_quadratic_regression(self):
        # NIST StRD Pontius.dat (40 observations, load cell calibration)
        pontius_rows = [
            (0.11019, 150000), (0.21956, 300000), (0.32949, 450000), (0.43899, 600000),
            (0.54803, 750000), (0.65694, 900000), (0.76562, 1050000), (0.87487, 1200000),
            (0.98292, 1350000), (1.09146, 1500000), (1.20001, 1650000), (1.30822, 1800000),
            (1.41599, 1950000), (1.52399, 2100000), (1.63194, 2250000), (1.73947, 2400000),
            (1.84646, 2550000), (1.95392, 2700000), (2.06128, 2850000), (2.16844, 3000000),
            (0.11052, 150000), (0.22018, 300000), (0.32939, 450000), (0.43886, 600000),
            (0.54798, 750000), (0.65739, 900000), (0.76596, 1050000), (0.87474, 1200000),
            (0.98300, 1350000), (1.09150, 1500000), (1.20004, 1650000), (1.30818, 1800000),
            (1.41613, 1950000), (1.52408, 2100000), (1.63159, 2250000), (1.73965, 2400000),
            (1.84696, 2550000), (1.95445, 2700000), (2.06177, 2850000), (2.16829, 3000000),
        ]
        y = [row[0] for row in pontius_rows]
        x = [float(row[1]) for row in pontius_rows]
        x2 = [xi * xi for xi in x]

        res = multiple_regression([x, x2], y, predictor_names=["x", "x2"], response_name="y")

        b0, b1, b2 = res["coefficients"]
        self.assertAlmostEqual(b0["estimate"], 0.673565789473684e-3, places=12)
        self.assertAlmostEqual(b0["standard_error"], 0.107938612033077e-3, places=12)
        self.assertAlmostEqual(b1["estimate"], 0.732059160401003e-6, places=14)
        self.assertAlmostEqual(b1["standard_error"], 0.157817399981659e-9, places=14)
        self.assertAlmostEqual(b2["estimate"], -0.316081871345029e-14, places=20)
        self.assertAlmostEqual(b2["standard_error"], 0.486652849992036e-16, places=20)
        self.assertAlmostEqual(res["residual_stdev"], 0.205177424076185e-3, places=12)
        self.assertAlmostEqual(res["r_squared"], 0.999999900178537, places=12)
        self.assertEqual(res["df_regression"], 2)
        self.assertEqual(res["df_error"], 37)
        self.assertAlmostEqual(res["ss_regression"], 15.6040343244198, places=8)
        self.assertAlmostEqual(res["ss_error"], 0.155761768796992e-5, places=12)
        self.assertAlmostEqual(res["f"], 185330865.995752, delta=1e-2)


class CapabilityParityTests(unittest.TestCase):
    """Normal Process Capability (Cp, Cpk, Pp, Ppk) reference parity."""

    def test_normal_capability_subgrouped_pooled_and_overall(self):
        # 10 subgroups of size 5 (50 observations), piston-ring style measurements
        subgroups = [
            [74.030, 74.002, 74.019, 73.992, 74.008],
            [73.995, 73.992, 74.001, 74.011, 74.004],
            [73.988, 74.024, 74.021, 74.005, 74.002],
            [74.002, 73.996, 73.993, 74.015, 74.009],
            [73.992, 74.007, 74.015, 73.989, 74.014],
            [74.009, 73.994, 73.997, 73.985, 73.993],
            [73.995, 74.006, 73.994, 74.000, 74.005],
            [73.985, 74.003, 73.993, 74.015, 73.988],
            [74.008, 73.995, 74.009, 74.005, 74.004],
            [73.998, 74.000, 73.990, 74.007, 73.995],
        ]
        flat = [v for g in subgroups for v in g]
        lsl, usl = 73.970, 74.030

        res = run_normal_capability(
            data=flat,
            subgroup_spec=5,
            lsl=lsl,
            usl=usl,
            estimate_method_gt1="pooled",
            unbiased_within=True,
            unbiased_overall=False,
        )

        # Independent analytical reference calculation
        arr = np.asarray(subgroups, dtype=float)
        mean_ref = float(np.mean(arr))
        sd_overall_ref = float(np.std(arr, ddof=1))
        df_within = 10 * (5 - 1)  # 40
        s_pooled = math.sqrt(float(np.mean(np.var(arr, axis=1, ddof=1))))
        # Exact c4(df + 1) = sqrt(2 / df) * Gamma((df + 1) / 2) / Gamma(df / 2)
        c4_41 = math.sqrt(2.0 / df_within) * math.exp(
            special.gammaln((df_within + 1) / 2.0) - special.gammaln(df_within / 2.0)
        )
        sd_within_ref = s_pooled / c4_41
        cp_ref = (usl - lsl) / (6.0 * sd_within_ref)
        cpk_ref = min((usl - mean_ref) / (3.0 * sd_within_ref), (mean_ref - lsl) / (3.0 * sd_within_ref))
        pp_ref = (usl - lsl) / (6.0 * sd_overall_ref)
        ppk_ref = min((usl - mean_ref) / (3.0 * sd_overall_ref), (mean_ref - lsl) / (3.0 * sd_overall_ref))

        self.assertEqual(res["sample_n"], 50)
        self.assertEqual(res["subgroup_count"], 10)
        self.assertAlmostEqual(res["mean"], mean_ref, places=10)
        self.assertAlmostEqual(res["stdev_within"], sd_within_ref, places=10)
        self.assertAlmostEqual(res["stdev_overall"], sd_overall_ref, places=10)
        self.assertAlmostEqual(res["cp"], cp_ref, places=8)
        self.assertAlmostEqual(res["cpk"], cpk_ref, places=8)
        self.assertAlmostEqual(res["pp"], pp_ref, places=8)
        self.assertAlmostEqual(res["ppk"], ppk_ref, places=8)


class GageRRParityTests(unittest.TestCase):
    """Crossed Gage R&R (balanced 3-operator x 10-part x 3-replicate ANOVA)."""

    def test_crossed_gage_rr_3x10x3_anova_and_study_var(self):
        # Balanced 3-operator x 10-part x 3-replicate reference dataset (90 runs)
        # Rows are parts 1..10, columns are operators A, B, C with 3 replicates each
        table = {
            1:  {"A": [0.29, 0.41, 0.64], "B": [0.08, 0.25, 0.07], "C": [0.04, -0.11, -0.15]},
            2:  {"A": [-0.56, -0.68, -0.58], "B": [-0.47, -1.22, -0.68], "C": [-1.38, -1.13, -0.96]},
            3:  {"A": [1.34, 1.17, 1.27], "B": [1.19, 0.94, 1.34], "C": [0.88, 1.09, 0.67]},
            4:  {"A": [0.47, 0.50, 0.64], "B": [0.01, 1.03, 0.20], "C": [0.14, 0.20, 0.11]},
            5:  {"A": [-0.80, -0.92, -0.84], "B": [-0.56, -1.20, -1.28], "C": [-1.46, -1.07, -1.45]},
            6:  {"A": [0.02, -0.11, -0.21], "B": [-0.20, 0.22, 0.06], "C": [-0.29, -0.67, -0.49]},
            7:  {"A": [0.59, 0.75, 0.66], "B": [0.47, 0.55, 0.83], "C": [0.02, 0.01, 0.21]},
            8:  {"A": [-0.31, -0.20, -0.17], "B": [-0.63, 0.08, -0.34], "C": [-0.46, -0.56, -0.49]},
            9:  {"A": [2.26, 1.99, 2.01], "B": [1.80, 2.12, 2.19], "C": [1.77, 1.45, 1.87]},
            10: {"A": [-1.36, -1.25, -1.31], "B": [-1.68, -1.62, -1.50], "C": [-1.49, -1.77, -2.16]},
        }
        parts, operators, measurements = [], [], []
        for p_id in range(1, 11):
            for op in ("A", "B", "C"):
                for val in table[p_id][op]:
                    parts.append(f"P{p_id}")
                    operators.append(op)
                    measurements.append(val)

        sheet = Worksheet(
            "GageRR_3x10x3",
            [
                Column("Measurement", values=measurements),
                Column("Part", "text", parts),
                Column("Operator", "text", operators),
            ],
        )

        # Keep full model (remove_interaction=False) to verify Operator*Part term
        res = analyze_gage_rr(sheet, 0, 1, 2, {"remove_interaction": False})

        # Independent balanced 2-way random-effects ANOVA oracle
        arr = np.array([[table[p][op] for op in ("A", "B", "C")] for p in range(1, 11)], dtype=float)
        p_cnt, q_cnt, r_cnt = arr.shape  # 10, 3, 3
        grand = float(arr.mean())
        part_m = arr.mean(axis=(1, 2))
        op_m = arr.mean(axis=(0, 2))
        cell_m = arr.mean(axis=2)

        ss_part = float(q_cnt * r_cnt * np.sum((part_m - grand) ** 2))
        ss_op = float(p_cnt * r_cnt * np.sum((op_m - grand) ** 2))
        ss_int = float(r_cnt * np.sum((cell_m - part_m[:, None] - op_m[None, :] + grand) ** 2))
        ss_err = float(np.sum((arr - cell_m[:, :, None]) ** 2))

        ms_part = ss_part / (p_cnt - 1)
        ms_op = ss_op / (q_cnt - 1)
        ms_int = ss_int / ((p_cnt - 1) * (q_cnt - 1))
        ms_err = ss_err / (p_cnt * q_cnt * (r_cnt - 1))

        var_repeat = ms_err
        var_int = max(0.0, (ms_int - ms_err) / r_cnt)
        var_op = max(0.0, (ms_op - ms_int) / (p_cnt * r_cnt))
        var_reprod = var_op + var_int
        var_grr = var_repeat + var_reprod
        var_part = max(0.0, (ms_part - ms_int) / (q_cnt * r_cnt))
        var_total = var_grr + var_part

        anova = {row["source"]: row for row in res["anova"]}
        self.assertEqual(anova["Part"]["df"], 9)
        self.assertEqual(anova["Operator"]["df"], 2)
        self.assertEqual(anova["Part * Operator"]["df"], 18)
        self.assertEqual(anova["Repeatability"]["df"], 60)
        self.assertEqual(anova["Total"]["df"], 89)

        self.assertAlmostEqual(anova["Part"]["ss"], ss_part, places=8)
        self.assertAlmostEqual(anova["Operator"]["ss"], ss_op, places=8)
        self.assertAlmostEqual(anova["Part * Operator"]["ss"], ss_int, places=8)
        self.assertAlmostEqual(anova["Repeatability"]["ss"], ss_err, places=8)

        comps = {c["key"]: c for c in res["variance_components"]}
        expected_vars = {
            "repeatability": var_repeat,
            "operator": var_op,
            "interaction": var_int,
            "reproducibility": var_reprod,
            "total_grr": var_grr,
            "part_to_part": var_part,
            "total": var_total,
        }
        for key, exp_var in expected_vars.items():
            self.assertAlmostEqual(comps[key]["variance"], exp_var, places=8)
            exp_sv = 6.0 * math.sqrt(exp_var)
            exp_pct_sv = 100.0 * math.sqrt(exp_var) / math.sqrt(var_total)
            self.assertAlmostEqual(comps[key]["study_variation"], exp_sv, places=7)
            self.assertAlmostEqual(comps[key]["percent_study_variation"], exp_pct_sv, places=6)


class TwoWayAnovaGlmParityTests(unittest.TestCase):
    """Two-Way ANOVA / GLM benchmark (Montgomery Battery Life 3x3x4 factorial)."""

    def test_montgomery_battery_life_two_way_anova(self):
        # Montgomery, Design and Analysis of Experiments, Table 5.1 (Battery Life)
        # 3 Material types x 3 Temperatures (15, 70, 125 F) x 4 replicates = 36 obs
        data = {
            ("M1", "15"):  [130, 155, 74, 180],
            ("M1", "70"):  [34, 40, 80, 75],
            ("M1", "125"): [20, 70, 82, 58],
            ("M2", "15"):  [150, 188, 159, 126],
            ("M2", "70"):  [136, 122, 106, 115],
            ("M2", "125"): [25, 70, 58, 45],
            ("M3", "15"):  [138, 110, 168, 160],
            ("M3", "70"):  [174, 120, 150, 139],
            ("M3", "125"): [96, 104, 82, 60],
        }
        life, material, temp = [], [], []
        for (m, t), vals in data.items():
            life.extend(vals)
            material.extend([m] * len(vals))
            temp.extend([t] * len(vals))

        sheet = Worksheet(
            "BatteryLife",
            [
                Column("Life", values=life),
                Column("Material", "text", material),
                Column("Temperature", "text", temp),
            ],
        )
        res = fit_glm(sheet, 0, [1, 2], [], terms=[[0], [1], [0, 1]])

        # Published Montgomery textbook ANOVA values
        self.assertEqual(res["df_error"], 27)
        self.assertEqual(res["df_total"], 35)
        self.assertAlmostEqual(res["ss_error"], 18230.75, places=6)
        self.assertAlmostEqual(res["ms_error"], 675.212962962963, places=6)

        terms = {row["source"]: row for row in res["anova_terms"]}
        expected = {
            "Material": (2, 10683.722222222222, 7.911372269380031, float(stats.f.sf(7.911372269380031, 2, 27))),
            "Temperature": (2, 39118.72222222222, 28.967691949042138, float(stats.f.sf(28.967691949042138, 2, 27))),
            "Material*Temperature": (4, 9613.777777777777, 3.559535400353798, float(stats.f.sf(3.559535400353798, 4, 27))),
        }
        for source, (df, ss, f_val, p_val) in expected.items():
            row = terms[source]
            self.assertEqual(row["df"], df)
            self.assertAlmostEqual(row["adj_ss"], ss, places=6)
            self.assertAlmostEqual(row["seq_ss"], ss, places=6)
            self.assertAlmostEqual(row["f"], f_val, places=6)
            self.assertAlmostEqual(row["p_value"], p_val, places=8)


class WeibullReliabilityParityTests(unittest.TestCase):
    """Weibull Reliability MLE parity for uncensored and right-censored data."""

    @staticmethod
    def _weibull_mle_oracle(times, events):
        """Solve exact Weibull MLE score equations independently via root-finding."""
        t = np.asarray(times, dtype=float)
        e = np.asarray(events, dtype=float)
        r = float(np.sum(e))
        sum_log_fail = float(np.sum(np.log(t[e == 1])))

        def score_beta(beta):
            tb = t ** beta
            return r / beta + sum_log_fail - r * float(np.sum(tb * np.log(t))) / float(np.sum(tb))

        beta_hat = float(optimize.brentq(score_beta, 1e-3, 100.0, xtol=1e-13, rtol=1e-13))
        eta_hat = float((np.sum(t ** beta_hat) / r) ** (1.0 / beta_hat))
        b10 = eta_hat * (-math.log(0.90)) ** (1.0 / beta_hat)
        b50 = eta_hat * (-math.log(0.50)) ** (1.0 / beta_hat)
        return beta_hat, eta_hat, b10, b50

    def test_weibull_mle_uncensored_lieblein_zelen(self):
        # Lieblein & Zelen (1956) deep-groove ball bearing endurance (23 failures, 10^6 revs)
        times = [
            17.88, 28.92, 33.00, 41.52, 42.12, 45.60, 48.80, 51.84,
            51.96, 54.12, 55.56, 67.80, 68.44, 68.64, 68.88, 84.12,
            93.12, 98.64, 105.12, 105.84, 127.92, 128.04, 173.40,
        ]
        res = run_reliability_analysis(times, dist_name="weibull")
        beta_ref, eta_ref, b10_ref, b50_ref = self._weibull_mle_oracle(times, [1] * len(times))

        self.assertAlmostEqual(res["parameters"]["shape"], beta_ref, places=5)
        self.assertAlmostEqual(res["parameters"]["scale"], eta_ref, places=4)

        ptable = {row["percent"]: row["estimate"] for row in res["percentile_table"]}
        self.assertAlmostEqual(ptable[10.0], b10_ref, places=4)
        self.assertAlmostEqual(ptable[50.0], b50_ref, places=4)

    def test_weibull_mle_right_censored_reference(self):
        # Right-censored lifetime dataset (12 failures, 8 right-censored units)
        times = [
            120, 185, 240, 295, 350, 410, 460, 520, 590, 650,
            710, 780, 300, 450, 600, 600, 800, 800, 900, 900,
        ]
        events = [1] * 12 + [0] * 8

        res = run_reliability_analysis(times, censor_values=events, dist_name="weibull")
        beta_ref, eta_ref, b10_ref, b50_ref = self._weibull_mle_oracle(times, events)

        self.assertEqual(res["n_total"], 20)
        self.assertEqual(res["n_events"], 12)
        self.assertEqual(res["n_censored"], 8)
        self.assertAlmostEqual(res["parameters"]["shape"], beta_ref, places=5)
        self.assertAlmostEqual(res["parameters"]["scale"], eta_ref, places=3)

        ptable = {row["percent"]: row["estimate"] for row in res["percentile_table"]}
        self.assertAlmostEqual(ptable[10.0], b10_ref, places=3)
        self.assertAlmostEqual(ptable[50.0], b50_ref, places=3)


if __name__ == "__main__":
    unittest.main()
