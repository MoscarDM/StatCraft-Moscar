import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('visual_suite', Path(__file__).resolve().parents[1]/'scripts/visual_stress_suite.py')
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


class HarnessContractTests(unittest.TestCase):
    def test_preimported_settings_alias_and_scope_are_isolated_and_restored(self):
        from statcraft import modern_app, settings_scope
        from PySide6 import QtCore
        from contextlib import ExitStack
        original = modern_app.QSettings
        previous = settings_scope._sandbox_workspace
        def scenario(win, app, folder, quick):
            settings = modern_app.QSettings('StatCraft', 'StatCraft')
            self.assertEqual(Path(settings.fileName()).parent, folder)
            settings.setValue('visual-harness-sentinel', True)
            return {}
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            for name in ['_scenario_large_dataset','_scenario_dark_and_resize','_scenario_charts_and_tabs','_scenario_dialogs','_scenario_mpx_and_session']:
                stack.enter_context(patch.object(suite,name,scenario))
            result = suite.run_suite(Path(folder), quick=True)
            self.assertEqual(result['unhandled_exceptions'],0,result['errors'])
        self.assertIs(modern_app.QSettings,original)
        self.assertIs(QtCore.QSettings,original)
        self.assertIs(settings_scope._sandbox_workspace,previous)

    def test_missing_mpx_is_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(suite, '_ROOT', Path(folder)):
            with self.assertRaises(FileNotFoundError):
                suite._scenario_mpx_and_session(MagicMock(), MagicMock(), Path(folder), True)

    def test_missing_modal_capture_is_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(suite, '_open_and_cancel_modal'):
            with self.assertRaises(RuntimeError):
                suite._scenario_dialogs(MagicMock(), MagicMock(), Path(folder), True)

    def test_dead_exe_fails_command(self):
        manifest={'unhandled_exceptions':0,'scenarios':[{'status':'ok'}], 'exe_smoke':{'alive_after_launch':False}}
        with patch.object(suite, 'run_suite', return_value=manifest):
            self.assertEqual(suite.main(['--out-dir','unused']),1)
