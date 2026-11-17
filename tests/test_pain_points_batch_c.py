import math
import unittest

from statcraft.graph_ergonomics import (
    add_percentile_line,
    add_reference_line,
    toggle_graph_gridlines,
    update_graph_annotations,
)
from statcraft.graph_presentation import graph_presentation, parse_ref_lines


def _sample_entry(title="Scatter of Y vs X"):
    return {
        "title": title,
        "result": {
            "graph": "scatterplot",
            "panels": [{"kind": "xy", "x_label": "X", "y_label": "Y"}],
        },
    }


class GraphErgonomicsBatchCTests(unittest.TestCase):
    # --- Item 12 (#44346): add_reference_line ---

    def test_add_reference_line_appends_x_and_y_lines(self):
        entry = _sample_entry()
        ret = add_reference_line(entry, "y", 10.5, label="Target")
        self.assertIs(ret, entry)
        add_reference_line(entry, "Y", 25, label="Upper")
        add_reference_line(entry, "x", -3.25)

        pres = graph_presentation(entry)
        self.assertEqual(parse_ref_lines(pres["y_ref_line"]), [10.5, 25.0])
        self.assertEqual(parse_ref_lines(pres["x_ref_line"]), [-3.25])
        self.assertEqual(
            entry["reference_lines"],
            [
                {"axis": "y", "value": 10.5, "label": "Target"},
                {"axis": "y", "value": 25.0, "label": "Upper"},
                {"axis": "x", "value": -3.25, "label": ""},
            ],
        )

    def test_add_reference_line_preserves_existing_presentation_refs(self):
        entry = _sample_entry()
        entry["graph_presentation"] = {"x_ref_line": "1, 2"}
        add_reference_line(entry, "x", 5.0)
        pres = graph_presentation(entry)
        self.assertEqual(parse_ref_lines(pres["x_ref_line"]), [1.0, 2.0, 5.0])

    def test_add_reference_line_validation_errors(self):
        entry = _sample_entry()
        for bad_entry in (None, [], "not-a-dict"):
            with self.assertRaises(ValueError):
                add_reference_line(bad_entry, "y", 1.0)
        for bad_axis in ("z", "", "xy", None, 1):
            with self.assertRaises(ValueError):
                add_reference_line(entry, bad_axis, 1.0)
        for bad_val in (math.nan, math.inf, -math.inf, True, False, "5", None):
            with self.assertRaises(ValueError):
                add_reference_line(entry, "y", bad_val)
        with self.assertRaises(ValueError):
            add_reference_line(entry, "y", 1.0, label=123)

    # --- Item 12 (#44347): add_percentile_line ---

    def test_add_percentile_line_computes_and_adds_ref_line(self):
        entry = _sample_entry()
        values = [10, 20, 30, 40, 50]
        add_percentile_line(entry, values, 50, axis="y")
        add_percentile_line(entry, values, 90, axis="x")

        pres = graph_presentation(entry)
        self.assertEqual(parse_ref_lines(pres["y_ref_line"]), [30.0])
        self.assertEqual(parse_ref_lines(pres["x_ref_line"]), [46.0])
        self.assertEqual(entry["reference_lines"][0]["label"], "P50")
        self.assertEqual(entry["reference_lines"][1]["label"], "P90")

    def test_add_percentile_line_validation_errors(self):
        entry = _sample_entry()
        for bad_pct in (0, 100, -5, 105, math.nan, math.inf, True, "50"):
            with self.assertRaises(ValueError):
                add_percentile_line(entry, [1, 2, 3], bad_pct)
        for bad_values in ([], (), "123", None, [1, math.nan], [1, math.inf], [True, 2], ["a"]):
            with self.assertRaises(ValueError):
                add_percentile_line(entry, bad_values, 50)
        with self.assertRaises(ValueError):
            add_percentile_line(entry, [1, 2, 3], 50, axis="z")

    # --- Item 13 (#44349-#44351): update_graph_annotations ---

    def test_update_graph_annotations_sets_and_clears_fields(self):
        entry = _sample_entry("Initial Title")
        update_graph_annotations(
            entry,
            title="Updated Title",
            subtitle="Batch A vs B",
            footnote="Source: Lab 2026",
        )
        pres = graph_presentation(entry)
        self.assertEqual(entry["title"], "Updated Title")
        self.assertEqual(pres["title"], "Updated Title")
        self.assertTrue(pres["title_enabled"])
        self.assertEqual(pres["subtitle"], "Batch A vs B")
        self.assertTrue(pres["subtitle_enabled"])
        self.assertEqual(pres["footnote"], "Source: Lab 2026")
        self.assertTrue(pres["footnote_enabled"])

        # Partial update leaves other fields intact
        update_graph_annotations(entry, subtitle="   ")
        pres2 = graph_presentation(entry)
        self.assertEqual(pres2["title"], "Updated Title")
        self.assertEqual(pres2["subtitle"], "")
        self.assertFalse(pres2["subtitle_enabled"])
        self.assertEqual(pres2["footnote"], "Source: Lab 2026")
        self.assertTrue(pres2["footnote_enabled"])

    def test_update_graph_annotations_validation_errors(self):
        entry = _sample_entry()
        with self.assertRaises(ValueError):
            update_graph_annotations(entry, title="x" * 146)
        with self.assertRaises(ValueError):
            update_graph_annotations(entry, subtitle=42)
        with self.assertRaises(ValueError):
            update_graph_annotations(entry, footnote=["bad"])

    # --- Item 14 (#44352): toggle_graph_gridlines ---

    def test_toggle_graph_gridlines_toggles_and_sets_explicit(self):
        entry = _sample_entry()
        # Default grid_enabled is True, so first toggle turns it False
        state1 = toggle_graph_gridlines(entry)
        self.assertIs(state1, False)
        self.assertFalse(graph_presentation(entry)["grid_enabled"])

        # Second toggle turns it back True
        state2 = toggle_graph_gridlines(entry)
        self.assertIs(state2, True)
        self.assertTrue(graph_presentation(entry)["grid_enabled"])

        # Explicit show=False / show=True
        self.assertIs(toggle_graph_gridlines(entry, show=False), False)
        self.assertFalse(graph_presentation(entry)["grid_enabled"])
        self.assertIs(toggle_graph_gridlines(entry, show=True), True)
        self.assertTrue(graph_presentation(entry)["grid_enabled"])

    def test_toggle_graph_gridlines_validation_errors(self):
        entry = _sample_entry()
        for bad_show in (1, 0, "true", []):
            with self.assertRaises(ValueError):
                toggle_graph_gridlines(entry, show=bad_show)


if __name__ == "__main__":
    unittest.main()
