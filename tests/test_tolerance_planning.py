import unittest

from statcraft import power_extended


class TolerancePlanningTests(unittest.TestCase):
    def test_published_washer_sample_sizes(self):
        result = power_extended.tolerance_interval_planning(maximum_coverages=[.96, .97])
        self.assertEqual(
            [(r["normal"], r["nonparametric"]) for r in result["rows"]],
            [(2480, 4654), (525, 1036)],
        )

    def test_published_washer_maximum_coverages(self):
        result = power_extended.tolerance_interval_planning(sample_sizes=[50, 100])
        for row, normal, nonparametric, confidence in zip(
            result["rows"], [.994015, .986914], [.992846, .996435], [.721, .963]
        ):
            self.assertAlmostEqual(row["normal"], normal, places=6)
            self.assertAlmostEqual(row["nonparametric"], nonparametric, places=6)
            self.assertAlmostEqual(row["achieved_confidence"], confidence, places=3)

    def test_normal_one_sided_bounds_match_and_invert(self):
        lower = power_extended.tolerance_interval_planning(sample_sizes=[80], interval_type="Lower bound")
        upper = power_extended.tolerance_interval_planning(sample_sizes=[80], interval_type="Upper bound")
        self.assertEqual(lower["rows"], upper["rows"])
        row = lower["rows"][0]
        self.assertGreater(row["normal"], .95)
        planned = power_extended.tolerance_interval_planning(
            maximum_coverages=[row["normal"] + 1e-9], interval_type="Lower bound"
        )
        self.assertEqual(planned["rows"][0]["normal"], 80)

    def test_rejects_invalid_inputs(self):
        for arguments in (
            {}, {"sample_sizes": [50], "maximum_coverages": [.96]},
            {"sample_sizes": [1]}, {"sample_sizes": [50.1]},
            {"maximum_coverages": [.94]}, {"sample_sizes": [50], "excess_probability": .99},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                power_extended.tolerance_interval_planning(**arguments)

    def test_presenter_rerun_and_report(self):
        from statcraft.app import Presenter, format_entry
        from statcraft.phase6_reports import sections

        presenter = Presenter()
        entry = presenter.extended_power("tolerance_planning", sample_sizes=[50, 100])
        self.assertEqual(presenter.rerun_result(entry)["result"], entry["result"])
        self.assertIn("99.4015%", format_entry(entry))
        self.assertEqual(sections(entry["result"])[1][2][0][:3], [50, "99.4015%", "99.2846%"])
        old = presenter.extended_power("tolerance_interval", margin_ratio=1.25)
        self.assertEqual(presenter.rerun_result(old)["result"], old["result"])


if __name__ == "__main__":
    unittest.main()
