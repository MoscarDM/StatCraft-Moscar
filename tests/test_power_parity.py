import unittest
from statcraft import power_extended as power


class PowerParityTests(unittest.TestCase):
    def test_estimation_resistor_example(self):
        solve = power.estimation_planning(planning_value=22.5, margins=[5])
        self.assertEqual(solve["rows"][0]["sample_size"], 81)
        inverse = power.estimation_planning(planning_value=22.5, sample_sizes=[80, 81])
        self.assertGreater(inverse["rows"][0]["margin"], 5)
        self.assertLessEqual(inverse["rows"][1]["margin"], 5)

    def test_estimation_exact_binomial_and_poisson_intervals(self):
        binomial = power.estimation_planning(parameter="Proportion (Binomial)", planning_value=.2, sample_sizes=[10])
        self.assertAlmostEqual(binomial["rows"][0]["lower_margin"], .1747893)
        self.assertAlmostEqual(binomial["rows"][0]["upper_margin"], .3560955)
        rate = power.estimation_planning(parameter="Poisson Rate", planning_value=2, exposure=2, sample_sizes=[5])
        self.assertAlmostEqual(rate["rows"][0]["lower_margin"], 2 - 1.22165196, places=6)
        self.assertAlmostEqual(rate["rows"][0]["upper_margin"], 3.08883780 - 2, places=6)

    def test_blocked_full_factorial_reference(self):
        result = power.general_factorial_power(levels=[3, 3], effect=.4, stdev=.15,
                                               target_power=.9, blocked=True)
        self.assertEqual((result["replicates"], result["total_runs"]), (2, 18))
        self.assertAlmostEqual(result["actual_power"], .930521, places=6)

    def test_plackett_burman_reference_with_center_points(self):
        for reps, expected in enumerate([.272032, .720550, .894838, .963485], 1):
            result = power.plackett_burman_power(factors=10, corner_points=12, center_points=3,
                                                replicates=reps, effect=5, stdev=4.5)
            self.assertEqual(result["total_runs"], 12 * reps + 3)
            self.assertAlmostEqual(result["actual_power"], expected, places=6)

    def test_equivalence_difference_reference(self):
        paired = power.equivalence_difference_power(
            design="Paired", lower_limit=-.5, upper_limit=.5, difference=.2,
            stdev=.42, sample_size=14,
        )
        self.assertAlmostEqual(paired["actual_power"], .811858, places=6)
        crossover = power.equivalence_difference_power(
            design="2x2 Crossover Design", lower_limit=-.425, upper_limit=.425,
            difference=.4, stdev=.088, target_power=.9,
        )
        self.assertEqual(crossover["sample_size"], 107)
        self.assertAlmostEqual(crossover["actual_power"], .900500, places=6)
