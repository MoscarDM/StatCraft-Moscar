"""CI unittest discovery runner with GitHub Actions failure annotations and safe Qt teardown exit."""
from __future__ import annotations

import ctypes
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _escape_gh(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("STATCRAFT_TESTING", "1")

    import tests  # noqa: F401 - ensures package path/env initialization

    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=str(REPO_ROOT))
    result = unittest.TextTestRunner(verbosity=1).run(suite)

    if os.environ.get("GITHUB_ACTIONS") == "true" and not result.wasSuccessful():
        for test_case, tb_text in (result.errors + result.failures)[:15]:
            title = _escape_gh(test_case.id())
            body = _escape_gh(tb_text.strip()[-1500:])
            print(f"::error title={title}::{body}", flush=True)

    sys.stdout.flush()
    sys.stderr.flush()
    code = 0 if result.wasSuccessful() else 1

    if os.name == "nt":
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k32.TerminateProcess(k32.GetCurrentProcess(), code)
    os._exit(code)


if __name__ == "__main__":
    raise SystemExit(main())
