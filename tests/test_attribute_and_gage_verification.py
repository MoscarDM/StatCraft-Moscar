"""Tests for R Workbench and Excel verification across Xbar-S, Attribute charts, and Crossed Gage R&R."""
import math
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STATCRAFT_TESTING', '1')

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from scipy.stats import f as f_dist

from statcraft.app import Presenter
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.r_verification import build_script as build_r_script, supports as supports_r, tab_name
from statcraft.xlsx_verification import supports as supports_xlsx, write_verification
from tests.test_xlsx_quality_verification import ExcelFormulaEvaluator, _NA


class ExtendedExcelFormulaEvaluator(ExcelFormulaEvaluator):
    """Add AVERAGEIF, FDIST, and INT support for Crossed Gage R&R verification workbooks."""

    def _call_func(self, sheet, name, raw_args):
        if name == 'INT':
            v = self._eval_tokens(sheet, raw_args[0])
            return _NA if v is _NA else math.floor(float(v))
        if name == 'FDIST':
            x = self._eval_tokens(sheet, raw_args[0])
            d1 = self._eval_tokens(sheet, raw_args[1])
            d2 = self._eval_tokens(sheet, raw_args[2])
            if x is _NA or d1 is _NA or d2 is _NA:
                return _NA
            fx = float(x)
            if fx <= 0:
                return 1.0
            return float(f_dist.sf(fx, float(d1), float(d2)))
        if name == 'AVERAGEIF':
            cond_vals = self._expand_range(sheet, raw_args[0][0])
            crit = self._eval_tokens(sheet, raw_args[1])
            avg_toks = raw_args[2] if len(raw_args) > 2 else raw_args[0]
            avg_vals = self._expand_range(sheet, avg_toks[0])
            matched = [
                float(av)
                for cv, av in zip(cond_vals, avg_vals)
                if self._matches_crit(cv, crit) and self._is_num(av)
            ]
            if not matched:
                return _NA
            return sum(matched) / len(matched)
        return super()._call_func(sheet, name, raw_args)


