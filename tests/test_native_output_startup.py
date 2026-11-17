import unittest

from statcraft.modern_app import initial_native_output


class NativeOutputStartupTests(unittest.TestCase):
    def test_startup_prefers_latest_renderable_saved_graph(self):
        outputs = [
            {"title": "Older chart", "result": {"analysis": "native_saved_output",
                                                    "graphs": [{"panels": [{"kind": "histogram"}]}]}},
            {"title": "Newer chart", "result": {"analysis": "native_saved_output",
                                                     "graphs": [{"panels": [{"kind": "contour"}]}]}},
            {"title": "Unsupported optimization", "result": {"analysis": "native_saved_output",
                                                                "graphs": [{"warnings": ["unsupported"]}]}},
        ]
        self.assertIs(initial_native_output(outputs), outputs[1])

    def test_startup_falls_back_to_latest_output_when_no_chart_is_renderable(self):
        outputs = [
            {"title": "First", "result": {"analysis": "native_saved_output", "graphs": []}},
            {"title": "Last", "result": {"analysis": "native_saved_output",
                                             "graphs": [{"warnings": ["unsupported"]}]}},
        ]
        self.assertIs(initial_native_output(outputs), outputs[-1])


if __name__ == "__main__":
    unittest.main()
