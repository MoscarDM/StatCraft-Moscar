"""Verify a built StatCraft executable (or source module) via headless --smoke-verify and SHA-256 reporting."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INIT_PATH = REPO_ROOT / "statcraft" / "__init__.py"
SMOKE_PREFIX = "STATCRAFT_SMOKE_VERIFY="


def read_source_version(init_path: Path = INIT_PATH) -> str:
    """Read __version__ from statcraft/__init__.py without importing GUI modules."""
    text = init_path.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not find __version__ in {init_path}")
    return match.group(1)


def compute_sha256(file_path: Path) -> str:
    """Compute hex SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_smoke_payload(stdout: str) -> dict:
    """Extract the structured STATCRAFT_SMOKE_VERIFY JSON payload from stdout."""
    for line in stdout.splitlines():
        if line.startswith(SMOKE_PREFIX):
            raw = line[len(SMOKE_PREFIX):].strip()
            return json.loads(raw)
    raise RuntimeError("Missing STATCRAFT_SMOKE_VERIFY=... payload in smoke output")


def verify_target(
    exe_path: Path | None = None,
    python_module: bool = False,
    expected_version: str | None = None,
    timeout: int = 60,
    json_out: Path | None = None,
) -> dict:
    """Run --smoke-verify against a built executable or `python -m statcraft` and validate version & SHA-256."""
    if exe_path is not None and python_module:
        raise ValueError("Specify either --exe or --python-module, not both")
    if exe_path is None and not python_module:
        raise ValueError("Specify --exe <path> or --python-module")

    expected = expected_version or read_source_version()
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["STATCRAFT_TESTING"] = "1"

    if exe_path is not None:
        target_path = Path(exe_path).resolve()
        if not target_path.is_file():
            raise FileNotFoundError(f"Executable not found: {target_path}")
        sha256 = compute_sha256(target_path)
        cmd = [str(target_path), "--smoke-verify"]
        target_label = str(target_path)
        cwd = str(target_path.parent)
    else:
        entry_file = REPO_ROOT / "statcraft" / "__main__.py"
        sha256 = compute_sha256(entry_file)
        cmd = [sys.executable, "-m", "statcraft", "--smoke-verify"]
        target_label = f"{sys.executable} -m statcraft"
        cwd = str(REPO_ROOT)
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing_pp}" if existing_pp else str(REPO_ROOT)

    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Smoke verification failed (exit {proc.returncode}) for {target_label}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

    payload = parse_smoke_payload(proc.stdout)
    if payload.get("status") != "ok":
        raise RuntimeError(f"Unexpected smoke status: {payload}")
    bundled_version = payload.get("version")
    if bundled_version != expected:
        raise RuntimeError(
            f"Version mismatch: bundled={bundled_version!r}, expected={expected!r}"
        )

    report = {
        "status": "ok",
        "target": target_label,
        "version": bundled_version,
        "expected_version": expected,
        "sha256": sha256,
        "smoke": payload,
    }

    if json_out is not None:
        out_path = Path(json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify built StatCraft executable via --smoke-verify and SHA-256 reporting."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--exe", type=Path, help="Path to built StatCraft executable")
    group.add_argument(
        "--python-module",
        action="store_true",
        help="Run smoke verification against `python -m statcraft` from source",
    )
    parser.add_argument(
        "--expected-version",
        default=None,
        help="Expected version string (defaults to statcraft/__init__.py __version__)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Subprocess timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write verification report JSON",
    )
    args = parser.parse_args(argv)

    try:
        report = verify_target(
            exe_path=args.exe,
            python_module=args.python_module,
            expected_version=args.expected_version,
            timeout=args.timeout,
            json_out=args.json_out,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Target: {report['target']}")
    print(f"Version: {report['version']} (matches expected {report['expected_version']})")
    print(f"SHA-256: {report['sha256']}")
    print(f"Smoke verify: PASSED (rows={report['smoke'].get('rows')}, mpx_bytes={report['smoke'].get('mpx_bytes')}, xlsx_bytes={report['smoke'].get('xlsx_bytes')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
