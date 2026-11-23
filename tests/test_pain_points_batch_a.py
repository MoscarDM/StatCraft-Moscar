"""Tests for Batch A (Pain Points #27459, #42469, #42460, #42473-#42475): statcraft.session_io."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from statcraft.model import Column, Matrix, Worksheet
from statcraft.session_io import (
    autosave_snapshot,
    clear_autosave_snapshot,
    export_history_script,
    export_session_window,
    load_autosave_snapshot,
    order_navigator_entries,
)


class ExportHistoryScriptTests(unittest.TestCase):
    def test_exports_mtb_script_and_creates_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "session_history.mtb"
            result = export_history_script(["DESCRIBE C1\r\n", "HISTOGRAM C1", "TTEST C1; MU 0."], target)
            self.assertEqual(result, target)
            self.assertTrue(target.is_file())
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "DESCRIBE C1\nHISTOGRAM C1\nTTEST C1; MU 0.\n",
            )
            # No leftover temp files
            self.assertEqual([p.name for p in target.parent.iterdir()], ["session_history.mtb"])

    def test_empty_history_writes_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "empty.txt"
            result = export_history_script([], target)
            self.assertEqual(result, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "")


class ExportSessionWindowTests(unittest.TestCase):
    def test_export_html_escapes_content_and_renders_entries(self):
        entries = [
            {
                "title": "Descriptive <Statistics>",
                "time": "2026-11-17 10:00:00",
                "worksheet": "Worksheet 1",
                "text": "Mean = 12.5 & StDev = 1.2\n<script>alert(1)</script>",
            },
            {
                "title": "One-Sample t",
                "time": "2026-11-17 10:05:00",
                "result": {"n": 10, "mean": 5.0},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "session.html"
            result = export_session_window(entries, target, fmt="html")
            self.assertEqual(result, target)
            html_text = target.read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE html>", html_text)
            self.assertIn("Descriptive &lt;Statistics&gt;", html_text)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_text)
            self.assertNotIn("<script>alert(1)</script>", html_text)
            self.assertIn("One-Sample t", html_text)
            self.assertIn("Mean", html_text)

    def test_export_txt_and_empty_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_txt = Path(tmp) / "empty.txt"
            export_session_window([], empty_txt, fmt="txt")
            self.assertEqual(empty_txt.read_text(encoding="utf-8"), "")

            empty_html = Path(tmp) / "empty.html"
            export_session_window([], empty_html, fmt="HTML")
            self.assertIn("No session", empty_html.read_text(encoding="utf-8"))

            filled_txt = Path(tmp) / "filled.txt"
            export_session_window(
                [{"title": "Summary", "time": "12:00", "text": "N = 42"}],
                filled_txt,
                fmt=".txt",
            )
            content = filled_txt.read_text(encoding="utf-8")
            self.assertIn("Summary", content)
            self.assertIn("N = 42", content)

    def test_invalid_format_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                export_session_window([], Path(tmp) / "out.pdf", fmt="pdf")


class AutosaveSnapshotTests(unittest.TestCase):
    def test_roundtrip_worksheet_and_history(self):
        ws = Worksheet(
            name="Data 1",
            columns=[
                Column("X", "number", [1.0, 2.5, None], {"unit": "mm"}),
                Column("Group", "text", ["A", "B", "A"]),
            ],
            constants=[Column("K1", "number", [3.14])],
            matrices=[Matrix("M1", 2, 2, [1.0, 2.0, 3.0, 4.0])],
            metadata={"source": "test"},
        )
        history = [
            {"title": "Describe X", "command": "DESCRIBE C1", "val": math.nan},
            {"title": "TTest", "command": "TTEST C1"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "recovery" / "autosave.json"
            written = autosave_snapshot(ws, history, snap_path)
            self.assertEqual(written, snap_path)
            self.assertTrue(snap_path.is_file())
            self.assertEqual([p.name for p in snap_path.parent.iterdir()], ["autosave.json"])

            loaded = load_autosave_snapshot(snap_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["worksheet"], ws)
            self.assertEqual(len(loaded["history"]), 2)
            self.assertIsNone(loaded["history"][0]["val"])
            self.assertEqual(loaded["history"][1]["command"], "TTEST C1")

            clear_autosave_snapshot(snap_path)
            self.assertFalse(snap_path.exists())
            # Clearing again is a safe no-op
            clear_autosave_snapshot(snap_path)

    def test_roundtrip_none_worksheet_and_corrupt_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "autosave.json"
            self.assertIsNone(load_autosave_snapshot(snap_path))

            autosave_snapshot(None, [], snap_path)
            loaded = load_autosave_snapshot(snap_path)
            self.assertIsNotNone(loaded)
            self.assertIsNone(loaded["worksheet"])
            self.assertEqual(loaded["history"], [])

            # Corrupt JSON returns None
            snap_path.write_text("{broken json", encoding="utf-8")
            self.assertIsNone(load_autosave_snapshot(snap_path))

            # Wrong schema returns None
            snap_path.write_text(json.dumps({"schema": "other", "version": 1}), encoding="utf-8")
            self.assertIsNone(load_autosave_snapshot(snap_path))

    def test_atomic_write_preserves_existing_on_error(self):
        ws = Worksheet("Good", [Column("C1", "number", [1.0, 2.0])])
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "autosave.json"
            autosave_snapshot(ws, [{"title": "First"}], snap_path)

            bad_ws = Worksheet("Bad", [Column("C1", "number", [1.0])])
            bad_ws.columns[0].values = [float("nan")]  # violates validate()
            with self.assertRaises(ValueError):
                autosave_snapshot(bad_ws, [{"title": "Second"}], snap_path)

            loaded = load_autosave_snapshot(snap_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["worksheet"].name, "Good")
            self.assertEqual(loaded["history"], [{"title": "First"}])


class OrderNavigatorEntriesTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {"id": 1, "title": "Zebra Summary", "worksheet": "Sheet B"},
            {"id": 2, "title": "Alpha Plot", "worksheet": "Sheet A"},
            {"id": 3, "title": "Beta Test", "worksheet": "Sheet B"},
            {"id": 4, "title": "Gamma Note"},
            {"id": 5, "title": "alpha check", "worksheet": "sheet a"},
        ]

    def test_chronological_preserves_order_without_mutating(self):
        ordered = order_navigator_entries(self.entries, mode="chronological")
        self.assertEqual([e["id"] for e in ordered], [1, 2, 3, 4, 5])
        self.assertIsNot(ordered, self.entries)

    def test_worksheet_groups_case_insensitively_and_puts_missing_last(self):
        ordered = order_navigator_entries(self.entries, mode="worksheet")
        self.assertEqual([e["id"] for e in ordered], [2, 5, 1, 3, 4])

    def test_title_sorts_case_insensitively_and_stably(self):
        ordered = order_navigator_entries(self.entries, mode="title")
        self.assertEqual([e["id"] for e in ordered], [5, 2, 3, 4, 1])

    def test_empty_and_invalid_mode(self):
        self.assertEqual(order_navigator_entries([], mode="title"), [])
        with self.assertRaises(ValueError):
            order_navigator_entries(self.entries, mode="unknown")


if __name__ == "__main__":
    unittest.main()
