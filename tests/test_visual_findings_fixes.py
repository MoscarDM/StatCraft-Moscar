import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from statcraft.modern_app import ModernWindow
from statcraft.executive_summary import generate_executive_summary
from statcraft.response_surface_dialogs import CreateSurfaceDialog, CreateSurfaceSettings
from statcraft import __version__


class VisualFindingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def window(self):
        win = ModernWindow(sandbox_mode=True)
        win.closeEvent = lambda event: event.accept()
        def cleanup():
            win.presenter.dirty = False
            win.presenter._results_dirty = False
            win.close()
            win.deleteLater()
            self.app.processEvents()
        self.addCleanup(cleanup)
        return win

    def test_banner_stays_compact_and_uses_current_version(self):
        win = self.window()
        win.resize(1280, 900)
        win.show()
        self.app.processEvents()
        self.assertLess(win.sandbox_banner.height(), 75)
        self.assertIn(__version__, win.sandbox_badge.text())
        win._copy_sandbox_diagnostics()
        self.assertIn(__version__, QApplication.clipboard().text())

    def test_imported_summary_does_not_claim_recalculation(self):
        bullets = generate_executive_summary({'title':'Response Optimization: Y', 'result':{'analysis':'native_saved_output'}})
        text = ' '.join(bullets)
        self.assertIn('saved', text.lower())
        self.assertNotIn('completed evaluation', text)

    def test_ccd_starts_with_catalog_default(self):
        dialog = CreateSurfaceDialog(self.window())
        self.addCleanup(dialog.deleteLater)
        self.assertIn('13 runs', dialog.design_description.text())
        child = CreateSurfaceSettings(dialog, 'Designs')
        self.addCleanup(child.deleteLater)
        self.assertTrue(child.default_centers.isChecked())
        self.assertEqual(child.controls['center_cube'].value(), 5)

    def test_native_graph_selected_even_when_report_text_exists(self):
        win = self.window()
        entry = {'title':'Saved graph','result':{'analysis':'native_saved_output','text':'Saved output text', 'tables':[{'title':'Summary','headers':['N'],'rows':[[2]]}], 'graphs':[{'title':'Saved scatter','panels':[{'kind':'scatter','series':[{'x':[1,2],'y':[3,4],'kind':'scatter'}]}]}]}}
        win.show_result(entry)
        self.assertNotEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), 'Report')
        win.show_result(entry, target_tab='Report')
        self.assertEqual(win.result_tabs.tabText(win.result_tabs.currentIndex()), 'Report')

    def test_module_entry_uses_modern_desktop(self):
        from statcraft.__main__ import main
        with patch('statcraft.app.main', return_value=0), patch('statcraft.modern_app.main', return_value=0) as modern:
            self.assertEqual(main(), 0)
            modern.assert_called_once()

    def test_autosave_is_a_filesystem_path_not_registry_key(self):
        win = self.window()
        self.assertEqual(win._autosave_path().parent, win.sandbox_workspace)
