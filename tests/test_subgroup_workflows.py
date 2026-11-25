import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STATCRAFT_TESTING', '1')

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

from statcraft.app import Presenter, format_entry
from statcraft.connect import create_connected_analysis_from_entry
from statcraft.connect_hub import StatCraftAnalysisBar
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.subgroup_workflows import (
    SubgroupInvestigationDialog,
    SubgroupReplayDialog,
    SubgroupTraceDialog,
    approve,
    point_trace,
    preview,
    replay,
)


_APP = QApplication.instance() or QApplication([])


class SubgroupWorkflowsTests(unittest.TestCase):
    def test_traceability_unequal_subgroups_unstacked_mpx_and_dialog(self):
        p = Presenter()
        # Unequal subgroups with a missing cell inside subgroup 2 and omitted subgroup 3
        p.worksheet = Worksheet('TraceSG', [
            Column('Diameter', 'number', [10.0, 10.2, 9.8, 10.1, None, 10.3, 15.0, 16.0, 10.0, 10.1, 9.9]),
            Column('Lot', 'text', ['L1', 'L1', 'L1', 'L2', 'L2', 'L2', 'L3', 'L3', 'L4', 'L4', 'L4']),
            Column('M1', 'number', [5.0, 5.2, 4.9]),
            Column('M2', 'number', [5.1, 5.0, 5.1]),
        ])
        xr = p.subgroup_control_chart(
            chart_type='xbar_r',
            stacked=True,
            response_index=0,
            factor_index=1,
            options={'omit_subgroups': [3]},
        )
        xs = p.subgroup_control_chart(
            chart_type='xbar_s',
            stacked=False,
            indices=[2, 3],
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sg_trace.mpx'
            p.save(path)
            reopened = Presenter()
            reopened.load(path)

        saved_xr = next(e for e in reopened.history if e['entry_id'] == xr['entry_id'])
        saved_xs = next(e for e in reopened.history if e['entry_id'] == xs['entry_id'])

        # Live worksheet edit makes result stale, yet saved trace remains unchanged
        reopened.worksheet.columns[0].values[3] = 999.0
        self.assertTrue(reopened.result_stale(saved_xr))

        t2 = point_trace(saved_xr['result'], 'xbar', 2)
        self.assertEqual(t2['label'], 'L2')
        self.assertEqual(t2['n'], 2)
        self.assertEqual(t2['missing_in_subgroup'], 1)
        self.assertFalse(t2['omitted'])
        self.assertEqual(t2['rows'], [[4, 10.1], [5, None], [6, 10.3]])
        self.assertAlmostEqual(t2['value'], 10.2, places=10)

        t3_disp = point_trace(saved_xr['result'], 'disp', 3)
        self.assertTrue(t3_disp['omitted'])
        self.assertAlmostEqual(t3_disp['value'], 1.0, places=10)
        self.assertIn('d2', t3_disp['constants'])

        t1_xs = point_trace(saved_xs['result'], 'disp', 1)
        self.assertIn('c4', t1_xs['constants'])
        self.assertEqual(t1_xs['rows'], [[1, 5.0, 'M1'], [1, 5.1, 'M2']])

        with self.assertRaises(ValueError):
            point_trace(saved_xr['result'], 'xbar', 0)
        with self.assertRaises(ValueError):
            point_trace(saved_xr['result'], 'invalid', 1)

        win = ModernWindow(reopened)
        observed = []
        labels = []
        try:
            menu = win.build_output_context_menu(saved_xr)
            action = next(a for a in menu.actions() if a.text() == 'Trace Subgroup Result…')

            def inspect():
                dlg = win.findChild(SubgroupTraceDialog)
                if dlg is not None:
                    dlg.panel.setCurrentIndex(1)
                    dlg.subgroup.setValue(3)
                    observed.append(dlg.details.toPlainText())
                    labels.extend(lbl.text() for lbl in dlg.findChildren(QLabel))
                    dlg.reject()

            QTimer.singleShot(120, inspect)
            action.trigger()
            self.assertEqual(len(observed), 1)
            self.assertIn('Row 7: 15.0', observed[0])
            self.assertIn('omitted from parameter estimation', observed[0])
            self.assertTrue(any('current worksheet differs' in lbl for lbl in labels))
        finally:
            reopened.dirty = False
            reopened._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()

    def test_signal_investigation_context_pending_and_after_comparison(self):
        p = Presenter()
        # Subgroup 4 is shifted out-of-control on Xbar and Range
        p.worksheet = Worksheet('Baseline', [
            Column('Diameter', 'number', [
                10.0, 10.1, 9.9,
                10.0, 10.2, 9.8,
                10.1, 9.9, 10.0,
                15.0, 18.0, 16.5,
                10.0, 10.1, 9.9,
            ]),
            Column('Lot', 'text', ['L1']*3 + ['L2']*3 + ['L3']*3 + ['L4']*3 + ['L5']*3),
            Column('Machine', 'text', ['M1']*9 + ['M2']*3 + ['M1']*3),
            Column('Tool', 'text', ['T1']*9 + ['T2']*3 + ['T3']*3),
        ])
        before_entry = p.subgroup_control_chart(
            chart_type='xbar_r', stacked=True, response_index=0, factor_index=1,
        )
        p.add_worksheet('FollowUp').columns = [
            Column('Diameter', 'number', [10.0, 10.1, 9.9, 10.2, 9.8, 10.0, 10.1, 9.9, 10.0]),
            Column('Lot', 'text', ['L6']*3 + ['L7']*3 + ['L8']*3),
        ]
        after_entry = p.subgroup_control_chart(
            chart_type='xbar_r', stacked=True, response_index=0, factor_index=1,
            options={'k_sigma': 2.5},
        )

        # Reject stale creation
        p._owned_project().worksheets[0].columns[0].values[9] = 999.0
        win = ModernWindow(p)
        try:
            dlg_stale = SubgroupInvestigationDialog(win, before_entry)
            dlg_stale.notes['cause'].setPlainText('Should fail stale')
            dlg_stale.save()
            self.assertIn('Rerun', dlg_stale.error.text())
            self.assertIsNone(dlg_stale.saved_entry)
            dlg_stale.reject()

            # Restore and verify empty notes rejected + cancel keeps history unchanged
            p._owned_project().worksheets[0].columns[0].values[9] = 15.0
            hist_before = len(p.history)
            dlg = SubgroupInvestigationDialog(win, before_entry)
            dlg.save()
            self.assertIn('Enter a suspected cause', dlg.error.text())
            self.assertEqual(len(p.history), hist_before)

            # Save with After: Pending
            for idx in range(dlg.signal.count()):
                if dlg.signal.itemData(idx) == ('xbar', 4):
                    dlg.signal.setCurrentIndex(idx)
                    break
            dlg.notes['cause'].setPlainText('Worn spindle T2 on M2')
            dlg.notes['evidence'].setPlainText('Subgroup 4 jumped to 16.5')
            dlg.save()
            inv = dlg.saved_entry
            self.assertIsNotNone(inv)
            self.assertIn('After: Pending', format_entry(inv))
            self.assertIn('C3 Machine=M2 | C4 Tool=T2', format_entry(inv))

            # Older reports can have a cached R Translator record for the baseline.
            self.assertEqual(p.worksheet.name, 'FollowUp')
            create_connected_analysis_from_entry(inv, p.result_worksheet(inv))
            self.assertIn('connected_analysis', inv)

            # Edit investigation to link FollowUp chart and verify option-diff note
            edit_dlg = SubgroupInvestigationDialog(win, None, inv)
            for idx in range(edit_dlg.after.count()):
                if edit_dlg.after.itemData(idx) == after_entry['entry_id']:
                    edit_dlg.after.setCurrentIndex(idx)
                    break
            edit_dlg.notes['action'].setPlainText('Replaced tool T2 with T3')
            edit_dlg.save()
            self.assertEqual(inv['result']['after']['xbar_signals'], 0)
            self.assertIn('saved chart options differ', format_entry(inv))
            win.show_result(inv, target_tab='Report')
            self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), 'Report')
            inv_menu = [a.text() for a in win.build_output_context_menu(inv).actions()]
            report = win.result_tabs.currentWidget().content
            self.assertIsNone(report.findChild(StatCraftAnalysisBar))
            self.assertTrue(any(
                button.text().startswith('Edit Investigation')
                for button in report.findChildren(QToolButton)
            ))
            self.assertFalse(any('Copy R Script' in action for action in inv_menu))
            self.assertTrue(win.tab_copy_r_btn.isHidden())

            win.show_result(after_entry, target_tab='Report')
            bridge = win.result_tabs.currentWidget().content.findChild(StatCraftAnalysisBar)
            self.assertIsNotNone(bridge)
            self.assertFalse(win.tab_copy_r_btn.isHidden())
            self.assertIn('Edit Investigation…', inv_menu)

            # Live worksheet edit does not alter saved investigation context across MPX roundtrip
            p._owned_project().worksheets[0].columns[3].values[10] = 'CHANGED'
            with tempfile.TemporaryDirectory() as tmp:
                mpx_path = Path(tmp) / 'sg_inv.mpx'
                p.save(mpx_path)
                reopened = Presenter()
                reopened.load(mpx_path)
            saved_inv = next(e for e in reopened.history if e['entry_id'] == inv['entry_id'])
            txt = format_entry(saved_inv)
            self.assertIn('C4 Tool=T2', txt)
            self.assertIn(f"Xbar signals: {inv['result']['before']['xbar_signals']}/5", txt)
            self.assertIn('Xbar signals: 0/3', txt)
            self.assertIn('Replaced tool T2 with T3', txt)
        finally:
            p.dirty = False
            p._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()

    def test_workflow_replay_stacked_constant_unstacked_and_dialog(self):
        # 1. Stacked with factor ID + unit validation + re-approval preservation
        p = Presenter()
        p.worksheet = Worksheet('Baseline', [
            Column('Diameter', 'number', [10.0, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1, 9.9], metadata={'unit': 'mm'}),
            Column('Lot', 'text', ['L1']*4 + ['L2']*4),
        ])
        base = p.subgroup_control_chart(
            chart_type='xbar_r', stacked=True, response_index=0, factor_index=1,
            options={'historical_mean': 10.0, 'historical_sigma': 0.2, 'omit_subgroups': [2]},
        )
        approve(p, base, 0)
        tpl = base['result']['workflow_replay']

        p.add_worksheet('Batch').columns = [
            Column('LotB', 'text', ['B1']*4 + ['B2']*4),
            Column('NewDiam', 'number', [10.0, 10.0, 10.0, 10.0, 14.0, 14.1, 13.9, 14.0], metadata={'unit': 'in'}),
        ]
        # Unit mismatch rejected without adding history
        hist_len = len(p.history)
        with self.assertRaisesRegex(ValueError, 'differs'):
            replay(p, tpl, response_index=1, factor_index=0)
        self.assertEqual(len(p.history), hist_len)

        # Too few subgroups for saved omission [2] rejected cleanly
        p.worksheet.columns[1].metadata['unit'] = 'mm'
        p.add_worksheet('TooShort').columns = [
            Column('LotS', 'text', ['S1']*4),
            Column('ShortDiam', 'number', [10.0, 10.1, 9.9, 10.0], metadata={'unit': 'mm'}),
        ]
        with self.assertRaisesRegex(ValueError, 'beyond the batch'):
            replay(p, tpl, response_index=1, factor_index=0)

        # Replay on valid Batch worksheet -> Acceptance: Fail + MPX persistence + re-approval preserves baseline
        p.select_worksheet(1)
        self.assertIn('C2 NewDiam', preview(p, tpl, response_index=1, factor_index=0))
        replayed = replay(p, tpl, response_index=1, factor_index=0)
        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / 'sg_replay.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
        saved = next(e for e in reopened.history if e['entry_id'] == replayed['entry_id'])
        txt = format_entry(saved)
        self.assertIn('Workflow Replay', txt)
        self.assertIn('Acceptance: Fail', txt)
        approve(reopened, saved, 3)
        self.assertIn('Acceptance: Fail', format_entry(saved))
        self.assertEqual(saved['result']['workflow_replay']['max_signals'], 3)

        # 2. Constant subgroup size AND unstacked row replay + UI dialog cancel/accept
        p2 = Presenter()
        p2.worksheet = Worksheet('UnstackedBase', [
            Column('S1', 'number', [10.0, 10.1, 9.9], metadata={'unit': 'kg'}),
            Column('S2', 'number', [10.1, 9.9, 10.0], metadata={'unit': 'kg'}),
            Column('Const', 'number', [10.0, 10.1, 9.9, 10.2, 9.8, 10.0], metadata={'unit': 'kg'}),
        ])
        unstacked_base = p2.subgroup_control_chart(chart_type='xbar_s', stacked=False, indices=[0, 1])
        const_base = p2.subgroup_control_chart(chart_type='xbar_r', stacked=True, response_index=2, subgroup_size=2)
        approve(p2, unstacked_base, 1)
        approve(p2, const_base, 1)

        p2.add_worksheet('UnstackedBatch').columns = [
            Column('S1', 'number', [10.0, 10.1, 10.0], metadata={'unit': 'kg'}),
            Column('S2', 'number', [10.0, 9.9, 10.1], metadata={'unit': 'kg'}),
            Column('Const', 'number', [10.0, 10.0, 10.1, 9.9, 10.0, 10.0], metadata={'unit': 'kg'}),
        ]
        const_replay = replay(p2, const_base['result']['workflow_replay'], response_index=2)
        self.assertIn('Acceptance: Pass', format_entry(const_replay))

        win = ModernWindow(p2)
        try:
            hist_before = len(p2.history)
            dlg_cancel = SubgroupReplayDialog(win, unstacked_base)
            self.assertTrue(dlg_cancel.buttons.button(dlg_cancel.buttons.StandardButton.Ok).isEnabled())
            dlg_cancel.reject()
            self.assertEqual(len(p2.history), hist_before)

            dlg_ok = SubgroupReplayDialog(win, unstacked_base)
            dlg_ok.accept_replay()
            self.assertIsNotNone(dlg_ok.saved_entry)
            self.assertIn('Acceptance: Pass', format_entry(dlg_ok.saved_entry))
            win.show_result(dlg_ok.saved_entry, target_tab='Report')
        finally:
            p2.dirty = False
            p2._results_dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()


if __name__ == '__main__':
    unittest.main()
