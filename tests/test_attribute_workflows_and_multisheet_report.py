"""Tests for multi-worksheet Report/R-Translator resolution and Attribute Control Chart decision workflows."""
import copy
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STATCRAFT_TESTING', '1')

from openpyxl import load_workbook
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QToolButton

from statcraft.app import Presenter, format_entry
from statcraft.attribute_workflows import (
    ApproveAttributeReplayDialog,
    AttributeInvestigationDialog,
    AttributeReplayDialog,
    AttributeTraceDialog,
    approve as approve_attribute,
    comparison_text as attribute_comparison_text,
    point_trace as attribute_point_trace,
    preview as preview_attribute,
    replay as replay_attribute,
)
from statcraft.connect_hub import ConnectBridgeWidget
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.quality_sensitivity import (
    AttributeSensitivityDialog,
    comparison_text as sensitivity_comparison_text,
)
from statcraft.r_verification import build_script as build_r_script
from statcraft.xlsx_verification import write_verification
from tests.test_attribute_and_gage_verification import ExtendedExcelFormulaEvaluator


_APP = QApplication.instance() or QApplication([])


def _find_rscript() -> str | None:
    env_path = os.environ.get('STATCRAFT_QA_RSCRIPT')
    if env_path and Path(env_path).exists():
        return env_path
    which = shutil.which('Rscript')
    if which:
        return which
    default_r = Path(r'C:\Program Files\R\R-4.6.1\bin\x64\Rscript.exe')
    return str(default_r) if default_r.exists() else None


