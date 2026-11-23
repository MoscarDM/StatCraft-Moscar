import math
import unittest
from scipy import stats
from statcraft.engine import MISSING_SENTINEL
from statcraft.variance_tests import equal_variances


class VarianceTests(unittest.TestCase):
    def test_hand_derived_median_deviation_anova(self):
        # Medians2,3; absolute deviations [1,0,1],[2,0,2].
        # Between SS2/3, withinSS10/3; DF1,4 -> F4/5.
        r=equal_variances([[1,2,3],[1,3,5]])
        self.assertAlmostEqual(r['test_statistic'],.8,places=14)
        self.assertEqual(r['df'],[1,4])
        # F(1,4) is t(4)^2; separate distribution identity validates tail.
        self.assertAlmostEqual(r['p_value'],float(2*stats.t.sf(math.sqrt(.8),4)),places=14)
        self.assertIn('Brown-Forsythe',r['method'])
        self.assertEqual([g['median'] for g in r['group_statistics']],[2,3])

    def test_hand_bartlett_and_chi_square_one_tail(self):
        # Sample variances1,4; pooled variance2.5 and correction1.25.
        t=(4*math.log(2.5)-2*math.log(4))/1.25
        r=equal_variances([[1,2,3],[1,3,5]],method='Bartlett')
        self.assertAlmostEqual(r['test_statistic'],t,places=14)
        self.assertAlmostEqual(r['p_value'],math.erfc(math.sqrt(t/2)),places=14)
        self.assertEqual(r['df'],1);self.assertIsNone(r['df_denominator'])

    def test_unequal_sizes_skewed_group_independent_scipy_fixtures(self):
        groups=[[float(v) for v in g] for g in [[0,1,1,9],[2,3,4,5,6],[1,2,4,8,16,32]]]
        for method,reference in [('Levene',stats.levene(*groups,center='median')),
                                 ('Bartlett',stats.bartlett(*groups))]:
            r=equal_variances(groups,method)
            self.assertAlmostEqual(r['test_statistic'],float(reference.statistic),places=12)
            self.assertAlmostEqual(r['p_value'],float(reference.pvalue),places=13)

    def test_equal_spreads_shifted_groups_and_scale_invariance(self):
        for method in ('Levene','Bartlett'):
            r=equal_variances([[1,2,3],[11,12,13]],method)
            self.assertEqual(r['test_statistic'],0);self.assertEqual(r['p_value'],1)
            a=equal_variances([[1,2,3],[1,3,5]],method)
            b=equal_variances([[1e100,2e100,3e100],[1e100,3e100,5e100]],method)
            self.assertAlmostEqual(a['test_statistic'],b['test_statistic'],places=12)

    def test_missing_independent_by_group_and_summary(self):
        r=equal_variances([[1,None,2,3,MISSING_SENTINEL],[1,math.inf,3,5,math.nan]])
        self.assertEqual((r['count'],r['missing']),(6,4))
        self.assertEqual([(g['count'],g['missing']) for g in r['group_statistics']],[(3,2),(3,2)])
        self.assertAlmostEqual(r['test_statistic'],.8,places=14)

    def test_degenerate_residuals_and_zero_variances(self):
        for groups in ([[1,1,1],[2,2,2]],[[1,3],[1,5]]):
            with self.assertRaises(ValueError):equal_variances(groups)
        for groups in ([[1,1,1],[1,2,3]],[[1,1,1],[1,1,1]]):
            with self.assertRaises(ValueError):equal_variances(groups,'Bartlett')
        # One constant group is valid for Brown-Forsythe when denominator >0.
        self.assertTrue(math.isfinite(equal_variances([[1,1,1],[1,2,3]])['test_statistic']))

    def test_validation_method_and_finite_arithmetic(self):
        for groups in ([],[[1,2,3]],[[1],[1,2]],[[None,1],[1,2]]):
            with self.assertRaises(ValueError):equal_variances(groups)
        for method in ('mean', None, 'unknown'):
            with self.assertRaises(ValueError):equal_variances([[1,2,3],[1,3,5]],method)
        for bad_alpha in (0.0, 1.0, -0.05, 1.5, math.nan, 'bad'):
            with self.assertRaises(ValueError):equal_variances([[1,2,3],[1,3,5]], 'Bonett', alpha=bad_alpha)
        with self.assertRaises(TypeError):equal_variances([[True,2],[1,3]])
        with self.assertRaises(ValueError):equal_variances([[-1e308,1e308],[1,2,3]])
        a=equal_variances([[1,2,3],[1,3,5]],'Brown-Forsythe')
        self.assertAlmostEqual(a['test_statistic'],.8,places=14)

    def test_bonett_and_multiple_comparisons_intervals(self):
        g1 = [10.1, 10.4, 9.8, 10.2, 10.5, 9.9]
        g2 = [12.0, 14.5, 11.2, 15.1, 13.0, 14.8]
        res = equal_variances([g1, g2], method="MultipleComparisons", alpha=0.05)
        self.assertIn("bonett_p_value", res)
        self.assertIn("multiple_comparisons_p_value", res)
        self.assertEqual(len(res["confidence_intervals"]), 2)
        self.assertAlmostEqual(res["p_value"], res["multiple_comparisons_p_value"], places=12)
        self.assertEqual(res["df"], 1)
        self.assertIsNone(res["df_denominator"])

        bonett_res = equal_variances([g1, g2], method="Bonett", alpha=0.05)
        self.assertAlmostEqual(bonett_res["p_value"], bonett_res["bonett_p_value"], places=12)
        self.assertAlmostEqual(bonett_res["p_value"], res["bonett_p_value"], places=12)
        self.assertEqual(bonett_res["df"], 1)
        self.assertGreater(bonett_res["test_statistic"], 0.0)
        self.assertLess(bonett_res["p_value"], 0.05)

        for ci in res["confidence_intervals"]:
            sd = ci["stdev"]
            var = ci["variance"]
            self.assertAlmostEqual(var, sd ** 2, places=12)
            b_lo, b_hi = ci["bonett_ci_stdev"]
            bv_lo, bv_hi = ci["bonett_ci_variance"]
            c_lo, c_hi = ci["chi2_ci_stdev"]
            cv_lo, cv_hi = ci["chi2_ci_variance"]
            self.assertGreater(b_lo, 0.0)
            self.assertLess(b_lo, sd)
            self.assertGreater(b_hi, sd)
            self.assertAlmostEqual(bv_lo, b_lo ** 2, places=12)
            self.assertAlmostEqual(bv_hi, b_hi ** 2, places=12)
            self.assertGreater(c_lo, 0.0)
            self.assertLess(c_lo, sd)
            self.assertGreater(c_hi, sd)
            self.assertAlmostEqual(cv_lo, c_lo ** 2, places=12)
            self.assertAlmostEqual(cv_hi, c_hi ** 2, places=12)

    def test_bonett_and_mc_scale_shift_and_small_n_safety(self):
        # Equal spreads shifted: statistic=0, p=1
        for method in ("Bonett", "MultipleComparisons"):
            r = equal_variances([[1, 2, 3, 4], [11, 12, 13, 14]], method=method)
            self.assertAlmostEqual(r["test_statistic"], 0.0, places=12)
            self.assertAlmostEqual(r["p_value"], 1.0, places=12)
            # Scale invariance
            a = equal_variances([[1, 2, 3, 4], [1, 3, 5, 7]], method=method)
            b = equal_variances([[1e50, 2e50, 3e50, 4e50], [1e50, 3e50, 5e50, 7e50]], method=method)
            self.assertAlmostEqual(a["test_statistic"], b["test_statistic"], places=10)

        # Small n=2 and skewed groups must not divide by zero or produce negative df
        r_small = equal_variances([[1.0, 2.0], [1.0, 1.0, 1.0, 100.0]], method="Bonett", alpha=0.10)
        self.assertTrue(math.isfinite(r_small["test_statistic"]))
        self.assertTrue(0.0 <= r_small["p_value"] <= 1.0)
        self.assertEqual(len(r_small["confidence_intervals"]), 2)

        # Zero variance group: Bonett raises ValueError, Levene handles safely with (0, 0) CIs
        with self.assertRaises(ValueError):
            equal_variances([[1, 1, 1], [1, 2, 3]], method="Bonett")
        r_lev = equal_variances([[1, 1, 1], [1, 2, 3]], method="Levene")
        self.assertEqual(r_lev["confidence_intervals"][0]["bonett_ci_stdev"], (0.0, 0.0))
        self.assertEqual(r_lev["confidence_intervals"][0]["chi2_ci_stdev"], (0.0, 0.0))
        self.assertIsNone(r_lev["bonett_p_value"])


if __name__=='__main__':unittest.main()
