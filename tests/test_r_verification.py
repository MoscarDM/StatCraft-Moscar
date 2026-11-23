import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from statcraft.app import Presenter
from statcraft.doe import create_factorial
from statcraft.model import Column, Worksheet
from statcraft.r_verification import build_script


class RVerificationTests(unittest.TestCase):
    def test_saved_numeric_regression_uses_retained_rows_and_rejects_stale_input(self):
        presenter = Presenter()
        presenter.worksheet = Worksheet('Regression', [
            Column('X', 'number', [1, 2, None, 4, 5, 6]),
            Column('Y', 'number', [4, 5, 7, 10, 11, 15]),
        ])
        saved = presenter.multiple_regression(1, [0])
        script = build_script(presenter, saved)
        self.assertIn('worksheet_row <- c(1, 2, 4, 5, 6)', script)
        self.assertIn('sessionInfo()', script)
        self.verify_r(script)
        presenter.worksheet.columns[0].values[0] = 9
        with self.assertRaisesRegex(ValueError, 'Rerun'):
            build_script(presenter, saved)

    def test_replicated_blocked_factorial_preserves_coding_and_selected_terms(self):
        presenter = Presenter()
        sheet = create_factorial([{'name': 'Heat', 'low': 10, 'high': 30},
                                  {'name': 'Time', 'low': 40, 'high': 60}],
                                 replicates=3, randomize=True, seed=73, blocks=3)
        presenter.worksheet = sheet
        measured = [40 + a / 2 + b / 4 + (a * b / 100) + (i % 3) * 0.1
                    for i, (a, b) in enumerate(zip(sheet.columns[4].values, sheet.columns[5].values))]
        measured[2] = None
        sheet.columns.append(Column('Result', 'number', measured))
        entry = presenter.analyze_factorial(6, [4, 5], selected_terms=[[0], [1], [0, 1]], include_blocks=True)
        script = build_script(presenter, entry)
        self.assertIn('Omitted worksheet rows: 3', script)
        self.assertIn('"design seed": 73', script)
        self.assertIn('Heat*Time', script)
        self.verify_r(script)

    def verify_r(self, script):
        executable = os.environ.get('STATCRAFT_QA_RSCRIPT') or shutil.which('Rscript')
        if not executable:
            return
        with tempfile.TemporaryDirectory() as directory:
            script_file = Path(directory) / 'verification.R'
            script_file.write_text(script, encoding='utf-8')
            result = subprocess.run([executable, '--vanilla', str(script_file)], cwd=directory,
                                    capture_output=True, encoding='utf-8', errors='replace', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Verification: PASS', result.stdout)
            self.assertTrue((Path(directory) / 'Rplots.pdf').is_file())
