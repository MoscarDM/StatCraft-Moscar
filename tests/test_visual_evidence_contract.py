import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6 import QtCore
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from scripts.run_visual_qa_batches import (
    isolated_qt_session,
    load_cases_catalog,
    update_ledger,
    validate_capture_image,
)


class VisualEvidenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_01_catalog_covers_all_54_cases_across_batches_a_to_e(self):
        catalog = load_cases_catalog()
        ids = [c["case_id"] for c in catalog]
        self.assertEqual(len(catalog), 54)
        self.assertEqual(len(set(ids)), 54)
        by_batch = {}
        for c in catalog:
            by_batch.setdefault(c["batch"], []).append(c["case_id"])
        self.assertEqual(set(by_batch.keys()), {"A", "B", "C", "D", "E"})
        self.assertEqual(len(by_batch["A"]), 13)  # A01-A05, W01-W08
        self.assertEqual(len(by_batch["B"]), 15)  # V01-V05, G01-G10
        self.assertEqual(len(by_batch["C"]), 11)  # M01-M05, D01-D06
        self.assertEqual(len(by_batch["D"]), 10)  # E01-E05, P01-P05
        self.assertEqual(len(by_batch["E"]), 5)   # S01-S05

    def test_02_blank_or_missing_capture_fails_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            missing = tmp_dir / "missing.png"
            with self.assertRaises(RuntimeError):
                validate_capture_image(missing)

            blank = tmp_dir / "blank.png"
            img = QImage(320, 240, QImage.Format.Format_RGB32)
            img.fill(QColor("#ffffff"))
            img.save(str(blank))
            with self.assertRaises(RuntimeError):
                validate_capture_image(blank)

            rich = tmp_dir / "rich.png"
            p = QPainter(img)
            p.fillRect(20, 20, 120, 80, QColor("#0284c7"))
            p.end()
            img.save(str(rich))
            meta = validate_capture_image(rich)
            self.assertEqual((meta["width"], meta["height"]), (320, 240))
            self.assertGreaterEqual(meta["distinct_sample_colors"], 2)

    def test_03_ledger_retains_all_54_cases_and_pending_visual_review(self):
        catalog = load_cases_catalog()
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "case-ledger.json"
            merged = update_ledger(
                ledger_path,
                catalog,
                {
                    "A01": {
                        "case_id": "A01",
                        "batch": "A",
                        "priority": "P1",
                        "interaction_status": "PASS",
                        "visual_status": "PENDING_REVIEW",
                    }
                },
            )
            self.assertEqual(len(merged), 54)
            by_id = {row["case_id"]: row for row in merged}
            self.assertEqual(by_id["A01"]["interaction_status"], "PASS")
            self.assertEqual(by_id["A01"]["visual_status"], "PENDING_REVIEW")
            self.assertEqual(by_id["S05"]["interaction_status"], "NOT RUN")
            self.assertEqual(len(json.loads(ledger_path.read_text(encoding="utf-8"))), 54)

    def test_04_isolated_session_restores_qsettings_and_sandbox_scope(self):
        from statcraft import modern_app, settings_scope

        orig_qt = QtCore.QSettings
        orig_mod = modern_app.QSettings
        orig_scope = settings_scope._sandbox_workspace
        with tempfile.TemporaryDirectory() as tmp:
            with isolated_qt_session(Path(tmp)) as (_app, _make_win, iso_dir, ini_path):
                s = modern_app.QSettings("StatCraft", "Desktop")
                self.assertEqual(Path(s.fileName()), ini_path)
                self.assertEqual(settings_scope._sandbox_workspace, iso_dir)
        self.assertIs(QtCore.QSettings, orig_qt)
        self.assertIs(modern_app.QSettings, orig_mod)
        self.assertIs(settings_scope._sandbox_workspace, orig_scope)


if __name__ == "__main__":
    unittest.main()
