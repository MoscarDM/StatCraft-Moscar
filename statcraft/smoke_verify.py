"""Headless startup, calculation, MPX roundtrip, and XLSX export smoke verification."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def run_smoke_verify() -> int:
    """Run headless StatCraft smoke verification and emit structured status to stdout."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("STATCRAFT_TESTING", "1")

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from . import __version__
    from .app import Presenter
    from .model import Column, Worksheet
    from .modern_app import ModernWindow
    from .xlsx_export import convert_mpx
    from .xlsx_import import load_xlsx

    with tempfile.TemporaryDirectory(prefix="statcraft-smoke-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            str(tmp_path / "settings"),
        )

        app = QApplication.instance() or QApplication(["StatCraft", "--smoke-verify"])
        presenter = Presenter()
        presenter.worksheet = Worksheet(
            "Smoke",
            [
                Column("X", values=[1.0, 2.0, 3.0, 4.0, 5.0]),
                Column("Y", values=[2.0, 4.0, 6.0, 8.0, 10.0]),
            ],
        )

        window = ModernWindow(presenter)
        try:
            window.show()
            app.processEvents()

            desc = presenter.describe_columns([0, 1])
            window.show_result(desc)
            app.processEvents()

            pix = window.grab()
            if pix.isNull():
                raise RuntimeError("Grabbed offscreen ModernWindow is null")

            mpx_path = tmp_path / "smoke.mpx"
            presenter.save(mpx_path)
            if not mpx_path.exists() or mpx_path.stat().st_size == 0:
                raise RuntimeError("MPX save failed to produce a non-empty file")

            reloaded = Presenter()
            reloaded.load(mpx_path)
            if reloaded.worksheet.row_count != 5:
                raise RuntimeError(
                    f"MPX roundtrip row count mismatch: expected 5, got {reloaded.worksheet.row_count}"
                )
            if reloaded.worksheet.columns[0].values != [1.0, 2.0, 3.0, 4.0, 5.0]:
                raise RuntimeError("MPX roundtrip column values mismatch")

            xlsx_path = tmp_path / "smoke.xlsx"
            convert_mpx(mpx_path, xlsx_path)
            if not xlsx_path.exists() or xlsx_path.stat().st_size == 0:
                raise RuntimeError("XLSX export failed to produce a non-empty file")

            loaded_sheets = load_xlsx(xlsx_path)
            if not loaded_sheets or loaded_sheets[0].row_count != 5:
                raise RuntimeError("XLSX roundtrip verification failed")

            payload = {
                "status": "ok",
                "version": __version__,
                "rows": reloaded.worksheet.row_count,
                "mpx_bytes": mpx_path.stat().st_size,
                "xlsx_bytes": xlsx_path.stat().st_size,
            }
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    print(f"STATCRAFT_SMOKE_VERIFY={json.dumps(payload, sort_keys=True)}", flush=True)
    print(f"StatCraft {__version__} smoke verification passed.", flush=True)
    return 0
