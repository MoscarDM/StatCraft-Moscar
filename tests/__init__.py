"""Test package setup with safe Qt top-level widget cleanup on exit."""
import atexit
import gc
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

try:
    from PySide6.QtCore import QCoreApplication, QEvent  # noqa: F401
    from PySide6.QtWidgets import QApplication  # noqa: F401
    _HAS_PYSIDE6 = True
except Exception:
    _HAS_PYSIDE6 = False


def _cleanup_qt_widgets() -> None:
    if not _HAS_PYSIDE6:
        return
    app = QApplication.instance()
    if app is None:
        return
    for widget in list(app.topLevelWidgets()):
        try:
            widget.close()
            widget.deleteLater()
        except Exception:
            pass
    try:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        cb = app.clipboard()
        if cb is not None:
            cb.clear()
        gc.collect()
    except Exception:
        pass


atexit.register(_cleanup_qt_widgets)
