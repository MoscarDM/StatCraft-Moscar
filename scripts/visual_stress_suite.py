"""Automated GUI visual stress-testing harness for StatCraft.

Usage:
    python scripts/visual_stress_suite.py --out-dir <dir> [--quick] [--exe <path>]

Runs 5 real-user stress scenarios against ``ModernWindow`` using a real Qt
event loop, captures PNG screenshots of every state, and emits ``manifest.json``
with per-scenario timings, unhandled-exception count, and screenshot paths.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DEPS = _ROOT.parent / "statcraft-build-deps"
if _DEPS.exists() and str(_DEPS) not in sys.path:
    sys.path.insert(0, str(_DEPS))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6 import QtCore
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog


def _pump(app: QApplication, ms: int = 30) -> None:
    """Process pending Qt events and allow scheduled layout/paint passes."""
    QTest.qWait(ms)
    app.processEvents()


def _grab_widget(widget, path: Path) -> str:
    """Capture a widget pixmap to ``path`` and return its string path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pix = widget.grab()
    pix.save(str(path))
    return str(path)


def _scenario_large_dataset(win, app: QApplication, out_dir: Path, quick: bool) -> dict:
    """Scenario 1: Large dataset load, rapid scroll, sort, autofill, and conditional formatting."""
    from statcraft.model import Column, Worksheet

    n_rows = 10_000 if quick else 100_000
    n_cols = 10 if quick else 20
    rng = np.random.default_rng(42)

    cols = [
        Column(
            "Measurement_1",
            kind="number",
            values=(10.0 + rng.normal(0.0, 0.45, n_rows)).round(4).tolist(),
        ),
        Column(
            "Batch",
            kind="text",
            values=[f"Batch-{(i % 5) + 1}" for i in range(n_rows)],
        ),
    ]
    for c in range(2, n_cols):
        cols.append(
            Column(
                f"Metric_{c + 1}",
                kind="number",
                values=(50.0 + c * 2.0 + rng.normal(0.0, 1.5, n_rows)).round(3).tolist(),
            )
        )

    ws = Worksheet(f"Stress_{n_rows}x{n_cols}", cols)
    win.presenter.worksheet = ws
    win.refresh()
    _pump(app, 40)

    vbar = win.table.verticalScrollBar()
    for pos in (vbar.maximum() // 2, vbar.maximum(), 0):
        vbar.setValue(pos)
        _pump(app, 20)

    win.presenter.sort_columns([0, 1], by_index=0, descending=True)
    win.presenter.autofill_column(0, 0, 5, 25)
    win.presenter.apply_conditional_formatting(0, "out_of_control", color="#f8d7da")
    win.presenter.apply_conditional_formatting(1, "in_list", param1="Batch-1, Batch-2", color="#d1fae5")
    win.refresh()
    _pump(app, 40)

    shot = _grab_widget(win, out_dir / "01_large_worksheet.png")
    return {"rows": n_rows, "cols": n_cols, "screenshot": shot}


def _scenario_dark_and_resize(win, app: QApplication, out_dir: Path, _quick: bool) -> dict:
    """Scenario 2: Light <-> Dark mode toggle, Consolas 11 data font, and 1920x1080 -> 1024x700 resize."""
    win.set_dark_mode(True)
    _pump(app, 30)
    win.set_dark_mode(False)
    _pump(app, 30)
    win.set_dark_mode(True)
    _pump(app, 30)

    win._apply_data_font(QFont("Consolas", 11))
    _pump(app, 25)

    win.resize(1920, 1080)
    _pump(app, 35)
    win.resize(1024, 700)
    _pump(app, 45)

    shot = _grab_widget(win, out_dir / "02_dark_compact_layout.png")
    win.resize(1366, 860)
    win.set_dark_mode(False)
    _pump(app, 30)
    return {"screenshot": shot}


def _scenario_charts_and_tabs(win, app: QApplication, out_dir: Path, _quick: bool) -> dict:
    """Scenario 3: I-MR, Sixpack, Boxplot, Scatter, tab switching, and close_current_graph()."""
    from statcraft.model import Column, Worksheet

    rng = np.random.default_rng(7)
    n = 120
    x = np.linspace(1.0, 20.0, n)
    y = 10.0 + 0.15 * np.sin(x) + rng.normal(0.0, 0.35, n)
    z = 2.0 * y + rng.normal(0.0, 0.6, n)

    ws = Worksheet(
        "Charts_Stress",
        [
            Column("Diameter", kind="number", values=y.round(4).tolist()),
            Column("Shift", kind="text", values=[f"S{(i % 3) + 1}" for i in range(n)]),
            Column("Strength", kind="number", values=z.round(4).tolist()),
        ],
    )
    win.presenter.worksheet = ws
    win.refresh()
    _pump(app, 30)

    entries = [
        win.presenter.imr_chart({"variables": [0], "options": {}}),
        win.presenter.normal_sixpack(
            {"single_column": True, "column_name": 0, "subgroup_spec": 5, "lsl": 8.5, "usl": 11.5}
        ),
        win.presenter.boxplot_graphs([0], variant="one"),
        win.presenter.scatter_plot(0, 2, mode="simple"),
    ]
    for entry in entries:
        if entry:
            win.show_result(entry)
            _pump(app, 30)

    ws_tabs = getattr(getattr(win, "_workspace", None), "tabs", None)
    tab_count = ws_tabs.count() if ws_tabs is not None else 0
    for idx in range(tab_count):
        ws_tabs.setCurrentIndex(idx)
        _pump(app, 20)

    win.close_current_graph()
    _pump(app, 35)

    shot = _grab_widget(win, out_dir / "03_charts_and_tabs.png")
    return {"tabs_opened": tab_count, "screenshot": shot}


def _open_and_cancel_modal(app: QApplication, opener, capture_path: Path | None = None) -> None:
    """Invoke a modal dialog opener and dismiss it automatically via QTimer."""
    captured = {"done": False}

    def _dismiss():
        modal = QApplication.activeModalWidget()
        if isinstance(modal, QDialog):
            if capture_path is not None and not captured["done"]:
                _grab_widget(modal, capture_path)
                captured["done"] = True
            modal.reject()
            return
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible():
                if capture_path is not None and not captured["done"]:
                    _grab_widget(w, capture_path)
                    captured["done"] = True
                w.reject()

    timer = QTimer()
    timer.setInterval(40)
    timer.timeout.connect(_dismiss)
    timer.start()
    try:
        opener()
        _pump(app, 25)
    finally:
        timer.stop()


def _scenario_dialogs(win, app: QApplication, out_dir: Path, _quick: bool) -> dict:
    """Scenario 4: Modal dialog open/cancel torture + Ctrl+E edit-last-dialog."""
    shot_path = out_dir / "04_dialogs.png"

    _open_and_cancel_modal(app, win.manage_conditional_rules_dialog)
    _open_and_cancel_modal(app, win.hide_unhide_columns_dialog)
    _open_and_cancel_modal(app, win.statguide_dialog, capture_path=shot_path)

    # Exercise Ctrl+E (edit_last_dialog) with a guaranteed modal dismissal timer
    win._last_dialog_action = win.statguide_dialog
    _open_and_cancel_modal(
        app,
        lambda: QTest.keyClick(win, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier),
    )

    if not shot_path.exists() or shot_path.stat().st_size == 0:
        raise RuntimeError('Expected modal dialog screenshot was not captured')
    return {"screenshot": str(shot_path)}


def _scenario_mpx_and_session(win, app: QApplication, out_dir: Path, _quick: bool) -> dict:
    """Scenario 5: Load .mpx project, run MTB > commands, and cycle prev/next history."""
    mpx_fixture = _ROOT / "tests" / "fixtures" / "statcraft-profile-v3.mpx"
    loaded_mpx = False
    if not mpx_fixture.is_file():
        raise FileNotFoundError(f'Required MPX fixture is missing: {mpx_fixture}')
    if mpx_fixture.exists():
        win.presenter.dirty = False
        win.load_path(str(mpx_fixture))
        loaded_mpx = True
        _pump(app, 40)

    if not win.command_line_pane.isVisible():
        win.toggle_command_line()
        _pump(app, 25)

    for cmd in ("INFO", "DESCRIBE C2 C3", "TALLY C4"):
        win.command_editor.setPlainText(cmd)
        win.run_command_line()
        _pump(app, 25)

    win.prev_command()
    _pump(app, 20)
    win.prev_command()
    _pump(app, 20)
    win.next_command()
    _pump(app, 30)

    shot = _grab_widget(win, out_dir / "05_mpx_and_session.png")
    return {"loaded_mpx": loaded_mpx, "screenshot": shot}


def _smoke_check_exe(exe_path: Path) -> dict:
    """Launch a packaged StatCraft.exe briefly to confirm clean startup."""
    if not exe_path.exists():
        raise FileNotFoundError(f"Executable not found: {exe_path}")
    proc = subprocess.Popen([str(exe_path)])
    try:
        time.sleep(2.5)
        exit_code = proc.poll()
        alive = exit_code is None
        return {"exe": str(exe_path), "alive_after_launch": alive, "exit_code": exit_code}
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def run_suite(out_dir: Path, quick: bool = False, exe_path: Path | None = None) -> dict:
    """Execute all 5 visual stress scenarios and write ``manifest.json``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    unhandled: list[str] = []
    orig_excepthook = sys.excepthook

    def _capture_excepthook(exc_type, exc_value, exc_tb):
        unhandled.append("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        orig_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _capture_excepthook
    original_settings = QtCore.QSettings
    class TestSettings(original_settings):
        def __init__(self, *args, **kwargs):
            if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], str):
                super().__init__(str(out_dir / 'test-settings.ini'), original_settings.Format.IniFormat)
                self.setFallbacksEnabled(False)
            else:
                super().__init__(*args, **kwargs)
    QtCore.QSettings = TestSettings
    from statcraft import settings_scope
    previous_workspace = settings_scope._sandbox_workspace
    settings_aliases = []
    for module in list(sys.modules.values()):
        if getattr(module, '__name__', '').startswith('statcraft') and getattr(module, 'QSettings', None) is original_settings:
            settings_aliases.append((module, original_settings))
            module.QSettings = TestSettings
    win = None
    try:
        app = QApplication.instance() or QApplication([])
        from statcraft.verification_fonts import load_verification_fonts
        load_verification_fonts(app)
        from statcraft.settings_scope import configure_sandbox_process
        configure_sandbox_process(out_dir)
        from statcraft.modern_app import ModernWindow

        win = ModernWindow()
        win.resize(1366, 860)
        win.show()
        _pump(app, 50)

        scenarios_spec = [
            ("01_large_dataset", _scenario_large_dataset),
            ("02_dark_and_resize", _scenario_dark_and_resize),
            ("03_charts_and_tabs", _scenario_charts_and_tabs),
            ("04_dialogs", _scenario_dialogs),
            ("05_mpx_and_session", _scenario_mpx_and_session),
        ]

        results = []
        for name, fn in scenarios_spec:
            t0 = time.perf_counter()
            try:
                details = fn(win, app, out_dir, quick)
                results.append(
                    {
                        "name": name,
                        "status": "ok",
                        "duration_sec": round(time.perf_counter() - t0, 3),
                        **details,
                    }
                )
            except Exception as exc:
                unhandled.append(traceback.format_exc())
                results.append(
                    {
                        "name": name,
                        "status": "error",
                        "error": str(exc),
                        "duration_sec": round(time.perf_counter() - t0, 3),
                    }
                )

        manifest = {
            "visual_review_status": "PENDING",
            "quick": quick,
            "platform": os.environ.get("QT_QPA_PLATFORM", "native"),
            "unhandled_exceptions": len(unhandled),
            "errors": unhandled,
            "scenarios": results,
        }
        if exe_path is not None:
            manifest["exe_smoke"] = _smoke_check_exe(exe_path)

        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        win.presenter.dirty = False
        app.processEvents()
        return manifest
    finally:
        if win is not None:
            win.presenter.dirty = False
            win.presenter._results_dirty = False
            win.close()
            win.deleteLater()
            app.processEvents()
        settings_scope._sandbox_workspace = previous_workspace
        for module in list(sys.modules.values()):
            if getattr(module, '__name__', '').startswith('statcraft') and getattr(module, 'QSettings', None) is TestSettings:
                module.QSettings = original_settings
        for module, original in settings_aliases:
            module.QSettings = original
        QtCore.QSettings = original_settings
        sys.excepthook = orig_excepthook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="StatCraft GUI visual stress suite")
    parser.add_argument("--out-dir", required=True, help="Directory for PNG screenshots and manifest.json")
    parser.add_argument("--quick", action="store_true", help="Use reduced dataset dimensions (10k x 10) for fast CI checks")
    parser.add_argument("--exe", default=None, help="Optional path to StatCraft.exe for live binary smoke check")
    args = parser.parse_args(argv)

    manifest = run_suite(
        out_dir=Path(args.out_dir),
        quick=args.quick,
        exe_path=Path(args.exe) if args.exe else None,
    )
    ok = manifest["unhandled_exceptions"] == 0 and all(s["status"] == "ok" for s in manifest["scenarios"])
    if "exe_smoke" in manifest:
        ok = ok and manifest['exe_smoke']['alive_after_launch']
    return 0 if ok else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k32.TerminateProcess(k32.GetCurrentProcess(), code)
    os._exit(code)
