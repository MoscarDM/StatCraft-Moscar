import tempfile
import unittest
from pathlib import Path
from statcraft.app import Presenter,format_entry
from statcraft._mpx_fixture import write_factorial_fixture


class FactorialIntegrationTests(unittest.TestCase):
    def test_replicated_factorial_workflow_and_saved_plots(self):
        presenter = Presenter()
        design = self._factorial_fixture(presenter)
        self.assertEqual(design['result']['runs'], 8)
        self.assertEqual(presenter.worksheet.columns[1].values, list(range(1, 9)))
        self.assertNotEqual(presenter.worksheet.columns[0].values, list(range(1, 9)))
        entry = presenter.analyze_factorial(6, [4, 5], confidence=.90)
        fit = entry['result']
        self.assertEqual(fit['factor_terms'], ['A', 'B', 'A*B'])
        for row, expected in zip(fit['coefficients'], [20, 3, 2, 1], strict=True):
            self.assertAlmostEqual(row['estimate'], expected)
        for row, expected in zip(fit['effects'], [6, 4, 2], strict=True):
            self.assertAlmostEqual(row['effect'], expected)
            self.assertAlmostEqual(row['t'], expected)
        self.assertEqual((fit['df_regression'], fit['df_error']), (3, 4))
        self.assertAlmostEqual(fit['ss_regression'], 112)
        self.assertAlmostEqual(fit['ss_error'], 8)
        self.assertIn('Estimated Effects', format_entry(entry))

        expected_means = {
            (10, 100): 16, (15, 100): 18, (20, 100): 20,
            (10, 200): 18, (15, 200): 22, (20, 200): 26,
        }
        for row, fitted, residual in zip(fit['row_indices'], fit['fitted'], fit['residuals'], strict=True):
            _, run_order, _, _, a, b, response = presenter.worksheet.row(row)
            self.assertEqual(run_order, row + 1)
            self.assertAlmostEqual(fitted, expected_means[a, b])
            self.assertAlmostEqual(residual, response - expected_means[a, b])

        plot_entry = presenter.factorial_plots(entry['recipe'])
        plots = plot_entry['result']
        for series, expected in zip(plots['main_effects'], [(17, 23), (18, 22)], strict=True):
            self.assertAlmostEqual(series['key_points'][0]['fit'], expected[0])
            self.assertAlmostEqual(series['key_points'][-1]['fit'], expected[1])
        interaction = plots['interactions'][0]
        for series in interaction['series']:
            for a, fitted in zip(series['anchor_x'], series['anchor_fits'], strict=True):
                self.assertAlmostEqual(fitted, expected_means[a, series['level_value']])

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path = Path(folder) / 'replicated.mpx'
            presenter.save(path)
            reopened = Presenter()
            reopened.load(path)
            for original in (entry, plot_entry):
                action = original['recipe']['action']
                saved = next(item for item in reopened.history if item.get('recipe', {}).get('action') == action)
                self.assertEqual(saved['result'], original['result'])
                self.assertEqual(reopened.rerun_result(saved)['result'], saved['result'])

    def test_saturated_factorial_leaves_worksheet_and_history_intact(self):
        from PySide6.QtWidgets import QApplication, QDialog
        from statcraft.doe_dialogs import AnalyzeFactorialDialog

        app = QApplication.instance() or QApplication([])
        presenter = Presenter()
        design = self._factorial_fixture(presenter, replicates=1)
        worksheet = presenter.worksheet
        responses = list(worksheet.columns[6].values)

        dialog = AnalyzeFactorialDialog(None, worksheet)
        self.addCleanup(dialog.deleteLater)
        dialog.response.setText('C7')
        dialog.validate()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIn('residual degrees of freedom', dialog.error.text())
        with self.assertRaisesRegex(ValueError, 'residual degrees of freedom'):
            presenter.analyze_factorial(6, [4, 5])

        self.assertIs(presenter.worksheet, worksheet)
        self.assertEqual(worksheet.columns[6].values, responses)
        self.assertEqual(presenter.history, [design])
        app.processEvents()

    @staticmethod
    def _factorial_fixture(presenter, replicates=2, noise=True):
        factors = [
            {'name': 'A', 'low': 10, 'high': 20},
            {'name': 'B', 'low': 100, 'high': 200},
        ]
        design = presenter.create_factorial(factors, replicates=replicates, seed=42)
        presenter.add_column('Yield')
        for row in range(presenter.worksheet.row_count):
            std_order, _, _, _, actual_a, actual_b, _ = presenter.worksheet.row(row)
            a = (actual_a - 15) / 5
            b = (actual_b - 150) / 50
            deviation = (-1 if std_order <= 4 else 1) if noise else 0
            presenter.set_cell(row, 6, str(20 + 3 * a + 2 * b + a * b + deviation))
        return design

    def test_factorial_result_opens_pareto_and_residual_graphs(self):
        from unittest.mock import patch
        from PySide6.QtCore import QSettings
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QApplication, QDialog
        from statcraft.doe_dialogs import AnalyzeFactorialDialog
        from statcraft.graph_frame import GraphFrame
        from statcraft.modern_app import ModernWindow

        app = QApplication.instance() or QApplication([])
        presenter = Presenter()
        self._factorial_fixture(presenter)
        settings_dir = self.enterContext(tempfile.TemporaryDirectory(dir=Path(__file__).parent))
        settings = QSettings(str(Path(settings_dir) / 'factorial.ini'), QSettings.Format.IniFormat)
        self.enterContext(patch('statcraft.modern_app.QSettings', return_value=settings))
        window = ModernWindow(presenter)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        self.addCleanup(setattr, presenter, 'dirty', False)
        self.addCleanup(setattr, presenter, '_results_dirty', False)
        action = next(item for item in window.findChildren(QAction) if item.text() == 'Analyze Factorial Design…')
        with patch.object(AnalyzeFactorialDialog, 'exec', return_value=QDialog.DialogCode.Rejected):
            action.trigger()
        self.assertEqual(len(presenter.history), 1)

        def confirm_analysis(dialog):
            dialog.response.setText('C7')
            dialog.confidence = .90
            dialog.validate()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted, dialog.error.text())
            return dialog.result()

        with patch.object(AnalyzeFactorialDialog, 'exec', confirm_analysis):
            action.trigger()
        result = presenter.history[-1]
        self.assertIs(window.selected_entry, result)
        window.show_result(result, target_tab='Effects Pareto')

        tabs = {window.result_tabs.tabText(index): index for index in range(window.result_tabs.count())}
        self.assertIn('Effects Pareto', tabs)
        self.assertEqual(window.result_tabs.currentIndex(), tabs['Effects Pareto'])
        pareto = window.result_tabs.widget(tabs['Effects Pareto']).content.findChild(GraphFrame)
        self.assertIs(window._active_graph_frame, pareto)
        self.assertFalse(pareto.capture().isNull())
        self.assertEqual([item['term'] for item in pareto.chart.result['pareto_effects']], ['A', 'B', 'A*B'])
        for item, magnitude in zip(pareto.chart.result['pareto_effects'], [6, 4, 2], strict=True):
            self.assertAlmostEqual(item['effect'], magnitude)
        self.assertAlmostEqual(pareto.chart.result['t_crit'], 2.1318467863)
        self.assertAlmostEqual(pareto.chart.result['alpha'], .10)

        window.result_tabs.setCurrentIndex(tabs['Residual Plots'])
        residuals = window.result_tabs.currentWidget().content.findChild(GraphFrame)
        self.assertIs(window._active_graph_frame, residuals)
        self.assertFalse(residuals.capture().isNull())
        self.assertEqual(residuals.chart.observation_order, list(range(1, 9)))
        self.assertEqual(residuals.chart.fitted, result['result']['fitted'])
        self.assertEqual(residuals.chart.residuals, result['result']['residuals'])

        window.set_zoom(140)
        window.result_tabs.setCurrentIndex(tabs['Effects Pareto'])
        window.set_zoom(180)
        window.show_result(presenter.history[0])
        window.show_result(result)
        self.assertEqual(window.result_tabs.tabText(window.result_tabs.currentIndex()), 'Effects Pareto')
        self.assertEqual(window._zoom_percent, 180)
        window._workspace.choose_view('Residual Plots')
        self.assertEqual(window._zoom_percent, 140)
        with patch('statcraft.modern_app.QFileDialog.getExistingDirectory', return_value=settings_dir):
            window.export_all_graphs_dialog()
        exports = list(Path(settings_dir).glob('*.png'))
        self.assertEqual(len(exports), 3)
        self.assertTrue(any(path.name.endswith('_Effects Pareto.png') for path in exports))
        self.assertTrue(any(path.name.endswith('_Residual Plots.png') for path in exports))

        window._workspace.choose_view('Effects Pareto')
        presenter.workspace = window._workspace.snapshot()
        self.assertEqual(presenter.workspace['views'][result['entry_id']]['view'], 'Graph')
        path = Path(settings_dir) / 'factorial-output.mpx'
        presenter.save(path)
        presenter.load(path)
        window._workspace.restore(presenter.workspace)
        self.assertEqual(window.result_tabs.tabText(window.result_tabs.currentIndex()), 'Effects Pareto')
        self.assertEqual(window._zoom_percent, 180)
        window._workspace.choose_view('Report')
        self.assertIsNone(window._active_graph_frame)
        result = window.selected_entry

        window.show_result(presenter.factorial_plots(result['recipe']), target_tab='Graph')
        model_plots = window.result_tabs.currentWidget().content.findChild(GraphFrame)
        self.assertIsNone(model_plots.chart.error)
        self.assertFalse(model_plots.capture().isNull())

        window.show_result(presenter.analyze_factorial(6, [4, 5], plot_residuals=False))
        tabs = [window.result_tabs.tabText(index) for index in range(window.result_tabs.count())]
        self.assertIn('Effects Pareto', tabs)
        self.assertNotIn('Graph', tabs)
        self.assertNotIn('Residual Plots', tabs)

        presenter.set_cell(2, 6, '')
        window.show_result(presenter.analyze_factorial(6, [4, 5]), target_tab='Residual Plots')
        residuals = window.result_tabs.currentWidget().content.findChild(GraphFrame)
        self.assertEqual(residuals.chart.observation_order, [1, 2, 4, 5, 6, 7, 8])

        self._factorial_fixture(presenter, noise=False)
        window.show_result(presenter.analyze_factorial(6, [4, 5]))
        tabs = [window.result_tabs.tabText(index) for index in range(window.result_tabs.count())]
        self.assertNotIn('Effects Pareto', tabs)
        self.assertNotIn('Residual Plots', tabs)
        self.assertIn('Graph', tabs)
        window.show_result(presenter.analyze_factorial(6, [4, 5], plot_residuals=False))
        self.assertIsNone(window._active_graph_frame)
        app.processEvents()

    def test_creation_is_transactional_and_metadata_persists(self):
        p=Presenter(); before=p.worksheet
        with self.assertRaises(ValueError): p.create_factorial([dict(name='A',low=1,high=1)])
        self.assertIs(p.worksheet,before)
        factors=[dict(name='A',low=-1,high=1),dict(name='B',low=10,high=20)]
        entry=p.create_factorial(factors,replicates=2,seed=42)
        self.assertEqual(entry['result']['runs'],8)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path=Path(folder)/'design.statcraft'; p.save(path); q=Presenter(); q.load(path)
            self.assertEqual(q.worksheet.metadata['doe'],p.worksheet.metadata['doe'])
            self.assertEqual(q.worksheet.columns,p.worksheet.columns)

    def test_mpx_factorial_effects_save_rerun_and_dependencies(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            source,target=Path(folder)/'in.mpx',Path(folder)/'copy.mpx'; write_factorial_fixture(source)
            original=source.read_bytes(); p=Presenter(); p.load(source)
            entry=p.analyze_factorial(2,[0,1],plot_residuals=False,show_factor_coding=False)
            self.assertEqual([round(r['effect'],8) for r in entry['result']['effects']],[4,-6,3])
            self.assertIn('Estimated Effects',format_entry(entry)); self.assertNotIn('Factor Coding',format_entry(entry))
            p.save(target); self.assertEqual(source.read_bytes(),original)
            q=Presenter(); q.load(target); entry=next(e for e in q.history if e.get('recipe',{}).get('action')=='analyze_factorial')
            q.select_worksheet(0); fresh=q.rerun_result(entry)
            self.assertEqual(q.native_project.active_index,1); self.assertEqual(fresh['result'],entry['result'])
            q.set_cell(0,2,'12'); self.assertTrue(q.result_stale(fresh))
            self.assertFalse(q.result_stale(q.rerun_result(fresh)))

    def test_failed_analysis_does_not_add_result(self):
        p=Presenter()
        with self.assertRaises(ValueError): p.analyze_factorial(0,[0,1])
        self.assertEqual(p.history,[])

    def test_multiple_blocks_presenter_roundtrip_and_rerun(self):
        p = Presenter()
        factors = [dict(name='A', low=-1, high=1), dict(name='B', low=-1, high=1)]
        entry = p.create_factorial(factors, replicates=2, blocks=2, seed=123, randomize=False)
        self.assertEqual(entry['result']['blocks'], 2)
        # Add a response column with a block effect
        y = [10.0 + 2.0 * row[4] - 3.0 * row[5] + (4.0 if row[3] == 1 else -4.0) for row in (p.worksheet.row(i) for i in range(p.worksheet.row_count))]
        from statcraft.model import Column
        p.worksheet.columns.append(Column('Response', values=y))
        fit_entry = p.analyze_factorial(6, [4, 5], include_blocks=True)
        self.assertTrue(fit_entry['result']['include_blocks'])
        self.assertIn('Blocks', fit_entry['result']['terms'])
        # Save and reload
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path = Path(folder) / 'blocks_project.statcraft'
            p.save(path)
            q = Presenter()
            q.load(path)
            self.assertEqual(q.worksheet.metadata['doe']['blocks'], 2)
            rerun = q.rerun_result(fit_entry)
            self.assertEqual(rerun['result']['include_blocks'], True)

