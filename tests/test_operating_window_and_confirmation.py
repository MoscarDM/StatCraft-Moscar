"""Tests for 3D Operating Window, Drift Robustness, and Confirmation Experiments."""
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QToolButton
from scipy import stats

from statcraft import recipes
from statcraft.app import Presenter
from statcraft.confirmation_experiments import (
    create_confirmation_plan,
    evaluate_confirmation_runs,
)
from statcraft.graph_frame import GraphFrame
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.modern_charts import ChartWidget
from statcraft.operating_window import (
    chemical_operating_window_defaults,
    evaluate_operating_window,
    simulate_chemical_confirmation_responses,
)
from statcraft.operating_window_dialogs import (
    ConfirmationEvaluateDialog,
    ConfirmationPlanDialog,
    OperatingWindowDialog,
    OperatingWindowSensitivityDialog,
)
from statcraft.optimizer import _encode_ols, _fit_model_bundle

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STATCRAFT_TESTING', '1')
_APP = QApplication.instance() or QApplication([])


class OperatingWindowAndConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.presenter = Presenter()

    def test_sensitivity_branches_one_assumption_and_saves_decision_comparison(self):
        presenter = self.presenter
        y_entry, v_entry = presenter.load_chemical_operating_window_demo()
        specs, options = chemical_operating_window_defaults(y_entry['recipe'], v_entry['recipe'])
        baseline = presenter.operating_window_3d(specs, 0, 1, options)
        before = json.dumps(baseline, sort_keys=True)
        scenario = presenter.operating_window_sensitivity(baseline, 0, 20.0)
        result = scenario['result']
        self.assertEqual(json.dumps(baseline, sort_keys=True), before)
        self.assertEqual(result['selected_setting']['factors'], baseline['result']['robust_setting']['factors'])
        self.assertFalse(result['selected_setting']['worst_case_feasible'])
        self.assertTrue(result['empty_window'])
        self.assertEqual(result['sensitivity']['baseline_id'], baseline['entry_id'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sensitivity.mpx'
            presenter.save(path)
            loaded = Presenter()
            loaded.load(path)
            saved = next(entry for entry in loaded.history if entry['entry_id'] == scenario['entry_id'])
            self.assertEqual(saved['result']['sensitivity'], result['sensitivity'])
            self.assertEqual(loaded.rerun_result(saved)['result']['window_summary'], result['window_summary'])

        win = ModernWindow(presenter)
        try:
            dlg = OperatingWindowSensitivityDialog(win, baseline)
            count = len(presenter.history)
            dlg.drift.setText('-1')
            dlg.validate()
            self.assertIn('non-negative', dlg.error.text())
            self.assertEqual(len(presenter.history), count)
            dlg.reject()
            self.assertEqual(len(presenter.history), count)
            presenter.worksheet.columns[0].values[0] += 1
            with self.assertRaisesRegex(ValueError, 'Rerun the baseline'):
                presenter.operating_window_sensitivity(baseline, 0, 20.0)
        finally:
            win.hide()
            win.deleteLater()
            _APP.processEvents()

    def test_closed_form_quadratic_margins_drift_and_outside_hull(self):
        # Circular design points of radius <= 2 inside [-2, 2] x [-2, 2]:
        # corners (2, 2) etc. have distance sqrt(8) > 2 -> outside design hull!
        angles = [k * math.pi / 4.0 for k in range(8)]
        xs = [2.0 * math.cos(a) for a in angles] + [0.0, 0.0, 0.0]
        ys = [2.0 * math.sin(a) for a in angles] + [0.0, 0.0, 0.0]
        # Deterministic exact quadratics with tiny non-degenerate replicate jitter for df_error > 0
        noise = [0.0] * 8 + [0.01, -0.01, 0.0]
        y1 = [90.0 + 3.0 * x - 1.5 * x * x - 1.0 * y * y + eps for x, y, eps in zip(xs, ys, noise)]
        y2 = [22.0 - 4.0 * x - 0.5 * y * y - eps for x, y, eps in zip(xs, ys, noise)]

        self.presenter.worksheet = Worksheet(
            'HullQuadratic',
            [
                Column('X1', 'number', xs),
                Column('X2', 'number', ys),
                Column('Y1', 'number', y1),
                Column('Y2', 'number', y2),
            ],
        )
        e1 = self.presenter.analyze_response_surface(2, [0, 1])
        e2 = self.presenter.analyze_response_surface(3, [0, 1])
        specs = [
            dict(model_recipe=e1['recipe'], lower=86.0, upper=None, goal='maximize'),
            dict(model_recipe=e2['recipe'], lower=18.0, upper=26.0, goal='target', target=22.0),
        ]
        res = evaluate_operating_window(
            self.presenter.worksheet,
            specs,
            x_index=0,
            y_index=1,
            options=dict(
                grid_size=17,
                drifts=[{'index': 0, 'delta': 0.5}, {'index': 1, 'delta': 0.25}],
                design_region_only=True,
            ),
        )
        self.assertEqual(res['analysis'], 'operating_window_3d')
        # Grid corner (0, 0) corresponds to (-2, -2), which is outside octagonal radius-2 hull
        self.assertTrue(res['outside_region_grid'][0][0])
        self.assertTrue(res['outside_region_grid'][-1][-1])
        # Grid center (8, 8) corresponds to (0, 0), strictly inside hull
        self.assertFalse(res['outside_region_grid'][8][8])

        # Verify closed-form Y2 drift at nominal corner (~ +0.8, 0) vs Robust center (~0, 0):
        rob = res['robust_setting']
        self.assertFalse(rob['outside_design_region'])
        self.assertTrue(rob['worst_case_feasible'])
        self.assertGreater(rob['min_drift_margin'], 0.0)
        # Verify strictly JSON serializable
        json.dumps(res, allow_nan=False)

    def test_chemical_process_cliff_fails_drift_while_robust_confirms(self):
        y_entry, v_entry = self.presenter.load_chemical_operating_window_demo()
        specs, opts = chemical_operating_window_defaults(y_entry['recipe'], v_entry['recipe'])
        ow_entry = self.presenter.operating_window_3d(specs, 0, 1, options=opts)
        res = ow_entry['result']

        opt = res['predicted_optimum']
        rob = res['robust_setting']
        # Predicted optimum pushes Yield up on the Temp cliff where Viscosity fails +/-3C drift
        self.assertTrue(opt['nominal_feasible'])
        self.assertFalse(opt['worst_case_feasible'])
        self.assertLess(opt['min_drift_margin'], 0.0)
        self.assertEqual(opt['limiting_response'], 'Viscosity')

        # Robust interior setting passes nominal AND full +/-3C, +/-0.15 bar drift inside hull
        self.assertFalse(rob['outside_design_region'])
        self.assertTrue(rob['nominal_feasible'])
        self.assertTrue(rob['worst_case_feasible'])
        self.assertGreater(rob['min_drift_margin'], 0.0)
        self.assertGreater(rob['min_drift_std_margin'], 0.2)

        # Generate confirmation plan and simulate responses -> must confirm
        plan_entry = self.presenter.create_confirmation_plan(
            res,
            setting_keys=['robust_setting'],
            replicates=4,
            seed=7,
            confidence=0.95,
        )
        run_ws = self.presenter.worksheet
        self.assertEqual(run_ws.name, 'Confirmation_Runs')
        self.assertEqual(run_ws.row_count, 4)
        simulate_chemical_confirmation_responses(run_ws, seed=101)
        eval_entry = self.presenter.evaluate_confirmation_runs(plan_entry['result'])
        ev = eval_entry['result']
        self.assertTrue(ev['confirmed'])
        for row in ev['comparisons']:
            self.assertEqual(row['status'], 'Confirmed')
            self.assertTrue(row['mean_in_spec'])
            self.assertTrue(row['mean_in_confirm_pi'])

    def test_exact_confirmation_pi_and_shuffled_runid_invariance(self):
        y_entry, v_entry = self.presenter.load_chemical_operating_window_demo()
        specs, opts = chemical_operating_window_defaults(y_entry['recipe'], v_entry['recipe'])
        ow_res = evaluate_operating_window(self.presenter.worksheet, specs, 0, 1, options=opts)

        m = 5
        conf = 0.90
        run_ws, plan = create_confirmation_plan(
            self.presenter.worksheet,
            ow_res,
            setting_keys=['robust_setting'],
            replicates=m,
            seed=19,
            confidence=conf,
        )
        # Closed-form check against scipy.stats.t.ppf & SVD leverage h for first response (Yield)
        bnd = _fit_model_bundle(self.presenter.worksheet, y_entry['recipe'])
        svd = bnd['svd']
        res_y = bnd['result']
        rob_f = ow_res['robust_setting']['factors']
        x_row = [rob_f[p['name']] for p in bnd['predictors']]
        new_x = _encode_ols([x_row], bnd['encode_action'], res_y)
        coded = (new_x - svd['means']) / svd['scales']
        fit = float((svd['mean_y'] + svd['unit'] * (coded @ svd['gamma']))[0])
        transformed = (coded @ svd['vh'].T) / svd['singular']
        h = float(1.0 / svd['n'] + np.sum(transformed * transformed, axis=1)[0])
        t_crit = float(stats.t.ppf((1.0 + conf) / 2.0, res_y['df_error']))
        half_width_m = t_crit * res_y['residual_stdev'] * math.sqrt(h + 1.0 / m)
        half_width_1 = t_crit * res_y['residual_stdev'] * math.sqrt(h + 1.0)

        crit_y = plan['settings'][0]['responses'][0]
        self.assertAlmostEqual(crit_y['fit'], fit, places=9)
        self.assertAlmostEqual(crit_y['confirm_pi_low'], fit - half_width_m, places=9)
        self.assertAlmostEqual(crit_y['confirm_pi_high'], fit + half_width_m, places=9)
        self.assertAlmostEqual(crit_y['indiv_pi_low'], fit - half_width_1, places=9)
        self.assertAlmostEqual(crit_y['indiv_pi_high'], fit + half_width_1, places=9)

        # Populate responses, evaluate, then reverse rows in measurement sheet and verify identical results
        simulate_chemical_confirmation_responses(run_ws, seed=202)
        eval_forward = evaluate_confirmation_runs(plan, run_ws)
        reversed_cols = [Column(c.name, c.kind, list(reversed(c.values))) for c in run_ws.columns]
        shuffled_ws = Worksheet('Shuffled_Runs', reversed_cols)
        eval_reversed = evaluate_confirmation_runs(plan, shuffled_ws)
        self.assertEqual(eval_forward['comparisons'][0]['observed_mean'], eval_reversed['comparisons'][0]['observed_mean'])
        self.assertEqual(eval_forward['comparisons'][1]['observed_mean'], eval_reversed['comparisons'][1]['observed_mean'])

    def test_validation_errors_and_empty_window_warning(self):
        y_entry, v_entry = self.presenter.load_chemical_operating_window_demo()
        # 1. Invalid bounds (lower >= upper, or no bounds)
        with self.assertRaises(ValueError):
            evaluate_operating_window(
                self.presenter.worksheet,
                [dict(model_recipe=y_entry['recipe'], lower=90.0, upper=85.0)],
                0, 1,
            )
        with self.assertRaises(ValueError):
            evaluate_operating_window(
                self.presenter.worksheet,
                [dict(model_recipe=y_entry['recipe'])],
                0, 1,
            )

        # 2. Impossible spec -> empty_window=True with explicit warning
        impossible = evaluate_operating_window(
            self.presenter.worksheet,
            [dict(model_recipe=y_entry['recipe'], lower=150.0, upper=None)],
            0, 1,
            options=dict(grid_size=9),
        )
        self.assertTrue(impossible['empty_window'])
        self.assertTrue(any('empty operating window' in w.lower() for w in impossible['warnings']))

        # 3. Duplicate / missing RunID errors on evaluation
        specs, opts = chemical_operating_window_defaults(y_entry['recipe'], v_entry['recipe'])
        ow_res = evaluate_operating_window(self.presenter.worksheet, specs, 0, 1, options=opts)
        run_ws, plan = create_confirmation_plan(self.presenter.worksheet, ow_res, replicates=2)
        simulate_chemical_confirmation_responses(run_ws, seed=55)

        dup_ws = Worksheet('Dup', [Column(c.name, c.kind, list(c.values)) for c in run_ws.columns])
        dup_ws.columns[0].values[1] = dup_ws.columns[0].values[0]
        with self.assertRaises(ValueError):
            evaluate_confirmation_runs(plan, dup_ws)

        miss_ws = Worksheet('Miss', [Column(c.name, c.kind, list(c.values[:-1])) for c in run_ws.columns])
        with self.assertRaises(ValueError):
            evaluate_confirmation_runs(plan, miss_ws)

    def test_offscreen_dialogs_viewcube_toolbar_and_mpx_roundtrip(self):
        win = ModernWindow(self.presenter)
        try:
            with patch.object(self.presenter, 'load_chemical_operating_window_demo', wraps=self.presenter.load_chemical_operating_window_demo):
                win.load_chemical_operating_window_demo()
            self.assertTrue(win.operating_window_actions['analyze_response_surface'].isEnabled())

            # Dialog Cancel safety
            hist_before = len(self.presenter.history)
            dlg_cancel = OperatingWindowDialog(win, 'response_surface')
            dlg_cancel.reject()
            self.assertEqual(len(self.presenter.history), hist_before)

            # Dialog accept configuring chemical operating window bounds & drift
            dlg = OperatingWindowDialog(win, 'response_surface')
            dlg.set_response_spec(0, included=True, lower='86', upper='', target='91.5', goal='maximize')
            dlg.set_response_spec(1, included=True, lower='18', upper='26', target='22', goal='target')
            dlg.pred_table.item(0, 3).setText('3.0')
            dlg.pred_table.item(1, 3).setText('0.15')
            dlg.validate()
            ow_entry = dlg.entry
            self.assertIsNotNone(ow_entry)
            self.assertEqual(ow_entry['result']['analysis'], 'operating_window_3d')

            # Verify Graph tab shows 3D Operating Window with ViewCube & Create Confirmation Runs toolbar button
            win.show_result(ow_entry, target_tab='Graph')
            _APP.processEvents()
            page = win.result_tabs.currentWidget()
            frame = page.content.findChild(GraphFrame)
            self.assertIsNotNone(frame)
            create_btn = frame.findChild(QToolButton, 'operatingWindowCreateConfirmation')
            self.assertIsNotNone(create_btn)

            chart = frame.chart
            chart.resize(760, 520)
            img1 = chart.grab()
            self.assertFalse(img1.isNull())
            chart.set_cad_orientation(45.0, 35.3)
            _APP.processEvents()
            img2 = chart.grab()
            self.assertFalse(img2.isNull())
            with tempfile.TemporaryDirectory() as tmp_imgs:
                p1 = Path(tmp_imgs) / 'view1.png'
                p2 = Path(tmp_imgs) / 'view2.png'
                self.assertTrue(img1.save(str(p1)))
                self.assertTrue(img2.save(str(p2)))
                self.assertNotEqual(p1.read_bytes(), p2.read_bytes())

            # Create Confirmation Plan via dialog, simulate responses, and evaluate via dialog
            plan_dlg = ConfirmationPlanDialog(win, ow_entry)
            plan_dlg.chk_robust.setChecked(True)
            plan_dlg.chk_optimum.setChecked(True)
            plan_dlg.rep_spin.setValue(3)
            plan_dlg.validate()
            self.assertIsNotNone(plan_dlg.entry)
            self.assertEqual(self.presenter.worksheet.name, 'Confirmation_Runs')

            simulate_chemical_confirmation_responses(self.presenter.worksheet, seed=101)
            eval_dlg = ConfirmationEvaluateDialog(win, plan_dlg.entry)
            eval_dlg.validate()
            eval_entry = eval_dlg.entry
            self.assertIsNotNone(eval_entry)

            # Render Confirmation Evaluation chart to PNG and verify non-empty
            eval_chart = ChartWidget(eval_entry)
            eval_chart.resize(720, 480)
            eval_img = eval_chart.grab()
            self.assertFalse(eval_img.isNull())

            # Multi-worksheet .mpx save -> reopen -> recipe rerun
            with tempfile.TemporaryDirectory() as tmp:
                mpx_path = Path(tmp) / 'operating_window_flagship.mpx'
                png_path = Path(tmp) / 'ow_surface.png'
                self.assertTrue(eval_img.save(str(png_path)))
                self.assertFalse(QImage(str(png_path)).isNull())

                self.presenter.workspace = win._workspace.snapshot()
                self.presenter.save(mpx_path)

                reloaded = Presenter()
                reloaded.load(mpx_path)
                saved_ow = next(e for e in reloaded.history if e.get('result', {}).get('analysis') == 'operating_window_3d')
                saved_eval = next(e for e in reloaded.history if e.get('result', {}).get('analysis') == 'confirmation_evaluation')

                # Rerun operating_window_3d on source sheet & evaluate_confirmation_runs on Confirmation_Runs
                reloaded.select_worksheet(0)
                rerun_ow = recipes.run(reloaded, saved_ow['recipe'])
                self.assertEqual(rerun_ow['result']['robust_setting']['x'], saved_ow['result']['robust_setting']['x'])

                reloaded.select_worksheet(1)
                rerun_eval = recipes.run(reloaded, saved_eval['recipe'])
                self.assertEqual(rerun_eval['result']['comparisons'][0]['observed_mean'], saved_eval['result']['comparisons'][0]['observed_mean'])
        finally:
            self.presenter.dirty = False
            win.close()
            win.deleteLater()
            _APP.processEvents()


if __name__ == '__main__':
    unittest.main()