def _run_modal_with(win, dlg_cls, trigger_fn, fn):
    done = [False]
    poll = QTimer(win)
    safety = QTimer(win)
    safety.setSingleShot(True)

    def tick():
        if done[0]:
            poll.stop()
            return
        active = QApplication.activeModalWidget()
        dlg = active if isinstance(active, dlg_cls) else next(
            (d for d in win.findChildren(dlg_cls) if d.isVisible()),
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

    poll.timeout.connect(tick)
    poll.start(25)
    safety.timeout.connect(lambda: [w.reject() for w in QApplication.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()])
    safety.start(3000)
    try:
        trigger_fn()
    finally:
        poll.stop()
        safety.stop()


class AttributeWorkflowsAndMultiSheetTests(unittest.TestCase):
    def test_multisheet_report_source_resolution_and_auto_heal(self):
        p = Presenter()
        p.worksheet = Worksheet('Variables_Base', [
            Column('Diam', 'number', [10.0, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 14.5, 16.0, 11.0, 10.0, 10.1, 9.9]),
            Column('Lot', 'text', ['L1'] * 3 + ['L2'] * 3 + ['L3'] * 3 + ['L4'] * 3 + ['L5'] * 3),
        ])
        xr = p.subgroup_control_chart(chart_type='xbar_s', stacked=True, response_index=0, factor_index=1)
        sg_sens = p.subgroup_sensitivity(xr, 'exclusion', batch_col_index=1, batch_values=['L4'], treatment='exclude_rows')

        s2 = p.add_worksheet('Batch_2')
        s2.columns = [
            Column('BatchDiam', 'number', [10.0, 10.05, 9.95, 10.02, 9.98, 10.01, 10.0, 9.99, 10.02], metadata={'units': 'mm'}),
            Column('BatchLot', 'text', ['B1'] * 3 + ['B2'] * 3 + ['B3'] * 3),
            Column('BadDiamIn', 'number', [10.0, 10.1, 9.9, 10.0, 10.1, 9.9, 10.0, 10.1, 9.9], metadata={'units': 'in'}),
        ]

        s3 = p.add_worksheet('Gage_RR')
        s3.columns = [
            Column('Part', 'text', ['P1'] * 4 + ['P2'] * 4 + ['P3'] * 4),
            Column('Operator', 'text', ['A', 'A', 'B', 'B'] * 3),
            Column('Reading', 'number', [10.0, 10.1, 10.2, 10.1, 12.0, 12.1, 12.2, 12.2, 14.0, 13.9, 14.1, 14.2]),
        ]
        grr = p.gage_rr(2, 0, 1, options={'tolerance': 6.0, 'process_stdev': 1.5})

        # Leave Batch_2 active, inject a pre-corrupted cached connected_analysis on Gage R&R, and roundtrip MPX.
        p.select_worksheet(1)
        grr['connected_analysis'] = {
            'analysis_id': 'corrupted-cache',
            'analysis_type': 'gage_rr',
            'title': 'Gage R&R: BadDiamIn',
            'engine': 'statcraft',
            'created_at': '2026-11-22T00:00:00',
            'worksheet_id': s2.metadata.get('id', 'ws-batch2'),
            'worksheet_name': 'Batch_2',
            'data_fingerprint': 'stale',
            'response_col_id': 'col-bad',
            'response_name': 'BadDiamIn',
            'predictor_col_ids': [],
            'predictor_names': ['BatchDiam', 'BatchLot'],
            'confidence': 0.95,
            'row_ids': ['r'] * 9,
            'fitted_row_ids': ['r'] * 9,
            'omitted_row_ids': [],
            'coefficients': [],
            'statistics': {},
            'fitted_values': [],
            'residuals': [],
            'metadata': {},
            'r_script': '# BadDiamIn script',
        }

        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / 'multisheet.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)

        self.assertEqual(reopened.worksheet.name, 'Batch_2')
        saved_sens = next(e for e in reopened.history if e['entry_id'] == sg_sens['entry_id'])
        saved_grr = next(e for e in reopened.history if e['entry_id'] == grr['entry_id'])
        self.assertEqual(reopened.resolve_entry_worksheet(saved_sens).name, 'Variables_Base')
        self.assertEqual(reopened.resolve_entry_worksheet(saved_grr).name, 'Gage_RR')

        ghost = copy.deepcopy(saved_grr)
        ghost['worksheet_id'] = 'missing-ws-id'
        ghost['worksheet_name'] = 'DeletedSheet'
        self.assertIsNone(reopened.resolve_entry_worksheet(ghost))

        win = ModernWindow(reopened)
        try:
            win.show_result(saved_sens, target_tab='Report')
            bridge_sens = win.result_tabs.currentWidget().content.findChild(ConnectBridgeWidget)
            self.assertIsNotNone(bridge_sens)
            badge_texts_sens = [lbl.text() for lbl in bridge_sens.findChildren(QLabel)]
            self.assertIn('✓ In Sync', badge_texts_sens)
            self.assertNotIn('⚠ Source Column Missing', badge_texts_sens)
            self.assertIn('Diam', bridge_sens.get_full_r_script())
            self.assertNotIn('BadDiamIn', bridge_sens.get_full_r_script())

            win.show_result(saved_grr, target_tab='Report')
            bridge_grr = win.result_tabs.currentWidget().content.findChild(ConnectBridgeWidget)
            self.assertIsNotNone(bridge_grr)
            badge_texts_grr = [lbl.text() for lbl in bridge_grr.findChildren(QLabel)]
            self.assertIn('✓ In Sync', badge_texts_grr)
            self.assertIn('Reading', bridge_grr.model_info.text())
            self.assertIn('N = 12', bridge_grr.model_info.text())
            self.assertNotIn('BadDiamIn', bridge_grr.model_info.text())
            self.assertEqual(saved_grr['connected_analysis']['worksheet_name'], 'Gage_RR')
            self.assertIn('Reading', win._get_entry_r_script(saved_grr)[0])

            # Deleted source worksheet must display explicit missing-sheet badge instead of binding active Batch_2.
            ghost_bridge = ConnectBridgeWidget(win, ghost, ghost['connected_analysis'])
            ghost_badges = [lbl.text() for lbl in ghost_bridge.findChildren(QLabel)]
            self.assertIn('⚠ Source Worksheet Unavailable', ghost_badges)

            # Read-only regression check against the saved v121.2.21 QA project when present.
            qa_mpx = Path('artifacts/visual_qa/121.2.21-native/Visual-QA-Checked.mpx')
            if qa_mpx.exists():
                qa_pres = Presenter()
                qa_pres.load(qa_mpx)
                batch_idx = next((i for i, ws in enumerate(qa_pres.native_project.worksheets) if ws.name == 'Batch_2'), None)
                if batch_idx is not None:
                    qa_pres.select_worksheet(batch_idx)
                qa_win = ModernWindow(qa_pres)
                try:
                    qa_sens = next((e for e in qa_pres.history if e.get('result', {}).get('sensitivity', {}).get('kind') == 'subgroup_exclusion'), None)
                    if qa_sens is not None:
                        qa_win.show_result(qa_sens, target_tab='Report')
                        qa_sens_bridge = qa_win.result_tabs.currentWidget().content.findChild(ConnectBridgeWidget)
                        self.assertIsNotNone(qa_sens_bridge)
                        qa_sens_badges = [lbl.text() for lbl in qa_sens_bridge.findChildren(QLabel)]
                        self.assertIn('✓ In Sync', qa_sens_badges)
                        self.assertNotIn('⚠ Source Column Missing', qa_sens_badges)
                    qa_grr = next((e for e in qa_pres.history if e.get('result', {}).get('analysis') == 'gage_rr'), None)
                    if qa_grr is not None:
                        qa_win.show_result(qa_grr, target_tab='Report')
                        qa_bridge = qa_win.result_tabs.currentWidget().content.findChild(ConnectBridgeWidget)
                        self.assertIsNotNone(qa_bridge)
                        self.assertIn('Reading', qa_bridge.model_info.text())
                        self.assertIn('N = 12', qa_bridge.model_info.text())
                        self.assertNotIn('BadDiamIn', qa_bridge.model_info.text())
                finally:
                    qa_pres.dirty = False
                    qa_pres._results_dirty = False
                    qa_win.close()
                    qa_win.deleteLater()
                    _APP.processEvents()
        finally:
            p.dirty = False
            p._results_dirty = False
            reopened.dirty = False
            reopened._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()

    def test_attribute_traceability_variants_stale_and_dialog(self):
        p = Presenter()
        p.worksheet = Worksheet('AttrTrace', [
            Column('DefectsP', 'number', [2, 3, 1, 18, 2, 4, 3]),
            Column('SizesP', 'number', [100, 120, 80, 150, 100, 110, 95]),
            Column('DefectsC', 'number', [3, 5, 2, 12, 4, 6, 3]),
            Column('LaneyCnt', 'number', [12, 38, 15, 42, 10, 44, 14]),
            Column('LaneyN', 'number', [200, 220, 190, 250, 210, 230, 200]),
        ])
        e_p = p.attribute_control_chart({
            'chart_type': 'P',
            'variables': [0],
            'is_subgroup_col': True,
            'subgroup_col_idx': 1,
            'options': {'omit_subgroups': [3], 'exclude_rows': [2], 'k_sigma': 3.0},
        })
        e_np = p.attribute_control_chart({'chart_type': 'NP', 'variables': [0], 'is_subgroup_col': False, 'subgroup_size': 100})
        e_c = p.attribute_control_chart({'chart_type': 'C', 'variables': [2]})
        e_u = p.attribute_control_chart({'chart_type': 'U', 'variables': [2], 'is_subgroup_col': False, 'subgroup_size': 2.0})
        e_pp = p.attribute_control_chart({'chart_type': "P'", 'variables': [3], 'is_subgroup_col': True, 'subgroup_col_idx': 4})
        e_up = p.attribute_control_chart({'chart_type': "U'", 'variables': [3], 'is_subgroup_col': True, 'subgroup_col_idx': 4})

        t_excl = attribute_point_trace(e_p['result'], 2)
        self.assertTrue(t_excl['excluded'])
        self.assertIsNone(t_excl['value'])

        t_omit = attribute_point_trace(e_p['result'], 3)
        self.assertTrue(t_omit['omitted'])
        self.assertEqual(t_omit['count'], 1.0)

        t_sig = attribute_point_trace(e_p['result'], 4)
        self.assertIn(1, t_sig['rules'])
        self.assertAlmostEqual(t_sig['value'], 18.0 / 150.0)

        self.assertAlmostEqual(attribute_point_trace(e_np['result'], 1)['value'], 2.0)
        self.assertEqual(attribute_point_trace(e_c['result'], 1)['subgroup_size'], 1.0)
        self.assertAlmostEqual(attribute_point_trace(e_u['result'], 1)['value'], 1.5)
        self.assertGreater(attribute_point_trace(e_pp['result'], 1)['sigma_z'], 0.0)
        self.assertGreater(attribute_point_trace(e_up['result'], 1)['sigma_z'], 0.0)

        with self.assertRaises(ValueError):
            attribute_point_trace(e_p['result'], 0)
        with self.assertRaises(ValueError):
            attribute_point_trace(e_p['result'], 8)
        with self.assertRaises(ValueError):
            attribute_point_trace(e_p['result'], '4')  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / 'attr_trace.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)

        saved_pp = next(e for e in reopened.history if e['entry_id'] == e_pp['entry_id'])
        saved_p = next(e for e in reopened.history if e['entry_id'] == e_p['entry_id'])
        reopened.worksheet.columns[0].values[0] = 50.0
        self.assertTrue(reopened.result_stale(saved_p))

        win = ModernWindow(reopened)
        seen_labels = []
        trace_texts = []
        try:
            menu = win.build_output_context_menu(saved_p)
            act = next(a for a in menu.actions() if a.text() == 'Trace Attribute Result…')

            def inspect_trace(dlg):
                seen_labels.extend(lbl.text() for lbl in dlg.findChildren(QLabel))
                dlg.subgroup.setValue(4)
                trace_texts.append(dlg.details.toPlainText())

            _run_modal_with(win, AttributeTraceDialog, act.trigger, inspect_trace)
            self.assertIn('The current worksheet differs from the saved analysis.', seen_labels)
            self.assertTrue(trace_texts and 'Subgroup (Row): 4' in trace_texts[0] and 'Test 1' in trace_texts[0])
            self.assertIn('sigma_z', attribute_point_trace(saved_pp['result'], 1))
        finally:
            p.dirty = False
            p._results_dirty = False
            reopened.dirty = False
            reopened._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()

    def test_attribute_investigation_context_edit_mpx_and_report_layout(self):
        p = Presenter()
        p.worksheet = Worksheet('Attr_Before', [
            Column('Defects', 'number', [2, 3, 1, 18, 2, 3, 2]),
            Column('SubSize', 'number', [100, 120, 80, 150, 100, 110, 95]),
            Column('Shift', 'text', ['Day', 'Day', 'Night', 'Night', 'Day', 'Day', 'Night']),
        ])
        base_p = p.attribute_control_chart({'chart_type': 'P', 'variables': [0], 'is_subgroup_col': True, 'subgroup_col_idx': 1})
        clean_p = p.attribute_control_chart({
            'chart_type': 'P',
            'variables': [0],
            'is_subgroup_col': True,
            'subgroup_col_idx': 1,
            'options': {'exclude_rows': [4]},
        })

        follow_sheet = p.add_worksheet('Attr_Followup')
        follow_sheet.columns = [
            Column('Defects', 'number', [1, 2, 1, 2, 1, 2, 1]),
            Column('SubSize', 'number', [100, 100, 100, 100, 100, 100, 100]),
        ]
        follow_p = p.attribute_control_chart({'chart_type': 'P', 'variables': [0], 'is_subgroup_col': True, 'subgroup_col_idx': 1})

        win = ModernWindow(p)
        try:
            # Clean chart with zero signals has Investigate Signal… disabled
            clean_menu = win.build_output_context_menu(clean_p)
            clean_inv = next(a for a in clean_menu.actions() if a.text() == 'Investigate Signal…')
            self.assertFalse(clean_inv.isEnabled())

            menu = win.build_output_context_menu(base_p)
            inv_act = next(a for a in menu.actions() if a.text() == 'Investigate Signal…')
            before_n = len(p.history)

            # Cancel leaves history untouched
            _run_modal_with(win, AttributeInvestigationDialog, inv_act.trigger, lambda dlg: dlg.reject())
            self.assertEqual(len(p.history), before_n)

            errors = []

            def fill_investigation(dlg):
                dlg.save()
                errors.append(dlg.error.text())
                dlg.notes['cause'].setPlainText('Nozzle buildup on Night shift')
                dlg.notes['evidence'].setPlainText('Row 4 Defects=18, Shift=Night')
                dlg.notes['action'].setPlainText('Cleaned nozzle and verified on Attr_Followup')
                idx = dlg.after.findData(follow_p['entry_id'])
                self.assertGreater(idx, 0)
                dlg.after.setCurrentIndex(idx)
                dlg.save()

            _run_modal_with(win, AttributeInvestigationDialog, inv_act.trigger, fill_investigation)
            self.assertTrue(errors and 'Suspected' in errors[0].capitalize() or 'cause' in errors[0].lower())
            self.assertEqual(len(p.history), before_n + 1)
            inv_entry = p.history[-1]
            self.assertEqual(inv_entry['result']['analysis'], 'attribute_investigation')
            self.assertEqual(inv_entry['result']['after']['worksheet'], 'Attr_Followup')
            self.assertEqual(inv_entry['worksheet_name'], 'Attr_Before')

            txt = format_entry(inv_entry)
            self.assertIn('Before and after', txt)
            self.assertIn('Shift=Night', txt)
            self.assertIn('Attr_Followup', txt)

            # Report uses investigation layout (Edit Investigation button, no R Translator card)
            win.show_result(inv_entry, target_tab='Report')
            page = win.result_tabs.currentWidget().content
            self.assertIsNone(page.findChild(ConnectBridgeWidget))
            btn_texts = [b.text() for b in page.findChildren(QToolButton)]
            self.assertIn('Edit Investigation…', btn_texts)
            inv_menu = win.build_output_context_menu(inv_entry)
            inv_menu_texts = [a.text() for a in inv_menu.actions()]
            self.assertIn('Edit Investigation…', inv_menu_texts)
            self.assertNotIn('📋 Copy R Script\tCtrl+Alt+R', inv_menu_texts)

            with tempfile.TemporaryDirectory() as tmp:
                mpx_path = Path(tmp) / 'attr_inv.mpx'
                p.save(mpx_path)
                reopened = Presenter()
                reopened.load(mpx_path)
            saved_inv = next(e for e in reopened.history if e['entry_id'] == inv_entry['entry_id'])
        finally:
            p.dirty = False
            p._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()

        win2 = ModernWindow(reopened)
        try:
            win2.show_result(saved_inv, target_tab='Report')
            report2 = win2.result_tabs.currentWidget().content
            self.assertIsNone(report2.findChild(ConnectBridgeWidget))

            edit_dlg = AttributeInvestigationDialog(win2, None, saved_inv)
            try:
                self.assertFalse(edit_dlg.signal.isEnabled())
                self.assertIn('Saved comparison · Attr_Followup', edit_dlg.after.currentText())
                self.assertIn('Attr_Followup', edit_dlg.preview.toPlainText())
            finally:
                edit_dlg.close()

            edit_texts = []
            poll = QTimer()
            safety = QTimer()
            safety.setSingleShot(True)

            def inspect_edit():
                dlg = QApplication.activeModalWidget()
                if isinstance(dlg, AttributeInvestigationDialog):
                    try:
                        edit_texts.append(dlg.preview.toPlainText())
                        self.assertFalse(dlg.signal.isEnabled())
                    finally:
                        poll.stop()
                        safety.stop()
                        dlg.reject()

            poll.timeout.connect(inspect_edit)
            safety.timeout.connect(lambda: (poll.stop(), [w.reject() for w in QApplication.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]))
            poll.start(30)
            safety.start(2000)
            edit_btn = next(b for b in report2.findChildren(QToolButton) if b.text() == 'Edit Investigation…')
            edit_btn.click()
            poll.stop()
            safety.stop()
            self.assertTrue(edit_texts and 'Attr_Followup' in edit_texts[0])
        finally:
            reopened.dirty = False
            reopened._results_dirty = False
            win2.close()
            win2.deleteLater()
            _APP.processEvents()

    def test_attribute_replay_approve_validation_pass_fail_and_mpx(self):
        p = Presenter()
        p.worksheet = Worksheet('AttrBase', [
            Column('Defects', 'number', [2, 3, 1, 2, 3, 2, 1]),
            Column('SubSize', 'number', [100, 100, 100, 100, 100, 100, 100]),
            Column('CDefects', 'number', [3, 4, 2, 5, 3, 4, 2]),
        ])
        base_p = p.attribute_control_chart({'chart_type': 'P', 'variables': [0], 'is_subgroup_col': True, 'subgroup_col_idx': 1})
        base_c = p.attribute_control_chart({'chart_type': 'C', 'variables': [2]})

        with self.assertRaises(ValueError):
            approve_attribute(p, base_p, max_signals=-1)
        with self.assertRaises(ValueError):
            approve_attribute(p, base_p, max_signals=0, max_center=1.5)

        approve_dlg = ApproveAttributeReplayDialog(None, default_center=base_p['result']['center'], chart_type='P')
        try:
            self.assertFalse(approve_dlg.max_center_spin.isEnabled())
            approve_dlg.use_max_center.setChecked(True)
            self.assertTrue(approve_dlg.max_center_spin.isEnabled())
            approve_dlg.max_center_spin.setValue(0.05)
            self.assertEqual(approve_dlg.thresholds(), (0, 0.05))
        finally:
            approve_dlg.close()

        tpl_p = approve_attribute(p, base_p, max_signals=0, max_center=0.05)
        tpl_c = approve_attribute(p, base_c, max_signals=0)

        bad_sheet = p.add_worksheet('AttrBad')
        bad_sheet.columns = [
            Column('BadDef', 'number', [120, 2, 3]),
            Column('BadSz', 'number', [100, 100, 100]),
        ]
        with self.assertRaises(ValueError):
            preview_attribute(p, tpl_p, count_index=0, size_index=1)
        with self.assertRaises(ValueError):
            preview_attribute(p, tpl_p, count_index=0, size_index=0)

        pass_sheet = p.add_worksheet('AttrPass')
        pass_sheet.columns = [
            Column('BatchDef', 'number', [1, 2, 1, 2, 1, 2]),
            Column('BatchSz', 'number', [100, 100, 100, 100, 100, 100]),
            Column('BatchC', 'number', [2, 3, 2, 4, 3, 2]),
        ]
        replayed_pass = replay_attribute(p, tpl_p, count_index=0, size_index=1)
        self.assertTrue(replayed_pass['result']['workflow_comparison']['passed'])
        self.assertIn('Acceptance: Pass', format_entry(replayed_pass))

        replayed_c = replay_attribute(p, tpl_c, count_index=2)
        self.assertTrue(replayed_c['result']['workflow_comparison']['passed'])

        # Re-approval preserves prior comparison
        approve_attribute(p, replayed_pass, max_signals=2, max_center=0.10)
        self.assertEqual(replayed_pass['result']['workflow_comparison']['baseline']['worksheet'], 'AttrBase')
        self.assertEqual(replayed_pass['result']['workflow_comparison']['max_signals'], 0)

        # Stale approval rejected
        p.select_worksheet(0)
        orig_val = p.worksheet.columns[0].values[0]
        p.worksheet.columns[0].values[0] = 9.0
        with self.assertRaises(ValueError):
            approve_attribute(p, base_p, max_signals=0)
        p.worksheet.columns[0].values[0] = orig_val

        fail_sheet = p.add_worksheet('AttrFail')
        fail_sheet.columns = [
            Column('BatchDef', 'number', [2, 3, 2, 25, 2, 3]),
            Column('BatchSz', 'number', [100, 100, 100, 100, 100, 100]),
        ]
        win = ModernWindow(p)
        try:
            menu = win.build_output_context_menu(base_p)
            replay_act = next(a for a in menu.actions() if a.text() == 'Replay Attribute Chart on Current Worksheet…')
            before_n = len(p.history)

            _run_modal_with(win, AttributeReplayDialog, replay_act.trigger, lambda dlg: dlg.reject())
            self.assertEqual(len(p.history), before_n)

            dlg_info = {}

            def accept_replay(dlg):
                dlg_info['count_idx'] = dlg.count_combo.currentData()
                dlg_info['size_idx'] = dlg.size_combo.currentData()
                dlg.accept_replay()

            _run_modal_with(win, AttributeReplayDialog, replay_act.trigger, accept_replay)
            self.assertEqual(dlg_info, {'count_idx': 0, 'size_idx': 1})
            self.assertEqual(len(p.history), before_n + 1)
            fail_entry = p.history[-1]
            self.assertFalse(fail_entry['result']['workflow_comparison']['passed'])
            self.assertIn('Acceptance: Fail', attribute_comparison_text(fail_entry['result']))

            with tempfile.TemporaryDirectory() as tmp:
                mpx_path = Path(tmp) / 'attr_replay.mpx'
                p.save(mpx_path)
                reopened = Presenter()
                reopened.load(mpx_path)
                self.assertTrue(any(
                    e.get('result', {}).get('analysis') == 'attribute_control'
                    and e.get('result', {}).get('workflow_comparison', {}).get('passed') is False
                    for e in reopened.history
                ))
        finally:
            p.dirty = False
            p._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()

    def test_attribute_sensitivity_period_exclusion_dialog_and_verifiers(self):
        p = Presenter()
        p.worksheet = Worksheet('AttrSens', [
            Column('Defects', 'number', [2, 3, 2, 18, 2, 3, 2, 3]),
            Column('SubSize', 'number', [100, 120, 100, 150, 100, 110, 100, 105]),
            Column('Lot', 'text', ['L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7', 'L8']),
            Column('LaneyCnt', 'number', [10, 38, 12, 95, 11, 40, 12, 39]),
            Column('LaneyN', 'number', [200, 220, 190, 200, 210, 230, 200, 220]),
        ])
        e_p = p.attribute_control_chart({'chart_type': 'P', 'variables': [0], 'is_subgroup_col': True, 'subgroup_col_idx': 1})
        e_u = p.attribute_control_chart({'chart_type': 'U', 'variables': [0], 'is_subgroup_col': False, 'subgroup_size': 2.0})
        e_pp = p.attribute_control_chart({'chart_type': "P'", 'variables': [3], 'is_subgroup_col': True, 'subgroup_col_idx': 4})

        with self.assertRaises(ValueError):
            p.attribute_sensitivity(e_p, 'baseline_period', start_row=3, end_row=1)
        with self.assertRaises(ValueError):
            p.attribute_sensitivity(e_p, 'baseline_period', start_row=1, end_row=8)

        period_u = p.attribute_sensitivity(e_u, 'baseline_period', start_row=1, end_row=3)
        self.assertEqual(period_u['result']['sensitivity']['kind'], 'attribute_baseline_period')
        self.assertEqual(period_u['result']['omitted_subgroups'], [4, 5, 6, 7, 8])

        period_pp = p.attribute_sensitivity(e_pp, 'baseline_period', start_row=1, end_row=6)
        self.assertTrue(any(
            c['criterion'] == 'Laney Sigma Z Stability (<=5%)'
            for c in period_pp['result']['sensitivity']['conclusions']
        ))
        self.assertIn('Laney Sigma Z:', sensitivity_comparison_text(period_pp['result']))

        excl_p = p.attribute_sensitivity(
            e_p,
            'exclusion',
            batch_col_index=2,
            batch_values=['L4'],
            treatment='exclude_rows',
        )
        self.assertEqual(excl_p['result']['sensitivity']['kind'], 'attribute_exclusion')
        self.assertEqual(excl_p['result']['excluded_rows'], [4])
        self.assertEqual(excl_p['result']['n_subgroups'], 7)
        conclusions = {c['criterion']: c['status'] for c in excl_p['result']['sensitivity']['conclusions']}
        self.assertEqual(conclusions['Overall Control Status'], 'Changed')
        self.assertIn('Rows excluded:          4', format_entry(excl_p))

        omit_p = p.attribute_sensitivity(
            e_p,
            'exclusion',
            batch_col_index=2,
            batch_values=['L4'],
            treatment='omit_estimation',
        )
        self.assertEqual(omit_p['result']['omitted_subgroups'], [4])
        self.assertEqual(omit_p['result']['n_subgroups'], 8)

        excl_pp = p.attribute_sensitivity(
            e_pp,
            'exclusion',
            batch_col_index=2,
            batch_values=['L4'],
            treatment='exclude_rows',
        )

        # Excluded-row branch must match identically in Excel Verification and R Workbench.
        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = write_verification(Path(tmp) / 'attr_excl.xlsx', p, excl_p)
            wb = load_workbook(xlsx_path, data_only=False)
            ev = ExtendedExcelFormulaEvaluator(wb)
            self.assertEqual(ev.cell('Verification', 'B6'), 'PASS')
            self.assertEqual(ev.cell('Verification', 'B7'), 'Valid')

            rscript = _find_rscript()
            if rscript:
                for tag, entry_ref in (('p', excl_p), ('pp', excl_pp)):
                    r_file = Path(tmp) / f'verify_attr_{tag}.R'
                    r_file.write_text(build_r_script(p, entry_ref), encoding='utf-8')
                    proc = subprocess.run([rscript, '--vanilla', str(r_file)], cwd=tmp, capture_output=True, text=True, timeout=30)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertIn('Verification: PASS', proc.stdout)

            mpx_path = Path(tmp) / 'attr_sens.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            self.assertTrue(any(
                e.get('result', {}).get('sensitivity', {}).get('kind') == 'attribute_exclusion'
                for e in reopened.history
            ))

        win = ModernWindow(p)
        try:
            menu = win.build_output_context_menu(e_p)
            sens_act = next(a for a in menu.actions() if a.text() == 'Sensitivity Analysis…')
            before_n = len(p.history)

            _run_modal_with(win, AttributeSensitivityDialog, sens_act.trigger, lambda dlg: dlg.reject())
            self.assertEqual(len(p.history), before_n)

            errors = []
            labels = []

            def run_dialog_checks(dlg):
                dlg.start_spin.setValue(3)
                dlg.end_spin.setValue(1)
                dlg.validate()
                errors.append(dlg.error.text())

                dlg.mode_combo.setCurrentIndex(1)
                labels.append(dlg.exclusion_controls.rows_label.text())
                dlg.treatment_combo.setCurrentIndex(1)
                labels.append(dlg.exclusion_controls.rows_label.text())
                dlg.treatment_combo.setCurrentIndex(0)
                dlg.exclusion_controls.rows_edit.setText('4')
                dlg.validate()

            _run_modal_with(win, AttributeSensitivityDialog, sens_act.trigger, run_dialog_checks)
            self.assertTrue(errors and 'Baseline period' in errors[0])
            self.assertEqual(labels, ['Additional Rows (1-based):', 'Additional Subgroups (1-based):'])
            self.assertEqual(len(p.history), before_n + 1)
            self.assertEqual(p.history[-1]['result']['sensitivity']['kind'], 'attribute_exclusion')
        finally:
            p.dirty = False
            p._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()


if __name__ == '__main__':
    unittest.main()
