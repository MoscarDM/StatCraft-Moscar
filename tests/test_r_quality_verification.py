import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STATCRAFT_TESTING', '1')

from PySide6.QtWidgets import QApplication, QMessageBox

from statcraft.app import Presenter
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.r_verification import build_script, supports, tab_name


class QualityRVerificationTests(unittest.TestCase):
    def verify_r(self, script, expect_pass=True):
        executable = os.environ.get('STATCRAFT_QA_RSCRIPT') or shutil.which('Rscript')
        if not executable:
            self.skipTest('Rscript not available')
        with tempfile.TemporaryDirectory() as directory:
            script_file = Path(directory) / 'verification.R'
            script_file.write_text(script, encoding='utf-8')
            result = subprocess.run(
                [executable, '--vanilla', str(script_file)],
                cwd=directory,
                capture_output=True,
                encoding='utf-8',
                errors='replace',
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            if expect_pass:
                self.assertIn('Verification: PASS', result.stdout)
                self.assertTrue((Path(directory) / 'Rplots.pdf').is_file())
            else:
                self.assertIn('Verification: DIFFERENCES FOUND', result.stdout)
            return result.stdout

    def test_imr_variants_gap_omission_stale_and_mismatch_detection(self):
        # 1. Default AMR with missing value gap, span=3, omission, and outlier
        p = Presenter()
        vals = [10.0, 10.4, None, 10.2, 10.8, 10.1, 10.6, 10.3, 18.0, 10.2, 10.5]
        p.worksheet = Worksheet('IMR_QA', [Column('Reading', 'number', vals)])
        entry = p.imr_chart({
            'variables': [0],
            'options': {'span': 3, 'omit_subgroups': '5', 'k_sigma': 2.5},
        })
        self.assertTrue(supports(entry))
        self.assertEqual(tab_name(entry), 'Verify_IMR.R')
        script = build_script(p, entry)
        self.assertIn('span <- 3L', script)
        self.assertIn('sessionInfo()', script)
        self.verify_r(script, expect_pass=True)

        # 2. MMR and SRMSSD and historical mean/sigma
        entry_mmr = p.imr_chart({
            'variables': [0],
            'options': {'estimation_method': 'mmr', 'unbiasing': True, 'display_lower': False},
        })
        self.verify_r(build_script(p, entry_mmr), expect_pass=True)

        entry_srm = p.imr_chart({
            'variables': [0],
            'options': {'estimation_method': 'srmssd', 'omit_subgroups': '5'},
        })
        self.verify_r(build_script(p, entry_srm), expect_pass=True)

        entry_hist = p.imr_chart({
            'variables': [0],
            'options': {'historical_mean': 10.3, 'historical_sigma': 0.25},
        })
        self.verify_r(build_script(p, entry_hist), expect_pass=True)

        # 3. Altered reference coefficient must be flagged as DIFFERENCES FOUND
        entry['result']['i_center'] += 0.5
        altered_script = build_script(p, entry)
        self.verify_r(altered_script, expect_pass=False)

        # 4. Stale worksheet edit must require rerun
        p.worksheet.columns[0].values[0] = 99.0
        with self.assertRaisesRegex(ValueError, 'Rerun'):
            build_script(p, entry)

    def test_subgroup_xbar_r_and_xbar_s_variants(self):
        groups = [
            [10.0, 10.2, 9.8, 10.0],
            [10.1, 9.9, 10.0],
            [10.0, 10.3, 9.7, 10.1, 9.9],
            [16.0, 17.0],
            [10.2, 9.8, 10.1, 9.9],
        ]
        flat_vals = [v for g in groups for v in g]
        lot_ids = [f'Lot{i + 1}' for i, g in enumerate(groups) for _ in g]

        p = Presenter()
        p.worksheet = Worksheet('SubgroupQA', [
            Column('Diameter', 'number', flat_vals),
            Column('Lot', 'text', lot_ids),
            Column('S1', 'number', [10.0, 10.1, 10.2, 16.0, 10.1]),
            Column('S2', 'number', [10.2, 9.9, 9.8, 17.0, 9.9]),
            Column('S3', 'number', [9.8, None, 10.0, None, 10.0]),
        ])

        # Unequal subgroups via factor_index + omission
        xr_unequal = p.subgroup_control_chart(
            chart_type='xbar_r',
            stacked=True,
            response_index=0,
            factor_index=1,
            options={'k_sigma': 2.5, 'omit_subgroups': [4]},
        )
        self.assertTrue(supports(xr_unequal))
        self.assertEqual(tab_name(xr_unequal), 'Verify_Subgroup.R')
        self.verify_r(build_script(p, xr_unequal), expect_pass=True)

        # Xbar-S with pooled_stdev on unequal subgroups
        xs_pooled = p.subgroup_control_chart(
            chart_type='xbar_s',
            stacked=True,
            response_index=0,
            factor_index=1,
            options={'estimation_method': 'pooled_stdev', 'unbiasing': True},
        )
        self.verify_r(build_script(p, xs_pooled), expect_pass=True)

        # Constant subgroup size
        xr_const = p.subgroup_control_chart(
            chart_type='xbar_r',
            stacked=True,
            response_index=0,
            subgroup_size=3,
        )
        self.verify_r(build_script(p, xr_const), expect_pass=True)

        # Unstacked rows across columns
        xr_rows = p.subgroup_control_chart(
            chart_type='xbar_r',
            stacked=False,
            indices=[2, 3, 4],
        )
        self.verify_r(build_script(p, xr_rows), expect_pass=True)

        # Unsupported single-panel chart_type rejected cleanly
        x_only = p.subgroup_control_chart(
            chart_type='xbar',
            stacked=True,
            response_index=0,
            factor_index=1,
        )
        self.assertFalse(supports(x_only))
        with self.assertRaisesRegex(ValueError, 'Xbar-R and Xbar-S'):
            build_script(p, x_only)

        # Stale rejection
        p.worksheet.columns[0].values[0] = 50.0
        with self.assertRaisesRegex(ValueError, 'Rerun'):
            build_script(p, xr_unequal)

    def test_normal_capability_variants_mpx_reopen_and_ui_menu(self):
        subgroups = [
            [-0.4, -0.1, 0.2, 0.3],
            [-0.2, 0.1, 0.3],
            [-0.5, -0.2, 0.0, 0.2, 0.5],
            [-0.3, 0.0, 0.1, 0.2],
        ]
        flat = [v for g in subgroups for v in g]
        batch = [f'B{i + 1}' for i, g in enumerate(subgroups) for _ in g]

        p = Presenter()
        p.worksheet = Worksheet('CapQA', [
            Column('Offset', 'number', flat),
            Column('Batch', 'text', batch),
            Column('R1', 'number', [10.0, 10.2, 9.9, 10.1, 10.3]),
            Column('R2', 'number', [10.1, 10.0, 10.2, 9.8, 10.0]),
            Column('R3', 'number', [9.9, 10.3, None, 10.0, 10.2]),
        ])

        # Rational subgroups (pooled) + Target=0.0
        cap_pooled = p.normal_capability(settings={
            'single_column': True,
            'column_name': 'Offset',
            'subgroup_spec': 'Batch',
            'lsl': -3.0,
            'usl': 3.0,
            'options': {'target': 0.0, 'estimate_method_gt1': 'pooled', 'unbiased_within': True},
        })
        self.assertTrue(supports(cap_pooled))
        self.assertEqual(tab_name(cap_pooled), 'Verify_Capability.R')
        self.verify_r(build_script(p, cap_pooled), expect_pass=True)

        # Rational subgroups (rbar and sbar)
        for gt1 in ('rbar', 'sbar'):
            cap_var = p.normal_capability(settings={
                'single_column': True,
                'column_name': 'Offset',
                'subgroup_spec': 'Batch',
                'lsl': -3.0,
                'usl': 3.0,
                'options': {'estimate_method_gt1': gt1, 'unbiased_within': True, 'display_unit': 'percent'},
            })
            self.verify_r(build_script(p, cap_var), expect_pass=True)

        # Individuals (subgroup_spec=1) with one-sided spec & AMR
        cap_ind = p.normal_capability(settings={
            'single_column': True,
            'column_name': 'Offset',
            'subgroup_spec': 1,
            'lsl': None,
            'usl': 2.5,
            'options': {'estimate_method_eq1': 'amr', 'moving_range_len': 3, 'unbiased_overall': True},
        })
        self.verify_r(build_script(p, cap_ind), expect_pass=True)

        # Across rows of columns
        cap_across = p.normal_capability(settings={
            'single_column': False,
            'cols_across': ['R1', 'R2', 'R3'],
            'lsl': 9.0,
            'usl': 11.0,
            'options': {'target': 10.0, 'estimate_method_gt1': 'pooled'},
        })
        self.verify_r(build_script(p, cap_across), expect_pass=True)

        # Legacy positional form
        cap_legacy = p.normal_capability(index=0, lsl=-3.0, usl=3.0, target=0.0)
        self.verify_r(build_script(p, cap_legacy), expect_pass=True)

        # Between/Within mode rejected clearly
        cap_bw = p.normal_capability(settings={
            'single_column': True,
            'column_name': 'Offset',
            'subgroup_spec': 'Batch',
            'analysis_mode': 'between_within',
            'lsl': -3.0,
            'usl': 3.0,
        })
        self.assertFalse(supports(cap_bw))
        with self.assertRaisesRegex(ValueError, 'Between/Within'):
            build_script(p, cap_bw)

        # MPX save/reopen preserves R verification + UI menu opens Verify_Capability.R tab
        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / 'cap_r.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            saved_cap = next(e for e in reopened.history if e['entry_id'] == cap_pooled['entry_id'])
            self.verify_r(build_script(reopened, saved_cap), expect_pass=True)

            app = QApplication.instance() or QApplication([])
            win = ModernWindow(reopened)
            try:
                action = next(
                    a for a in win.build_output_context_menu(saved_cap).actions()
                    if a.text().startswith('Verify in R Workbench')
                )
                action.trigger()
                idx = win.r_workbench.editor_tabs.currentIndex()
                self.assertEqual(win.r_workbench.editor_tabs.tabText(idx), 'Verify_Capability.R')
                self.assertIn('Normal Capability', win.r_workbench.editor.toPlainText())

                # Unsupported Between/Within triggers friendly info message without crash
                saved_bw = next(e for e in reopened.history if e['entry_id'] == cap_bw['entry_id'])
                bw_action = next(
                    a for a in win.build_output_context_menu(saved_bw).actions()
                    if a.text().startswith('Verify in R Workbench')
                )
                with patch.object(QMessageBox, 'information') as info_mock:
                    bw_action.trigger()
                self.assertIn('Between/Within', info_mock.call_args.args[2])
            finally:
                reopened.dirty = False
                win.close()
                win.deleteLater()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