class AttributeAndGageVerificationTests(unittest.TestCase):
    def _find_rscript(self):
        return os.environ.get('STATCRAFT_QA_RSCRIPT') or shutil.which('Rscript')

    def _verify_r(self, script, expect_pass=True):
        executable = self._find_rscript()
        if not executable:
            self.skipTest('Rscript not available')
        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / 'verify.R'
            script_path.write_text(script, encoding='utf-8')
            proc = subprocess.run(
                [executable, '--vanilla', str(script_path)],
                cwd=tmp,
                capture_output=True,
                encoding='utf-8',
                errors='replace',
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            if expect_pass:
                self.assertIn('Verification: PASS', proc.stdout)
                self.assertTrue((Path(tmp) / 'Rplots.pdf').is_file())
            else:
                self.assertIn('Verification: DIFFERENCES FOUND', proc.stdout)
            return proc.stdout

    def test_attribute_charts_r_workbench_variants_tamper_stale_and_ui(self):
        p = Presenter()
        p.worksheet = Worksheet('AttrR', [
            Column('DefectsP', 'number', [2, 3, 1, 18, 2, 4, 3]),
            Column('SizesP', 'number', [100, 120, 80, 150, 100, 110, 95]),
            Column('DefectsC', 'number', [3, 5, 2, 12, 4, 6, 3]),
            Column('UnitsU', 'number', [2.0, 2.5, 1.5, 3.0, 2.0, 2.5, 2.0]),
            Column('LaneyCnt', 'number', [12, 38, 15, 42, 10, 44, 14]),
            Column('LaneyN', 'number', [200, 220, 190, 250, 210, 230, 200]),
        ])
        e_p = p.attribute_control_chart({
            'chart_type': 'P',
            'variables': [0],
            'is_subgroup_col': True,
            'subgroup_col_idx': 1,
            'options': {'omit_subgroups': [4], 'k_sigma': 2.5},
        })
        e_np = p.attribute_control_chart({
            'chart_type': 'NP',
            'variables': [0],
            'is_subgroup_col': False,
            'subgroup_size': 100,
        })
        e_c = p.attribute_control_chart({
            'chart_type': 'C',
            'variables': [2],
        })
        e_u = p.attribute_control_chart({
            'chart_type': 'U',
            'variables': [2],
            'is_subgroup_col': True,
            'subgroup_col_idx': 3,
            'options': {'display_lower': False},
        })
        e_pp = p.attribute_control_chart({
            'chart_type': "P'",
            'variables': [4],
            'is_subgroup_col': True,
            'subgroup_col_idx': 5,
        })
        e_up = p.attribute_control_chart({
            'chart_type': "U'",
            'variables': [4],
            'is_subgroup_col': True,
            'subgroup_col_idx': 5,
        })

        for entry in (e_p, e_np, e_c, e_u, e_pp, e_up):
            self.assertTrue(supports_r(entry))
            self.assertEqual(tab_name(entry), 'Verify_Attribute.R')
            self._verify_r(build_r_script(p, entry), expect_pass=True)

        # Tampered center triggers DIFFERENCES FOUND
        e_p['result']['center'] += 0.05
        self._verify_r(build_r_script(p, e_p), expect_pass=False)

        # MPX roundtrip + UI Output Options -> Verify in R Workbench
        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / 'attr_r.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            saved_c = next(e for e in reopened.history if e['entry_id'] == e_c['entry_id'])
            app = QApplication.instance() or QApplication([])
            win = ModernWindow(reopened)
            try:
                act = next(
                    a for a in win.build_output_context_menu(saved_c).actions()
                    if a.text().startswith('Verify in R Workbench')
                )
                act.trigger()
                tab_idx = win.r_workbench.editor_tabs.currentIndex()
                self.assertEqual(win.r_workbench.editor_tabs.tabText(tab_idx), 'Verify_Attribute.R')
                self.assertIn('Attribute Control Chart', win.r_workbench.editor.toPlainText())

                # Stale rejection
                reopened.worksheet.columns[2].values[0] = 50
                with patch.object(QMessageBox, 'information') as info:
                    act.trigger()
                self.assertIn('Rerun', info.call_args.args[2])
            finally:
                p.dirty = False
                p._results_dirty = False
                reopened.dirty = False
                reopened._results_dirty = False
                win.close()
                win.deleteLater()
                app.processEvents()

    def test_gage_rr_r_workbench_pooled_unpooled_tolerance_and_ui(self):
        # Dataset A: Pooled interaction (replicates close within part/operator)
        rows_pooled = [
            (1, 'A', 10.0), (1, 'A', 10.1), (1, 'B', 10.2), (1, 'B', 10.1),
            (2, 'A', 12.0), (2, 'A', 12.1), (2, 'B', 12.2), (2, 'B', 12.2),
            (3, 'A', 14.0), (3, 'A', 13.9), (3, 'B', 14.1), (3, 'B', 14.2),
        ]
        # Dataset B: Strong significant Part*Operator interaction (unpooled)
        rows_unpooled = [
            ('P*1', 'Op_1', 10.0), ('P*1', 'Op_1', 10.02), ('P*1', 'Op_2', 14.0), ('P*1', 'Op_2', 14.02),
            ('P*2', 'Op_1', 14.0), ('P*2', 'Op_1', 14.01), ('P*2', 'Op_2', 10.0), ('P*2', 'Op_2', 10.03),
            ('P*3', 'Op_1', 12.0), ('P*3', 'Op_1', 12.01), ('P*3', 'Op_2', 12.1), ('P*3', 'Op_2', 12.12),
        ]

        p = Presenter()
        p.worksheet = Worksheet('GageQA', [
            Column('PartA', 'text', [str(r[0]) for r in rows_pooled]),
            Column('OpA', 'text', [r[1] for r in rows_pooled]),
            Column('MeasA', 'number', [r[2] for r in rows_pooled]),
            Column('PartB', 'text', [r[0] for r in rows_unpooled]),
            Column('OpB', 'text', [r[1] for r in rows_unpooled]),
            Column('MeasB', 'number', [r[2] for r in rows_unpooled]),
        ])
        e_pool = p.gage_rr(2, 0, 1, options={'tolerance': 6.0, 'process_stdev': 1.5, 'interaction_alpha': 0.05})
        e_unpool = p.gage_rr(5, 3, 4, options={'study_multiplier': 5.15, 'remove_interaction': True, 'interaction_alpha': 0.05})
        self.assertTrue(e_pool['result']['interaction']['pooled'])
        self.assertFalse(e_unpool['result']['interaction']['pooled'])

        for entry in (e_pool, e_unpool):
            self.assertTrue(supports_r(entry))
            self.assertEqual(tab_name(entry), 'Verify_GageRR.R')
            self._verify_r(build_r_script(p, entry), expect_pass=True)

        # Altered reference triggers DIFFERENCES FOUND
        e_unpool['result']['variance_components'][0]['variance'] += 0.25
        self._verify_r(build_r_script(p, e_unpool), expect_pass=False)

    def test_xbar_s_attribute_and_gage_rr_excel_workbooks(self):
        groups = [
            [10.0, 10.2, 9.8, 10.0],
            [10.1, 9.9, 10.0],
            [10.0, 10.3, 9.7, 10.1, 9.9],
            [16.0, 17.0],
            [10.2, 9.8, 10.1, 9.9],
        ]
        flat_vals = [v for g in groups for v in g]
        lots = [f'Lot{i + 1}' for i, g in enumerate(groups) for _ in g]

        p = Presenter()
        p.worksheet = Worksheet('AllExcelQA', [
            Column('Diam', 'number', flat_vals),
            Column('Lot', 'text', lots),
            Column('PDef', 'number', [2, 3, 1, 18, 2, 4]),
            Column('PSz', 'number', [100, 120, 80, 150, 100, 110]),
            Column('CDef', 'number', [3, 5, 2, 12, 4, 6]),
            Column('UExp', 'number', [2.0, 2.5, 1.5, 3.0, 2.0, 2.5]),
            Column('Part', 'text', ['P*1', 'P*1', 'P*1', 'P*1', 'P*2', 'P*2', 'P*2', 'P*2', 'P*3', 'P*3', 'P*3', 'P*3']),
            Column('Op', 'text', ['Op1', 'Op1', 'Op2', 'Op2', 'Op1', 'Op1', 'Op2', 'Op2', 'Op1', 'Op1', 'Op2', 'Op2']),
            Column('MeasPooled', 'number', [10.0, 10.1, 10.2, 10.1, 12.0, 12.1, 12.2, 12.2, 14.0, 13.9, 14.1, 14.2]),
            Column('MeasUnpool', 'number', [10.0, 10.02, 14.0, 14.02, 14.0, 14.01, 10.0, 10.03, 12.0, 12.01, 12.1, 12.12]),
            Column('EqD', 'number', [10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1]),
        ])

        xs_unequal = p.subgroup_control_chart(
            chart_type='xbar_s', stacked=True, response_index=0, factor_index=1,
            options={'k_sigma': 2.5, 'omit_subgroups': [4]},
        )
        xs_pooled = p.subgroup_control_chart(
            chart_type='xbar_s', stacked=True, response_index=0, factor_index=1,
            options={'estimation_method': 'pooled_stdev', 'unbiasing': True},
        )
        xs_equal_nounbias = p.subgroup_control_chart(
            chart_type='xbar_s', stacked=True, response_index=10, subgroup_size=3,
            options={'unbiasing': False},
        )
        e_p = p.attribute_control_chart({
            'chart_type': 'P', 'variables': [2], 'is_subgroup_col': True, 'subgroup_col_idx': 3,
            'options': {'omit_subgroups': [4]},
        })
        e_np = p.attribute_control_chart({'chart_type': 'NP', 'variables': [2], 'subgroup_size': 100})
        e_c = p.attribute_control_chart({'chart_type': 'C', 'variables': [4]})
        e_u = p.attribute_control_chart({'chart_type': 'U', 'variables': [4], 'is_subgroup_col': True, 'subgroup_col_idx': 5})
        e_pp = p.attribute_control_chart({'chart_type': "P'", 'variables': [2], 'is_subgroup_col': True, 'subgroup_col_idx': 3})
        e_grr_pool = p.gage_rr(8, 6, 7, options={'tolerance': 6.0, 'process_stdev': 1.5})
        e_grr_unpool = p.gage_rr(9, 6, 7, options={'study_multiplier': 5.15})

        self.assertFalse(supports_xlsx(e_pp))
        with self.assertRaisesRegex(ValueError, "Laney P'/U'"):
            write_verification(Path(tempfile.gettempdir()) / 'unused_laney.xlsx', p, e_pp)

        with tempfile.TemporaryDirectory() as tmp:
            cases = [
                ('xs_unequal.xlsx', xs_unequal, 'E2', 14.5, None, False),
                ('xs_pooled.xlsx', xs_pooled, 'E2', 14.5, None, False),
                ('xs_equal_nounbias.xlsx', xs_equal_nounbias, 'E2', 14.5, None, False),
                ('attr_p.xlsx', e_p, 'C2', 20, 150, False),
                ('attr_np.xlsx', e_np, 'C2', 15, 150, False),
                ('attr_c.xlsx', e_c, 'C2', 15, -1, False),
                ('attr_u.xlsx', e_u, 'C2', 20, -1, False),
                ('grr_pool.xlsx', e_grr_pool, 'D2', 15.0, None, True),
                ('grr_unpool.xlsx', e_grr_unpool, 'D2', 15.0, None, True),
            ]
            for fname, entry, edit_cell, new_val, bad_val, is_gage in cases:
                self.assertTrue(supports_xlsx(entry), fname)
                xlsx_path = write_verification(Path(tmp) / fname, p, entry)
                wb = load_workbook(xlsx_path, data_only=False)
                ev = ExtendedExcelFormulaEvaluator(wb)
                self.assertEqual(ev.cell('Verification', 'B7'), 'Valid', fname)
                self.assertEqual(ev.cell('Verification', 'B6'), 'PASS', fname)

                # Verify v121.2.18+ Excel chart placement & styling rules
                charts = wb['Verification']._charts
                self.assertGreaterEqual(len(charts), 1, fname)
                anchors = {str(ch.anchor._from.row) for ch in charts}
                self.assertTrue(all(int(r) >= 9 for r in anchors), f'{fname}: {anchors}')
                if not is_gage:
                    for ch in charts:
                        self.assertFalse(getattr(ch, 'smooth', False), fname)
                        self.assertEqual(ch.legend.position, 'b', fname)
                else:
                    self.assertEqual(len(charts), 2)
                    self.assertEqual(charts[0].legend.position, 'b')
                    self.assertFalse(charts[1].smooth)

                # Edit input -> DIFFERENCES FOUND; restore -> PASS; invalid -> Check inputs
                orig = wb['Inputs'][edit_cell].value
                wb['Inputs'][edit_cell].value = new_val
                ev.invalidate()
                self.assertEqual(ev.cell('Verification', 'B6'), 'DIFFERENCES FOUND', fname)
                wb['Inputs'][edit_cell].value = orig
                ev.invalidate()
                self.assertEqual(ev.cell('Verification', 'B6'), 'PASS', fname)
                wb['Inputs'][edit_cell].value = bad_val
                ev.invalidate()
                self.assertEqual(ev.cell('Verification', 'B7'), 'Check inputs', fname)

            # R 4.6.1 cross-check against workbook for Xbar-S, Attribute P, and Gage R&R
            rscript = self._find_rscript()
            if rscript:
                for tag, entry in (('xs', xs_unequal), ('p', e_p), ('grr', e_grr_pool)):
                    r_file = Path(tmp) / f'cross_{tag}.R'
                    r_file.write_text(build_r_script(p, entry), encoding='utf-8')
                    proc = subprocess.run([rscript, '--vanilla', str(r_file)], cwd=tmp, capture_output=True, text=True, timeout=30)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertIn('Verification: PASS', proc.stdout)

            # UI Output Options menu export for Attribute P and Gage R&R
            app = QApplication.instance() or QApplication([])
            win = ModernWindow(p)
            try:
                for label, entry in (('p', e_p), ('grr', e_grr_pool)):
                    out_path = Path(tmp) / f'ui_{label}.xlsx'
                    act = next(
                        a for a in win.build_output_context_menu(entry).actions()
                        if a.text().startswith('Export Excel Verification')
                    )
                    with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(out_path), '')):
                        act.trigger()
                    self.assertTrue(out_path.is_file(), label)
            finally:
                p.dirty = False
                p._results_dirty = False
                win.close()
                win.deleteLater()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
