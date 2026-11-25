import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STATCRAFT_TESTING', '1')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from statcraft.app import Presenter, format_entry
from statcraft.capability_chart import CapabilityContainerWidget
from statcraft.capability_nonnormal_chart import NonnormalCapabilityPlotWidget
from statcraft.capability_nonnormal_engine import run_nonnormal_capability
from statcraft.imr_chart import IMRChartWidget
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.quality_sensitivity import (
    CapabilitySensitivityDialog,
    IMRSensitivityDialog,
    comparison_text,
)
from statcraft.r_verification import build_script as build_r_script
from statcraft.xlsx_verification import write_verification


_APP = QApplication.instance() or QApplication([])


class QualitySensitivityTests(unittest.TestCase):
    def _imr_fixture(self):
        # Rows 1..10: tight Phase I around 10.0; rows 11..16: oscillating Phase II inflating full-series limits
        vals = [
            10.0, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 10.1,
            10.8, 9.2, 11.1, 8.9, 11.5, 8.6,
        ]
        lots = ['Phase1'] * 10 + ['Phase2'] * 4 + ['BadBatch', 'BadBatch']
        p = Presenter()
        p.worksheet = Worksheet('IMR_Sens', [
            Column('Thickness', 'number', vals),
            Column('Batch', 'text', lots),
        ])
        baseline = p.imr_chart({'variables': [0], 'options': {}})
        return p, baseline

    def test_imr_baseline_period_sensitivity_and_mpx_roundtrip(self):
        p, baseline = self._imr_fixture()
        orig_center = baseline['result']['i_center']
        orig_sigma = baseline['result']['within_stdev']

        entry = p.imr_sensitivity(baseline, 'baseline_period', start_row=1, end_row=10)
        sens = entry['result']['sensitivity']
        self.assertEqual(sens['kind'], 'imr_baseline_period')
        self.assertLess(sens['scenario_summary']['within_stdev'], orig_sigma)
        self.assertEqual(baseline['result']['i_center'], orig_center)
        self.assertGreater(sens['scenario_summary']['i_signals'], sens['baseline_summary']['i_signals'])
        conclusions = {c['criterion']: c for c in sens['conclusions']}
        self.assertEqual(conclusions['Individuals Signal Rows']['status'], 'Changed')
        self.assertEqual(conclusions['Within Sigma Stability (<=5%)']['status'], 'Changed')

        txt = format_entry(entry)
        self.assertIn('Sensitivity Analysis Comparison', txt)
        self.assertIn('[Changed] Individuals Signal Rows', txt)

        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / 'imr_sens.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            saved = next(e for e in reopened.history if e['entry_id'] == entry['entry_id'])
            self.assertEqual(saved['result']['sensitivity'], sens)
            self.assertIn('Sensitivity Analysis Comparison', format_entry(saved))
            widget = IMRChartWidget(saved)
            widget.resize(780, 620)
            self.assertFalse(widget.grab().isNull())
            rerun = reopened.rerun_result(saved)
            self.assertAlmostEqual(rerun['result']['i_center'], entry['result']['i_center'], places=10)

    def test_imr_flagged_batch_and_row_exclusion_treatments(self):
        p = Presenter()
        vals = [10.0, 10.1, 9.9, 10.2, 18.5, 9.8, 10.0, 10.1, 21.0, 9.9, 10.0, 10.2]
        batches = ['A', 'A', 'A', 'A', 'Quarantine', 'B', 'B', 'B', 'Quarantine', 'B', 'C', 'C']
        p.worksheet = Worksheet('Batch_IMR', [
            Column('Width', 'number', vals),
            Column('Lot', 'text', batches),
        ])
        baseline = p.imr_chart({'variables': [0], 'options': {}})

        # 1. Omit from estimation keeps points plotted (count=12) while tightening limits
        omit_entry = p.imr_sensitivity(
            baseline, 'exclusion', batch_col_index=1, batch_values=['Quarantine'], treatment='omit_estimation',
        )
        self.assertEqual(omit_entry['result']['count'], 12)
        self.assertEqual(omit_entry['result']['omit_subgroups'], [5, 9])
        self.assertLess(omit_entry['result']['within_stdev'], baseline['result']['within_stdev'])
        self.assertIn(5, omit_entry['result']['i_signals'])
        self.assertIn(9, omit_entry['result']['i_signals'])

        # 2. Exclude rows drops points from plot and estimation (count=10)
        excl_entry = p.imr_sensitivity(
            baseline, 'exclusion', batch_col_index=1, batch_values=['Quarantine'],
            exclude_rows_spec='12', treatment='exclude_rows',
        )
        self.assertEqual(excl_entry['result']['count'], 9)
        self.assertEqual(excl_entry['result']['excluded_rows'], [5, 9, 12])
        self.assertEqual(excl_entry['result']['sensitivity']['kind'], 'imr_exclusion')
        self.assertIn('Quarantine', excl_entry['result']['sensitivity']['scenario_description'])

        # R and Excel verification exports also honor exclude_rows on the scenario result
        r_script = build_r_script(p, excl_entry)
        self.assertIn('obs_count <- sum(!is.na(value))', r_script)
        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / 'imr_excl.xlsx'
            write_verification(xlsx_path, p, excl_entry)
            self.assertTrue(xlsx_path.is_file())

            mpx_path = Path(tmp) / 'batch_excl.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            saved = next(e for e in reopened.history if e['entry_id'] == excl_entry['entry_id'])
            rerun = reopened.rerun_result(saved)
            self.assertEqual(rerun['result']['count'], 9)
            self.assertAlmostEqual(rerun['result']['within_stdev'], excl_entry['result']['within_stdev'], places=10)

    def test_capability_distribution_sensitivity_auto_best_and_nonpositive_rejection(self):
        # Right-skewed positive process data inside [0.2, 20.0]
        skewed = [
            0.8, 1.1, 1.3, 1.5, 1.6, 1.8, 2.0, 2.1, 2.4, 2.7,
            3.0, 3.3, 3.8, 4.2, 4.9, 5.8, 7.1, 8.6, 10.4, 12.8,
        ]
        p = Presenter()
        p.worksheet = Worksheet('SkewCap', [Column('CycleTime', 'number', skewed)])
        baseline = p.normal_capability(settings={
            'single_column': True,
            'column_name': 'CycleTime',
            'subgroup_spec': 1,
            'lsl': 0.2,
            'usl': 15.0,
            'options': {'target': 2.5},
        })

        weib_entry = p.capability_sensitivity(baseline, 'distribution', distribution='weibull', ppk_threshold=1.33)
        direct_weib = run_nonnormal_capability(skewed, dist_or_transform='weibull', lsl=0.2, usl=15.0, target=2.5)
        self.assertAlmostEqual(weib_entry['result']['indices']['ppk'], direct_weib['indices']['ppk'], places=10)
        self.assertEqual(weib_entry['result']['sensitivity']['kind'], 'capability_distribution')

        auto_entry = p.capability_sensitivity(baseline, 'distribution', distribution='auto_best', ppk_threshold=1.33)
        fits = auto_entry['result']['sensitivity']['candidate_fits']
        self.assertEqual(len(fits), 5)
        self.assertEqual(auto_entry['result']['method'], fits[0]['distribution'])
        ads = [f['ad_stat'] for f in fits if f['ad_stat'] is not None]
        self.assertEqual(ads, sorted(ads))

        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / 'cap_dist.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            saved = next(e for e in reopened.history if e['entry_id'] == auto_entry['entry_id'])
            self.assertIn('Candidate Distribution Fits', format_entry(saved))
            widget = NonnormalCapabilityPlotWidget(saved)
            widget.resize(780, 560)
            self.assertFalse(widget.grab().isNull())
            rerun = reopened.rerun_result(saved)
            self.assertAlmostEqual(
                rerun['result']['indices']['ppk'],
                auto_entry['result']['indices']['ppk'],
                places=10,
            )

        # Nonpositive observations cannot fit Weibull/Lognormal/Box-Cox and must leave history untouched
        p_neg = Presenter()
        p_neg.worksheet = Worksheet('NegCap', [Column('Offset', 'number', [-1.2, -0.4, 0.0, 0.3, 0.8, 1.1])])
        neg_base = p_neg.normal_capability(settings={
            'single_column': True, 'column_name': 'Offset', 'subgroup_spec': 1, 'lsl': -3.0, 'usl': 3.0,
        })
        hist_len = len(p_neg.history)
        with self.assertRaises(ValueError):
            p_neg.capability_sensitivity(neg_base, 'distribution', distribution='weibull')
        self.assertEqual(len(p_neg.history), hist_len)

    def test_capability_flagged_batch_exclusion_flips_verdict_and_ui_workflows(self):
        good_vals = [10.0, 10.05, 9.95, 10.02, 9.98, 10.01, 9.99, 10.03, 9.97, 10.0, 10.02, 9.98]
        bad_vals = [11.6, 8.4, 11.5, 8.5]
        vals = good_vals + bad_vals
        batches = ['Good'] * len(good_vals) + ['Rework'] * len(bad_vals)

        p = Presenter()
        p.worksheet = Worksheet('CapExcl', [
            Column('Diameter', 'number', vals),
            Column('Lot', 'text', batches),
        ])
        baseline = p.normal_capability(settings={
            'single_column': True,
            'column_name': 'Diameter',
            'subgroup_spec': 1,
            'lsl': 9.0,
            'usl': 11.0,
            'options': {'target': 10.0},
        })
        self.assertLess(baseline['result']['ppk'], 1.33)

        excl_entry = p.capability_sensitivity(
            baseline, 'exclusion', ppk_threshold=1.33, batch_col_index=1, batch_values=['Rework'],
        )
        self.assertEqual(excl_entry['result']['sample_n'], len(good_vals))
        self.assertGreater(excl_entry['result']['ppk'], 1.33)
        conclusions = {c['criterion']: c for c in excl_entry['result']['sensitivity']['conclusions']}
        self.assertEqual(conclusions['Capability Verdict (Ppk >= 1.33)']['status'], 'Changed')
        self.assertEqual(conclusions['Capability Verdict (Ppk >= 1.33)']['scenario'], 'Capable')

        # UI context menu, validation error handling, cancel preservation, and Report rendering
        win = ModernWindow(p)
        try:
            cap_actions = [a.text() for a in win.build_output_context_menu(baseline).actions()]
            self.assertIn('Sensitivity Analysis…', cap_actions)

            p_imr, imr_base = self._imr_fixture()
            win_imr = ModernWindow(p_imr)
            try:
                imr_actions = [a.text() for a in win_imr.build_output_context_menu(imr_base).actions()]
                self.assertIn('Sensitivity Analysis…', imr_actions)

                # Invalid inverted period inside IMRSensitivityDialog keeps dialog open with inline error
                dlg_imr = IMRSensitivityDialog(win_imr, imr_base)
                dlg_imr.start_spin.setValue(10)
                dlg_imr.end_spin.setValue(5)
                hist_before = len(p_imr.history)
                dlg_imr.validate()
                self.assertTrue(bool(dlg_imr.error.text()))
                self.assertEqual(len(p_imr.history), hist_before)
                dlg_imr.reject()
                self.assertEqual(len(p_imr.history), hist_before)

                # Valid baseline period execution updates window Report tab
                dlg_imr2 = IMRSensitivityDialog(win_imr, imr_base)
                dlg_imr2.start_spin.setValue(1)
                dlg_imr2.end_spin.setValue(10)
                dlg_imr2.validate()
                self.assertIsNotNone(dlg_imr2.entry)
                self.assertEqual(win_imr.result_tabs.tabText(win_imr.result_tabs.currentIndex()), 'Report')
            finally:
                p_imr.dirty = False
                p_imr._results_dirty = False
                win_imr.close()
                win_imr.deleteLater()

            # CapabilitySensitivityDialog empty exclusion -> inline error; valid check -> new entry + chart
            dlg_cap = CapabilitySensitivityDialog(win, baseline)
            dlg_cap.mode_combo.setCurrentIndex(1)
            hist_before = len(p.history)
            dlg_cap.validate()
            self.assertIn('Select at least one', dlg_cap.error.text())
            self.assertEqual(len(p.history), hist_before)

            # Check 'Rework' in batch list and validate
            dlg_cap.exclusion_controls.batch_col_combo.setCurrentIndex(2)
            for idx in range(dlg_cap.exclusion_controls.batch_vals_list.count()):
                item = dlg_cap.exclusion_controls.batch_vals_list.item(idx)
                if item.text() == 'Rework':
                    item.setCheckState(Qt.CheckState.Checked)
            dlg_cap.validate()
            self.assertIsNotNone(dlg_cap.entry)
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), 'Report')

            # Between/Within mode is NOT offered Sensitivity Analysis…
            bw_entry = p.normal_capability(settings={
                'single_column': True,
                'column_name': 'Diameter',
                'subgroup_spec': 'Lot',
                'analysis_mode': 'between_within',
                'lsl': 9.0,
                'usl': 11.0,
            })
            bw_actions = [a.text() for a in win.build_output_context_menu(bw_entry).actions()]
            self.assertNotIn('Sensitivity Analysis…', bw_actions)

            # Stale baseline triggers friendly QMessageBox without crashing
            p.worksheet.columns[0].values[0] = 9.5
            with patch.object(QMessageBox, 'information') as info:
                win.capability_sensitivity_dialog(baseline)
            self.assertIn('Rerun', info.call_args.args[2])

            with tempfile.TemporaryDirectory() as tmp:
                mpx_path = Path(tmp) / 'cap_excl.mpx'
                p.save(mpx_path)
                reopened = Presenter()
                reopened.load(mpx_path)
                saved = next(e for e in reopened.history if e['entry_id'] == excl_entry['entry_id'])
                widget = CapabilityContainerWidget(saved)
                widget.resize(780, 560)
                self.assertFalse(widget.grab().isNull())
                rerun = reopened.rerun_result(saved)
                self.assertEqual(rerun['result']['sample_n'], len(good_vals))
        finally:
            p.dirty = False
            p._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()


if __name__ == '__main__':
    unittest.main()
