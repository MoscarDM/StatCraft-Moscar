import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


EXPECTED_SCREENSHOTS = [
    "01_large_worksheet.png",
    "02_dark_compact_layout.png",
    "03_charts_and_tabs.png",
    "04_dialogs.png",
    "05_mpx_and_session.png",
]


class VisualStressHarnessTests(unittest.TestCase):
    def test_visual_stress_script_emits_manifest_and_screenshots(self):
        repo_root = Path(__file__).resolve().parent.parent
        script = repo_root / "scripts" / "visual_stress_suite.py"
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(script), "--out-dir", tmp, "--quick"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

            out_dir = Path(tmp)
            manifest_path = out_dir / "manifest.json"
            self.assertTrue(manifest_path.exists(), "manifest.json was not created")

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest.get("unhandled_exceptions"), 0)
            self.assertEqual(len(manifest.get("scenarios", [])), 5)
            for scenario in manifest["scenarios"]:
                self.assertEqual(scenario.get("status"), "ok", scenario)
                self.assertIn("duration_sec", scenario)
                shot = Path(scenario["screenshot"])
                self.assertTrue(shot.exists(), f"Missing screenshot: {shot}")
                self.assertGreater(shot.stat().st_size, 0, f"Empty screenshot: {shot}")

            for name in EXPECTED_SCREENSHOTS:
                p = out_dir / name
                self.assertTrue(p.exists(), f"Missing expected PNG: {name}")
                self.assertGreater(p.stat().st_size, 0, f"Empty expected PNG: {name}")


if __name__ == "__main__":
    unittest.main()
