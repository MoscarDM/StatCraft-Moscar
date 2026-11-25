"""Tests for Subgroup Sensitivity Analysis and Normal Capability Traceability & Batch Replay."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STATCRAFT_TESTING', '1')

from openpyxl import load_workbook
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from statcraft.app import Presenter, format_entry
from statcraft.capability_workflows import (
    ApproveCapabilityReplayDialog,
    CapabilityReplayDialog,
    CapabilityTraceDialog,
    approve as approve_capability,
    capability_trace_summary,
    comparison_text as capability_comparison_text,
    preview as preview_capability,
    replay as replay_capability,
)
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.quality_sensitivity import SubgroupSensitivityDialog, comparison_text as sensitivity_comparison_text
from statcraft.r_verification import build_script as build_r_script
from statcraft.xlsx_verification import write_verification
from tests.test_xlsx_quality_verification import ExcelFormulaEvaluator


_APP = QApplication.instance() or QApplication([])


def _run_modal_with(win, dlg_cls, trigger_fn, fn, timeout_ms=6000):
    done = [False]
    poll = QTimer(win)
    safety = QTimer(win)
    safety.setSingleShot(True)

    def tick():
        if done[0]:
            poll.stop()
            return
        try:
            active = QApplication.activeModalWidget()
            dlg = active if isinstance(active, dlg_cls) else next(
                (d for d in reversed(win.findChildren(dlg_cls)) if d.isVisible()),
                None,
            )
            if dlg is not None and dlg.isVisible():
                done[0] = True
                poll.stop()
                safety.stop()
                try:
                    fn(dlg)
                finally:
                    if dlg.isVisible():
                        dlg.reject()
                    dlg.deleteLater()
        except RuntimeError:
            done[0] = True
            poll.stop()
            safety.stop()

    def on_timeout():
        done[0] = True
        poll.stop()
        for w in QApplication.topLevelWidgets():
            try:
                if isinstance(w, QDialog) and w.isVisible():
                    w.reject()
            except RuntimeError:
                pass

    poll.timeout.connect(tick)
    poll.start(20)
    safety.timeout.connect(on_timeout)
    safety.start(timeout_ms)
    try:
        trigger_fn()
    finally:
        done[0] = True
        poll.stop()
        safety.stop()
        _APP.processEvents()


def _find_rscript() -> str | None:
    env_path = os.environ.get('STATCRAFT_QA_RSCRIPT')
    if env_path and Path(env_path).exists():
        return env_path
    which = shutil.which('Rscript')
    if which:
        return which
    default_r = Path(r'C:\Program Files\R\R-4.6.1\bin\x64\Rscript.exe')
    return str(default_r) if default_r.exists() else None


class VariablesQualityWorkflowsTests(unittest.TestCase):
    def test_subgroup_sensitivity_period_and_exclusion_mpx_and_verifiers(self):
        p = Presenter()
        # Lot1-Lot3 stable around 10.0; Lot4 has shifted mean & huge range
        p.worksheet = Worksheet('SubgroupSens', [
            Column('Diam', 'number', [
                10.0, 10.1, 9.9,
                10.0, 10.2, 9.8,
                10.1, 9.9, 10.0,
                14.5, 16.0, 11.0,
                10.0, 10.0, 10.1,
            ]),
            Column('Lot', 'text', [
                'L1', 'L1', 'L1',
                'L2', 'L2', 'L2',
                'L3', 'L3', 'L3',
                'L4', 'L4', 'L4',
                'L5', 'L5', 'L5',
            ]),
        ])
        xr = p.subgroup_control_chart(chart_type='xbar_r', stacked=True, response_index=0, factor_index=1)
        xs = p.subgroup_control_chart(chart_type='xbar_s', stacked=True, response_index=0, factor_index=1)

        with self.assertRaises(ValueError):
            p.subgroup_sensitivity(xr, 'baseline_period', start_subgroup=3, end_subgroup=2)
        with self.assertRaises(ValueError):
            p.subgroup_sensitivity(xr, 'baseline_period', start_subgroup=1, end_subgroup=5)

        period_branch = p.subgroup_sensitivity(xr, 'baseline_period', start_subgroup=1, end_subgroup=3)
        self.assertEqual(period_branch['result']['sensitivity']['kind'], 'subgroup_baseline_period')
        self.assertLess(period_branch['result']['within_stdev'], xr['result']['within_stdev'])
        self.assertIn('Sensitivity Analysis Comparison', format_entry(period_branch))

        excl_branch = p.subgroup_sensitivity(
            xr,
            'exclusion',
            batch_col_index=1,
            batch_values=['L4'],
            treatment='exclude_rows',
        )
        self.assertEqual(excl_branch['result']['sensitivity']['kind'], 'subgroup_exclusion')
        self.assertEqual(excl_branch['result']['k_subgroups'], 4)
        self.assertEqual(excl_branch['result']['estimation_trace']['exclude_rows'], [10, 11, 12])
        conclusions = {c['criterion']: c['status'] for c in excl_branch['result']['sensitivity']['conclusions']}
        self.assertEqual(conclusions['Overall Control Status'], 'Changed')

        omit_branch = p.subgroup_sensitivity(
            xs,
            'exclusion',
            batch_col_index=1,
            batch_values=['L4'],
            treatment='omit_estimation',
        )
        self.assertEqual(omit_branch['result']['k_subgroups'], 5)
        self.assertEqual(omit_branch['result']['options']['omit_subgroups'], [4])
        self.assertIn('Total Signals:', sensitivity_comparison_text(omit_branch['result']))

        # Excluded-row branch must verify identically in Excel and R Workbench!
        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = write_verification(Path(tmp) / 'xr_excl.xlsx', p, excl_branch)
            wb = load_workbook(xlsx_path, data_only=False)
            ev = ExcelFormulaEvaluator(wb)
            self.assertEqual(ev.cell('Verification', 'B6'), 'PASS')
            self.assertEqual(ev.cell('Verification', 'B7'), 'Valid')
            rscript = _find_rscript()
            if rscript:
                r_code = build_r_script(p, excl_branch)
                r_file = Path(tmp) / 'verify_sg_excl.R'
                r_file.write_text(r_code, encoding='utf-8')
                proc = subprocess.run([rscript, '--vanilla', str(r_file)], cwd=tmp, capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn('Verification: PASS', proc.stdout)

            mpx_path = Path(tmp) / 'sg_sens.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            self.assertTrue(any(
                e.get('result', {}).get('sensitivity', {}).get('kind') == 'subgroup_exclusion'
                for e in reopened.history
            ))

    def test_subgroup_sensitivity_dialog_validation_cancel_and_accept(self):
        p = Presenter()
        p.worksheet = Worksheet('SubgroupSensUI', [
            Column('Y', 'number', [10.0, 10.1, 9.9, 10.0, 10.2, 9.8, 15.0, 18.0, 12.0, 10.0, 10.1, 9.9]),
            Column('Batch', 'text', ['B1', 'B1', 'B1', 'B2', 'B2', 'B2', 'B3', 'B3', 'B3', 'B4', 'B4', 'B4']),
        ])
        xr = p.subgroup_control_chart(chart_type='xbar_r', stacked=True, response_index=0, factor_index=1)
        win = ModernWindow(p)
        try:
            menu = win.build_output_context_menu(xr)
            act = next(a for a in menu.actions() if a.text() == 'Sensitivity Analysis…')
            before_count = len(p.history)

            # Cancel path leaves history untouched
            _run_modal_with(win, SubgroupSensitivityDialog, act.trigger, lambda dlg: dlg.reject())
            self.assertEqual(len(p.history), before_count)

            # Invalid inverted period -> inline error -> fix -> accept
            errors = []

            def accept_dlg(dlg):
                dlg.start_spin.setValue(3)
                dlg.end_spin.setValue(1)
                dlg.validate()
                errors.append(dlg.error.text())
                dlg.start_spin.setValue(1)
                dlg.end_spin.setValue(2)
                dlg.validate()

            _run_modal_with(win, SubgroupSensitivityDialog, act.trigger, accept_dlg)
            self.assertTrue(errors and 'Baseline subgroup period' in errors[0])
            self.assertEqual(len(p.history), before_count + 1)
            self.assertEqual(p.history[-1]['result']['sensitivity']['kind'], 'subgroup_baseline_period')
        finally:
            p.dirty = False
            p._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()

    def test_capability_traceability_single_across_exclude_and_dialog(self):
        p = Presenter()
        p.worksheet = Worksheet('CapTrace', [
            Column('Width', 'number', [10.0, 10.2, None, 8.5, 11.4, 10.1, 10.0, 9.9], metadata={'units': 'mm'}),
            Column('Lot', 'text', ['L1', 'L1', 'L1', 'L2', 'L2', 'L2', 'L3', 'L3']),
            Column('R1', 'number', [10.0, 10.2, 8.6, 10.1]),
            Column('R2', 'number', [10.1, None, 10.0, 10.2]),
        ])
        cap_col = p.normal_capability(settings={
            'single_column': True,
            'column_name': 'Width',
            'subgroup_spec': 'Lot',
            'lsl': 9.0,
            'usl': 11.0,
            'exclude_rows': '8',
            'options': {'target': 10.0, 'estimate_method_gt1': 'sbar', 'unbiased_within': True},
        })
        cap_across = p.normal_capability(settings={
            'single_column': False,
            'cols_across': ['R1', 'R2'],
            'lsl': 9.0,
            'usl': 11.0,
            'options': {'target': 10.0, 'estimate_method_gt1': 'rbar'},
        })

        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / 'cap_trace.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)

        saved_col = next(e for e in reopened.history if e['entry_id'] == cap_col['entry_id'])
        saved_across = next(e for e in reopened.history if e['entry_id'] == cap_across['entry_id'])
        reopened.worksheet.columns[0].values[0] = 999.0
        self.assertTrue(reopened.result_stale(saved_col))

        ov = capability_trace_summary(saved_col['result'], focus='overview')
        self.assertFalse(ov['legacy_trace_missing'])
        self.assertEqual(ov['sample_n'], 6)
        self.assertEqual(ov['excluded_rows'], [8])
        self.assertEqual(ov['missing_rows'], [3])
        self.assertEqual(ov['oos_below_rows'], [[4, 8.5]])
        self.assertEqual(ov['oos_above_rows'], [[5, 11.4]])
        self.assertEqual(ov['estimation']['within_method'], 'sbar')

        oos = capability_trace_summary(saved_col['result'], focus='oos')
        self.assertEqual([r[0] for r in oos['rows']], [4, 5])

        sg2 = capability_trace_summary(saved_col['result'], focus='subgroup', subgroup=2)
        self.assertEqual([r[0] for r in sg2['rows']], [4, 5, 6])

        across_ov = capability_trace_summary(saved_across['result'], focus='overview')
        self.assertEqual(across_ov['arrangement'], 'cols_across')
        self.assertEqual(across_ov['missing_rows'], [2])
        self.assertEqual(len(across_ov['rows']), 7)

        win = ModernWindow(reopened)
        seen_labels = []
        texts = []
        try:
            menu = win.build_output_context_menu(saved_col)
            act = next(a for a in menu.actions() if a.text() == 'Trace Capability Result…')

            def inspect_dlg(dlg):
                seen_labels.extend(lbl.text() for lbl in dlg.findChildren(QLabel))
                dlg.focus.setCurrentIndex(1)
                texts.append(dlg.details.toPlainText())

            _run_modal_with(win, CapabilityTraceDialog, act.trigger, inspect_dlg)
            self.assertIn('The current worksheet differs from the saved analysis.', seen_labels)
            self.assertTrue(texts and 'Row 4' in texts[0] and '< LSL' in texts[0])
        finally:
            p.dirty = False
            p._results_dirty = False
            reopened.dirty = False
            reopened._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()

    def test_capability_replay_single_and_across_validation_reapproval_and_dialog(self):
        p = Presenter()
        p.worksheet = Worksheet('CapBase', [
            Column('Meas', 'number', [10.0, 10.1, 9.9, 10.0, 10.1, 9.95, 10.05, 9.98, 10.02, 10.0], metadata={'units': 'mm'}),
            Column('Lot', 'text', ['A', 'A', 'B', 'B', 'C', 'C', 'D', 'D', 'E', 'E']),
            Column('S1', 'number', [10.0, 10.1, 9.9, 10.0, 10.05], metadata={'units': 'mm'}),
            Column('S2', 'number', [10.02, 9.98, 10.01, 9.99, 10.0], metadata={'units': 'mm'}),
        ])
        base = p.normal_capability(settings={
            'single_column': True,
            'column_name': 'Meas',
            'subgroup_spec': 'Lot',
            'lsl': 9.0,
            'usl': 11.0,
            'options': {'target': 10.0, 'estimate_method_gt1': 'pooled', 'unbiased_within': True},
        })
        base_across = p.normal_capability(settings={
            'single_column': False,
            'cols_across': ['S1', 'S2'],
            'lsl': 9.0,
            'usl': 11.0,
            'options': {'target': 10.0},
        })

        with self.assertRaises(ValueError):
            approve_capability(p, base, min_ppk=None, min_cpk=None, max_ppm_total=None)

        tpl = approve_capability(p, base, min_ppk=1.33)
        tpl_across = approve_capability(p, base_across, min_ppk=1.33, max_ppm_total=100.0)

        # New batch with mismatched units must fail preview
        bad_sheet = p.add_worksheet('BadUnits')
        bad_sheet.columns = [
            Column('DiamIn', 'number', [10.0, 10.1, 9.9, 10.0], metadata={'units': 'in'}),
            Column('Batch', 'text', ['B1', 'B1', 'B2', 'B2']),
        ]
        with self.assertRaises(ValueError):
            preview_capability(bad_sheet, tpl, column_index=0, subgroup_col_index=1)

        # Passing batch (tight process)
        pass_sheet = p.add_worksheet('PassBatch')
        pass_sheet.columns = [
            Column('BatchMeas', 'number', [10.0, 10.02, 9.98, 10.01, 9.99, 10.0], metadata={'units': 'mm'}),
            Column('BatchLot', 'text', ['B1', 'B1', 'B2', 'B2', 'B3', 'B3']),
            Column('B1', 'number', [10.0, 10.01, 9.99, 10.0], metadata={'units': 'mm'}),
            Column('B2', 'number', [10.0, 9.99, 10.01, 10.0], metadata={'units': 'mm'}),
        ]
        p.worksheet = pass_sheet
        replayed_pass = replay_capability(p, tpl, column_index=0, subgroup_col_index=1)
        self.assertEqual(replayed_pass['result']['workflow_comparison']['status'], 'Pass')
        self.assertIn('Acceptance: Pass', format_entry(replayed_pass))

        replayed_across = replay_capability(p, tpl_across, cols_across_indices=[2, 3])
        self.assertEqual(replayed_across['result']['workflow_comparison']['status'], 'Pass')

        # Re-approval on a replayed result preserves its previous workflow_comparison
        approve_capability(p, replayed_pass, min_ppk=2.0)
        self.assertEqual(replayed_pass['result']['workflow_comparison']['baseline']['worksheet'], 'CapBase')
        self.assertEqual(replayed_pass['result']['workflow_comparison']['criteria']['min_ppk'], 1.33)

        # Failing batch (wide spread)
        fail_sheet = p.add_worksheet('FailBatch')
        fail_sheet.columns = [
            Column('BatchMeas', 'number', [8.0, 12.0, 8.5, 11.5, 9.0, 11.0], metadata={'units': 'mm'}),
            Column('BatchLot', 'text', ['B1', 'B1', 'B2', 'B2', 'B3', 'B3']),
        ]
        p.worksheet = fail_sheet
        win = ModernWindow(p)
        try:
            menu = win.build_output_context_menu(base)
            replay_act = next(a for a in menu.actions() if a.text() == 'Replay Capability on Current Worksheet…')

            # Cancel leaves history count unchanged
            before_n = len(p.history)

            _run_modal_with(win, CapabilityReplayDialog, replay_act.trigger, lambda dlg: dlg.reject())
            self.assertEqual(len(p.history), before_n)

            # Accept dialog on FailBatch auto-selects distinct BatchLot column and produces Fail verdict
            dlg_checks = {}

            def accept_replay(dlg):
                dlg_checks['sub_idx'] = dlg.sub_combo.currentData()
                dlg_checks['error_before'] = dlg.error.text()
                dlg.accept_replay()

            _run_modal_with(win, CapabilityReplayDialog, replay_act.trigger, accept_replay)
            self.assertEqual(dlg_checks.get('sub_idx'), 1)
            self.assertEqual(dlg_checks.get('error_before'), '')
            self.assertEqual(len(p.history), before_n + 1)
            replayed_fail = p.history[-1]
            self.assertEqual(replayed_fail['result']['workflow_comparison']['status'], 'Fail')
            self.assertIn('Acceptance: Fail', capability_comparison_text(replayed_fail['result']))

            with tempfile.TemporaryDirectory() as tmp:
                mpx_path = Path(tmp) / 'cap_replay.mpx'
                p.save(mpx_path)
                reopened = Presenter()
                reopened.load(mpx_path)
                self.assertTrue(any(
                    e.get('result', {}).get('analysis') == 'capability'
                    and e.get('result', {}).get('workflow_comparison', {}).get('status') == 'Fail'
                    for e in reopened.history
                ))
        finally:
            p.dirty = False
            p._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()


if __name__ == '__main__':
    unittest.main()
