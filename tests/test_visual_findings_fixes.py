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

    def test_specialized_charts_accept_pointer_events_on_first_open(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from statcraft.dsd_chart import DSDParetoEffectsWidget
        from statcraft.fitted_line_plot_chart import FittedLinePlotChartWidget
        from statcraft.imr_chart import IMRChartWidget

        for chart_type in (DSDParetoEffectsWidget, FittedLinePlotChartWidget, IMRChartWidget):
            with self.subTest(chart=chart_type.__name__):
                chart = chart_type({'result': {}})
                self.addCleanup(chart.deleteLater)
                position = QPointF(20, 20)
                event = QMouseEvent(
                    QEvent.Type.MouseMove, position, position, Qt.MouseButton.NoButton,
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                )
                chart.mouseMoveEvent(event)
                self.assertEqual(chart.hover_text_at(position), '')

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

    def test_startup_offers_recovery_and_clean_timer_preserves_snapshot(self):
        import tempfile
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox
        from statcraft import session_io
        from statcraft.model import Column, Worksheet
        from statcraft.startup import start_window

        window = self.window()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "autosave_recovery.json"
            sheet = Worksheet("Recovered", [Column("Score", "number", [88.5])])
            session_io.autosave_snapshot(sheet, [], path)
            original = path.read_bytes()
            with patch.object(window, "_autosave_path", return_value=path), patch.object(
                QMessageBox, "question", side_effect=[QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
            ):
                start_window(self.app, lambda: window)
                self.assertFalse(window.presenter.dirty)
                window._autosave_timer.timeout.emit()
                self.assertEqual(path.read_bytes(), original)

                start_window(self.app, lambda: window)
                self.assertTrue(window.presenter.dirty)
                self.assertEqual(window.presenter.worksheet.columns[0].values, [88.5])
                window.presenter.set_cell(0, 0, "99.5")
                window._autosave_timer.timeout.emit()
                self.assertEqual(session_io.load_autosave_snapshot(path)["worksheet"].columns[0].values, [99.5])
                saved = Path(tmp) / "recovered.mpx"
                self.assertTrue(window.save_path(saved))
                self.assertFalse(path.exists())
                reopened = self.window()
                reopened.load_path(saved)
                self.assertEqual(reopened.presenter.worksheet.columns[0].values, [99.5])

    def test_scatter_dialog_enter_transfers_selected_variable(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from statcraft.model import Column, Worksheet
        from statcraft.variable_dialogs import ScatterDialog

        ws = Worksheet("ScatterEnter", [Column("Run", "number", [1.0, 2.0, 3.0]), Column("Strength", "number", [4.0, 5.0, 6.0])])
        dlg = ScatterDialog(self.window(), ws, mode="simple")
        self.addCleanup(dlg.deleteLater)
        dlg.show()
        self.app.processEvents()
        dlg.available.setCurrentRow(1)
        dlg.available.setFocus()
        self.app.processEvents()
        QTest.keyClick(dlg.available, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertIsNotNone(dlg.roles.item(0, 0))
        self.assertIn("Strength", dlg.roles.item(0, 0).text())

    def test_load_path_resets_scroll_selection_and_paste_toast(self):
        import tempfile
        from pathlib import Path
        from PySide6.QtWidgets import QTableWidgetSelectionRange
        from statcraft.model import Column, Worksheet
        from statcraft.mpx_create import create_project
        from statcraft.mpx import save_mpx

        win = self.window()
        win.presenter.worksheet = Worksheet("Big", [Column("X", "number", [float(i) for i in range(60)]), Column("Y", "number", [float(i * 2) for i in range(60)])])
        win.refresh()
        win.resize(1200, 600)
        win.show()
        self.app.processEvents()
        win.table.verticalScrollBar().setValue(win.table.verticalScrollBar().maximum())
        win.table.setRangeSelected(QTableWidgetSelectionRange(5, 1, 20, 1), True)
        win.paste_toast.show_paste(10, 2, allow_header_promote=False)
        self.app.processEvents()
        self.assertGreater(win.table.verticalScrollBar().value(), 0)
        self.assertFalse(win.paste_toast.isHidden())

        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / "fresh.mpx"
            save_mpx(create_project([Worksheet("Fresh", [Column("A", "number", [1.0, 2.0])])]), str(mpx_path), session_records=[])
            win.load_path(str(mpx_path))
            self.app.processEvents()

        self.assertEqual(win.table.verticalScrollBar().value(), 0)
        self.assertTrue(win.paste_toast.isHidden())
        self.assertEqual(len(win.table.selectedRanges()), 1)
        r = win.table.selectedRanges()[0]
        self.assertEqual((r.topRow(), r.leftColumn(), r.bottomRow(), r.rightColumn()), (0, 0, 0, 0))

    def test_reset_3d_view_defaults_works_on_expanded_scatter3d(self):
        from statcraft.model import Column, Worksheet
        from statcraft.spatial_view import DEFAULT_VIEW

        win = self.window()
        win.presenter.worksheet = Worksheet(
            "3DTest",
            [
                Column("X", "number", [1.0, 2.0, 3.0, 4.0]),
                Column("Y", "number", [2.0, 4.0, 1.0, 3.0]),
                Column("Z", "number", [10.0, 20.0, 30.0, 40.0]),
            ],
        )
        entry = win.presenter.expanded_graph("scatter3d", [0, 1, 2])
        win.show_result(entry, target_graph_index=0)
        self.app.processEvents()
        chart = win._active_graph_frame.chart
        chart.rotate_view(24.0, 10.0)
        self.assertNotEqual(chart.view_state, DEFAULT_VIEW)
        self.assertTrue(win.reset_graph_3d_view_defaults())
        self.assertEqual(chart.view_state, DEFAULT_VIEW)

    def test_specialized_charts_render_graph_tab_in_show_result(self):
        from statcraft.model import Column, Worksheet
        from statcraft.modern_charts import supported

        win = self.window()
        win.presenter.worksheet = Worksheet(
            "Charts",
            [
                Column("X", "number", [10.0, 12.0, 14.0, 15.0, 18.0, 21.0, 22.0, 24.0]),
                Column("Y", "number", [50.0, 54.0, 59.0, 61.0, 68.0, 72.0, 75.0, 80.0]),
            ],
        )
        entries = [
            win.presenter.marginal_plot(1, 0),
            win.presenter.ecdf_plot(0),
            win.presenter.probability_distribution_plot(),
        ]
        for entry in entries:
            self.assertTrue(supported(entry))
            win.show_result(entry, target_graph_index=0)
            self.app.processEvents()
            self.assertIsNotNone(win._active_graph_frame, f"Missing GraphFrame for {entry.get('title')}")
            self.assertGreater(win._active_graph_frame.capture().width(), 0)

    def test_saving_analysis_clears_dirty_prompt_and_persists_the_result(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from statcraft.mpx_create import create_project, save_owned
        from statcraft.model import Column, Worksheet

        win = self.window()
        ws = Worksheet("CleanCheck", [Column("X", "number", [1.0, 2.0, 3.0, 4.0])])
        proj = create_project([ws])
        with tempfile.TemporaryDirectory() as tmpdir:
            mpx_path = Path(tmpdir) / "clean_check.mpx"
            save_owned(proj, str(mpx_path), [])
            win.load_path(mpx_path)
            entry = win.presenter.describe_columns([0])
            self.assertTrue(win.presenter.dirty)
            self.assertTrue(win.save_path(mpx_path))
            self.assertFalse(win.presenter.dirty)
            with patch("statcraft.modern_app.QMessageBox.question") as mock_q:
                win.new_document()
            mock_q.assert_not_called()
            win.load_path(mpx_path)
            self.assertIn(entry["entry_id"], {item.get("entry_id") for item in win.presenter.history})
