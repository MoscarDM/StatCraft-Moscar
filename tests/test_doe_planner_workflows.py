"""DOE planner orchestration, project transactions and source-preserving saved data."""
import copy
from pathlib import Path
import unittest
from test_mpx import scratch
from statcraft.app import Presenter,format_entry
from statcraft.model import Worksheet,Column
from statcraft.doe_planner import build_plan

class DOEPlannerWorkflows(unittest.TestCase):
    def test_preserves_existing_project_and_unique_tabs_through_mpx(self):
        p=Presenter();p.worksheet=Worksheet('Original',[Column('Data',values=[1,2,3])]);old=p.describe_column(0)
        factors=[dict(name='A',low=-1,high=1),dict(name='B',low=2,high=4)]
        a=p.create_doe_plan(kind='full_factorial',factors=factors,name='Plan')
        b=p.create_doe_plan(kind='full_factorial',factors=factors,name='Plan')
        self.assertEqual([s.name for s in p.native_project.worksheets],['Original','Plan','Plan (2)'])
        self.assertEqual(p.rerun_result(old)['result']['count'],3)
        self.assertIn('Factorial',format_entry(a))
        with scratch() as temp:
            expected=[list(s.columns[0].values) for s in p.native_project.worksheets]
            path=Path(temp)/'plans.mpx';p.save(path);q=Presenter();q.load(path)
            self.assertEqual([s.columns[0].values for s in q.native_project.worksheets],expected)
            self.assertEqual(q.native_project.worksheets[1].metadata['doe']['planner_configuration']['kind'],'full_factorial')

    def test_invalid_design_does_not_reset_dirty_project_or_history(self):
        p=Presenter();p.worksheet.columns[0].values=[7,8];p.describe_column(0)
        before=(copy.deepcopy(p.worksheet),copy.deepcopy(p.history),p.dirty)
        with self.assertRaises(ValueError):p.create_doe_plan(kind='simplex_centroid',factors=[dict(name='A',low=.9,high=1),dict(name='B',low=.8,high=1)])
        self.assertEqual((p.worksheet,p.history,p.dirty),before)
        self.assertIsNone(p.native_project)

    def test_response_surface_centers_count_actual_replicates(self):
        p=Presenter();entry=p.create_doe_plan(kind='central_composite',factors=[dict(name='A',low=-1,high=1),dict(name='B',low=-1,high=1)],centers=2,replicates=3)
        self.assertEqual(entry['result']['center_runs'],6)
        self.assertEqual(sum(v==0 for v in p.worksheet.columns[2].values),6)

    def test_configuration_copied_and_block_restrictions_explicit(self):
        parameters=dict(kind='general_factorial',factors=[dict(name='A',kind='number',levels=[0,1,2]),dict(name='B',kind='text',levels=['X','Y'])])
        sheet=build_plan(**parameters);parameters['factors'][0]['levels'][0]=999
        self.assertEqual(sheet.metadata['doe']['planner_configuration']['factors'][0]['levels'][0],0)
        with self.assertRaises(ValueError):build_plan(**parameters,replicates=1,blocks=2)

    def test_blocked_response_surface_end_to_end_create_analyze_save_reopen(self):
        p = Presenter()
        factors = [dict(name='Temp', low=100.0, high=200.0), dict(name='Time', low=10.0, high=30.0)]
        target, design_entry = p.create_response_surface(
            factors, kind='central_composite', blocks=2, block_replicates=False,
            replicates=1, centers=4, randomize=False, seed=7, name='BlockedCCD'
        )
        self.assertIs(target, p)
        self.assertEqual(design_entry['result']['blocks'], 2)
        # Quadratic + block signal in natural units
        y_vals = []
        for i in range(p.worksheet.row_count):
            row = p.worksheet.row(i)
            blk = row[3]
            x1 = (row[4] - 150.0) / 50.0
            x2 = (row[5] - 20.0) / 10.0
            y_vals.append(50.0 + 4.0 * x1 - 3.0 * x2 - 2.5 * x1 * x1 + 1.5 * x1 * x2 + (2.0 if blk == 1 else -2.0))
        p.worksheet.columns.append(Column('Yield', values=y_vals))
        fit = p.analyze_response_surface(6, [4, 5], block_index=3)
        self.assertGreater(fit['result']['r_squared'], 0.99)
        self.assertEqual(len(fit['result']['block_levels']), 2)
        self.assertTrue(any('Blocks' in c.get('name', '') for c in fit['result']['coefficients']))
        with scratch() as temp:
            path = Path(temp) / 'blocked_rsm.mpx'
            p.save(path)
            q = Presenter()
            q.load(path)
            self.assertEqual(q.worksheet.metadata['doe']['blocks'], 2)
            saved_fit = next(e for e in q.history if e.get('recipe', {}).get('action') == 'analyze_response_surface')
            rerun = q.rerun_result(saved_fit)
            self.assertAlmostEqual(rerun['result']['r_squared'], fit['result']['r_squared'], places=8)

    def test_screening_dsd_and_nine_factor_fractional_end_to_end_save_reopen(self):
        # 1. Definitive Screening Design: create -> analyze -> save/reopen
        p = Presenter()
        dsd_factors = [dict(name=f'F{i+1}', low=-1.0, high=1.0) for i in range(5)]
        p.create_definitive_screening_design(dsd_factors, extra_centers=1, randomize=False, seed=11)
        y_dsd = [10.0 + 3.0 * p.worksheet.row(i)[4] - 2.0 * p.worksheet.row(i)[5] for i in range(p.worksheet.row_count)]
        p.worksheet.columns.append(Column('Response', values=y_dsd))
        dsd_fit = p.analyze_definitive_screening_design(len(p.worksheet.columns) - 1, selection='main_effects')
        self.assertEqual(dsd_fit['result']['analysis'], 'definitive_screening_analysis')
        with scratch() as temp:
            path = Path(temp) / 'dsd_screening.statcraft'
            p.save(path)
            q = Presenter()
            q.load(path)
            self.assertEqual(q.worksheet.metadata['doe']['design'], 'definitive_screening')
            reopened_dsd = q.analyze_definitive_screening_design(len(q.worksheet.columns) - 1, selection='main_effects')
            self.assertEqual(reopened_dsd['result']['analysis'], 'definitive_screening_analysis')
            self.assertAlmostEqual(reopened_dsd['result']['r2'], dsd_fit['result']['r2'], places=8)
            self.assertEqual(reopened_dsd['result']['terms'], dsd_fit['result']['terms'])

        # 2. 9-factor 32-run Resolution IV fractional screening: create -> analyze -> save/reopen
        from statcraft.doe_catalog_designs import two_level_design_spec
        spec = two_level_design_spec(num_factors=9, runs=32)
        p2 = Presenter()
        fac9 = [dict(name=f'X{i+1}', low=-1.0, high=1.0) for i in range(9)]
        p2.create_factorial(fac9, generators=spec['generators'], randomize=False, seed=3)
        y_frac = [20.0 + 5.0 * p2.worksheet.row(i)[4] - 4.0 * p2.worksheet.row(i)[12] for i in range(p2.worksheet.row_count)]
        p2.worksheet.columns.append(Column('Response', values=y_frac))
        frac_fit = p2.analyze_factorial(13, list(range(4, 13)), max_order=1)
        self.assertEqual(frac_fit['result']['design_resolution'], 4)
        with scratch() as temp:
            path = Path(temp) / 'frac9_screening.statcraft'
            p2.save(path)
            q2 = Presenter()
            q2.load(path)
            self.assertEqual(q2.worksheet.metadata['doe']['resolution'], 4)
            reopened_frac = q2.analyze_factorial(13, list(range(4, 13)), max_order=1)
            self.assertEqual(reopened_frac['result']['design_resolution'], 4)
            self.assertEqual(reopened_frac['result']['effects'], frac_fit['result']['effects'])
