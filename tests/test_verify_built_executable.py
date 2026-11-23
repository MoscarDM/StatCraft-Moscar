"""Unit tests for StatCraft --smoke-verify and scripts/verify_built_executable.py."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["STATCRAFT_TESTING"] = "1"

_root = Path(__file__).resolve().parent.parent
_deps = _root.parent / "statcraft-build-deps"
if _deps.exists() and str(_deps) not in sys.path:
    sys.path.insert(0, str(_deps))
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
if str(_root / "scripts") not in sys.path:
    sys.path.insert(0, str(_root / "scripts"))

import statcraft
from statcraft.smoke_verify import run_smoke_verify
import verify_built_executable as vbe


class VerifyBuiltExecutableTests(unittest.TestCase):
    def test_run_smoke_verify_direct(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = run_smoke_verify()
        self.assertEqual(code, 0)
        payload = vbe.parse_smoke_payload(buf.getvalue())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["version"], statcraft.__version__)
        self.assertEqual(payload["rows"], 5)
        self.assertGreater(payload["mpx_bytes"], 0)
        self.assertGreater(payload["xlsx_bytes"], 0)
        self.assertEqual(payload["factorial_charts"], ["Effects Pareto", "Residual Plots"])
        self.assertEqual(payload["response_surface_grid_points"], 81)
        self.assertEqual(payload["fractional_graph_exports"], 3)
        self.assertEqual(payload["regression_residual_rows"], [1, 2, 4, 5, 6, 7, 8, 9])
        self.assertEqual(payload["fitted_line_interval_points"], 120)
        self.assertEqual(payload["basic_statistics_workflows"], 9)
        self.assertEqual(payload["quality_workflows"], 6)
        self.assertTrue(payload["packaged_acceptance"]["freeze_panes_ok"])
        self.assertEqual(
            payload["packaged_acceptance"]["exported_png_count"],
            payload["packaged_acceptance"]["distinct_png_hashes"],
        )
        self.assertTrue(payload["operating_window_flagship"]["optimum_drift_failed"])
        self.assertTrue(payload["operating_window_flagship"]["robust_drift_feasible"])
        self.assertTrue(payload["operating_window_flagship"]["confirmation_confirmed"])
        self.assertGreater(payload["operating_window_flagship"]["drift_feasible_pct"], 0.0)

    def test_python_module_smoke_verify_cli(self):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["STATCRAFT_TESTING"] = "1"
        env["PYTHONPATH"] = str(_root)
        proc = subprocess.run(
            [sys.executable, "-m", "statcraft", "--smoke-verify"],
            cwd=str(_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = vbe.parse_smoke_payload(proc.stdout)
        self.assertEqual(payload["version"], statcraft.__version__)

    def test_launch_modern_smoke_verify_cli(self):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["STATCRAFT_TESTING"] = "1"
        proc = subprocess.run(
            [sys.executable, str(_root / "launch_modern.py"), "--smoke-verify"],
            cwd=str(_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = vbe.parse_smoke_payload(proc.stdout)
        self.assertEqual(payload["version"], statcraft.__version__)

    def test_verify_script_python_module_and_json_report(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_path = Path(tmp_dir) / "verify-report.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(_root / "scripts" / "verify_built_executable.py"),
                    "--python-module",
                    "--json-out",
                    str(report_path),
                ],
                cwd=str(_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("SHA-256:", proc.stdout)
            self.assertIn("Smoke verify: PASSED", proc.stdout)
            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["version"], statcraft.__version__)
            self.assertEqual(len(report["sha256"]), 64)

    def test_verify_script_missing_exe_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_exe = Path(tmp_dir) / "MissingStatCraft.exe"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(_root / "scripts" / "verify_built_executable.py"),
                    "--exe",
                    str(missing_exe),
                ],
                cwd=str(_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Executable not found", proc.stderr)

    def test_verify_target_version_mismatch_fails(self):
        with self.assertRaises(RuntimeError) as ctx:
            vbe.verify_target(python_module=True, expected_version="0.0.0-mismatch")
        self.assertIn("Version mismatch", str(ctx.exception))

    def test_verify_target_exe_mode_computes_sha256(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fake_exe = Path(tmp_dir) / "StatCraft.exe"
            fake_exe.write_bytes(b"MZ-statcraft-test-binary")
            expected_hash = vbe.compute_sha256(fake_exe)
            fake_stdout = (
                f'STATCRAFT_SMOKE_VERIFY={{"status": "ok", "version": "{statcraft.__version__}", '
                f'"rows": 5, "mpx_bytes": 128, "xlsx_bytes": 256}}\n'
            )
            fake_proc = subprocess.CompletedProcess(
                args=[str(fake_exe), "--smoke-verify"],
                returncode=0,
                stdout=fake_stdout,
                stderr="",
            )
            with mock.patch("verify_built_executable.subprocess.run", return_value=fake_proc) as run_mock:
                report = vbe.verify_target(exe_path=fake_exe)
            run_mock.assert_called_once()
            self.assertEqual(run_mock.call_args.args[0], [str(fake_exe.resolve()), "--smoke-verify"])
            self.assertEqual(report["sha256"], expected_hash)
            self.assertEqual(report["version"], statcraft.__version__)

    def test_smoke_result_diff_tolerates_blas_ulp_noise_and_flags_real_drift(self):
        from statcraft.everyday_smoke import _find_result_diff

        base = {
            "residuals": [-4.8166598914506786e-15, 0.0],
            "cooks_distance": [4.860768862322053e-27, 1.0],
            "lack_of_fit": {"f": 3.700743415417188e-16, "status": "exact_fit"},
            "raw_pairs": [["A", 1.0]],
            "test_failures": {"1": [0], "2": []},
            "flag": False,
        }
        ulp_shifted = {
            "residuals": [1.1e-15, -0.0],
            "cooks_distance": [0.0, 1.0 + 1e-14],
            "lack_of_fit": {"f": 0.0, "status": "exact_fit"},
            "raw_pairs": [("A", 1.0)],
            "test_failures": {1: [0], 2: []},
            "flag": False,
        }
        self.assertIsNone(_find_result_diff(base, ulp_shifted))

        real_drift = {**base, "cooks_distance": [4.860768862322053e-27, 1.0001]}
        diff_num = _find_result_diff(base, real_drift)
        self.assertIsNotNone(diff_num)
        self.assertIn("cooks_distance[1]", diff_num)

        type_drift = {**base, "flag": 0}
        diff_bool = _find_result_diff(base, type_drift)
        self.assertIsNotNone(diff_bool)
        self.assertIn("flag", diff_bool)


if __name__ == "__main__":
    unittest.main()
