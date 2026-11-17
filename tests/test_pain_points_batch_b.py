import unittest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from statcraft.app import Presenter
from statcraft.data_prep import merge_worksheets
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.verification_fonts import load_verification_fonts


class SplitViewWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        load_verification_fonts(cls.app)
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.p = Presenter()
        self.p.worksheet = Worksheet(
            'Measurements',
            [
                Column('Run', values=list(range(1, 9))),
                Column('Strength', values=[12, 15, 13, 18, 17, 20, 22, 21]),
            ],
        )
        self.w = ModernWindow(self.p)
        self.w.show()
        self.app.processEvents()
        self.ws = self.w._workspace

    def tearDown(self):
        self.p.dirty = False
        self.p._results_dirty = False
        self.w.close()
        self.w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def _add_graph(self):
        entry = self.p.scatter_plot(0, 1)
        self.w.show_result(entry)
        self.app.processEvents()
        return entry

    def test_split_view_requires_at_least_two_tabs(self):
        self.assertFalse(self.ws.is_split())
        self.assertFalse(self.ws.split_view())
        self.assertFalse(self.ws.is_split())

        self._add_graph()
        self.assertEqual(self.ws.tabs.count(), 1)
        self.assertFalse(self.ws.split_view())
        self.assertFalse(self.ws.is_split())
        self.assertFalse(self.ws.unsplit_view())

    def test_split_view_and_unsplit_view_lifecycle(self):
        a = self._add_graph()
        b = self._add_graph()
        self.assertEqual(self.ws.tabs.count(), 2)
        self.assertIs(self.w.selected_entry, b)

        self.assertTrue(self.ws.split_view())
        self.assertTrue(self.ws.is_split())
        self.assertIsNotNone(self.ws._split_splitter)
        self.assertEqual(self.ws._split_splitter.count(), 2)
        self.assertIs(self.ws._split_splitter.widget(0), self.w.result_tabs)
        self.assertIs(self.ws._split_splitter.widget(1), self.ws._secondary_pane)
        self.assertEqual(self.ws._secondary_title.text(), a['title'])
        self.assertTrue(self.ws._secondary_body.toPlainText().strip())

        self.assertTrue(self.ws.unsplit_view())
        self.assertFalse(self.ws.is_split())
        self.assertIsNone(self.ws._split_splitter)
        self.assertGreaterEqual(self.ws.layout.indexOf(self.w.result_tabs), 0)
        self.assertFalse(self.ws.unsplit_view())

    def test_split_view_explicit_secondary_index_and_invalid_index(self):
        a = self._add_graph()
        b = self._add_graph()
        c = self._add_graph()
        self.assertIs(self.w.selected_entry, c)

        self.assertFalse(self.ws.split_view(secondary_index=-1))
        self.assertFalse(self.ws.split_view(secondary_index=99))
        self.assertFalse(self.ws.is_split())

        self.assertTrue(self.ws.split_view(secondary_index=0))
        self.assertTrue(self.ws.is_split())
        self.assertEqual(self.ws._secondary_key, a['entry_id'])

        self.assertTrue(self.ws.split_view(secondary_index=1))
        self.assertEqual(self.ws._secondary_key, b['entry_id'])

    def test_split_view_with_report_pad_and_auto_unsplit_on_close(self):
        a = self._add_graph()
        self.ws.pad.setPlainText('Batch B split note')
        self.ws.show_pad()
        self.app.processEvents()
        self.assertEqual(self.ws.tabs.count(), 2)

        self.assertTrue(self.ws.split_view(secondary_index=0))
        self.assertTrue(self.ws.is_split())
        self.assertEqual(self.ws._secondary_key, a['entry_id'])

        self.ws.close_index(0)
        self.app.processEvents()
        self.assertEqual(self.ws.tabs.count(), 1)
        self.assertFalse(self.ws.is_split())


class MergeWorksheetsTests(unittest.TestCase):
    def setUp(self):
        self.left = Worksheet(
            'Left',
            [
                Column('ID', values=[1, 2, 3, None]),
                Column('Score', values=[10.0, 20.0, 30.0, 40.0]),
            ],
        )
        self.right = Worksheet(
            'Right',
            [
                Column('ID', values=[2, 3, 4]),
                Column('Group', kind='text', values=['B', 'C', 'D']),
            ],
        )

    def test_left_join_by_key(self):
        merged = merge_worksheets(self.left, self.right, left_key=0, right_key=0, name='LeftJoin', how='left')
        self.assertEqual(merged.name, 'LeftJoin')
        self.assertEqual(merged.row_count, 4)
        self.assertEqual(merged.columns[0].values, [1, 2, 3, None])
        self.assertEqual(merged.columns[1].values, [10.0, 20.0, 30.0, 40.0])
        self.assertEqual(merged.columns[2].values, [None, 2, 3, None])
        self.assertEqual(merged.columns[3].values, [None, 'B', 'C', None])

    def test_inner_join_by_key(self):
        merged = merge_worksheets(self.left, self.right, left_key=0, right_key=0, how='inner')
        self.assertEqual(merged.row_count, 2)
        self.assertEqual(merged.columns[0].values, [2, 3])
        self.assertEqual(merged.columns[1].values, [20.0, 30.0])
        self.assertEqual(merged.columns[3].values, ['B', 'C'])

    def test_full_join_by_key(self):
        merged = merge_worksheets(self.left, self.right, left_key=0, right_key=0, how='full')
        self.assertEqual(merged.row_count, 5)
        self.assertEqual(merged.columns[0].values, [1, 2, 3, None, None])
        self.assertEqual(merged.columns[2].values, [None, 2, 3, None, 4])
        self.assertEqual(merged.columns[3].values, [None, 'B', 'C', None, 'D'])

    def test_position_merge(self):
        merged = merge_worksheets(self.left, self.right, how='position')
        self.assertEqual(merged.row_count, 4)
        self.assertEqual(merged.columns[2].values, [2, 3, 4, None])
        self.assertEqual(merged.columns[3].values, ['B', 'C', 'D', None])

    def test_key_validation_errors(self):
        text_right = Worksheet('TextRight', [Column('ID', kind='text', values=['2', '3'])])
        with self.assertRaises(ValueError):
            merge_worksheets(self.left, text_right, left_key=0, right_key=0, how='left')

        dup_right = Worksheet('DupRight', [Column('ID', values=[2, 2])])
        with self.assertRaises(ValueError):
            merge_worksheets(self.left, dup_right, left_key=0, right_key=0, how='left')

        with self.assertRaises(ValueError):
            merge_worksheets(self.left, self.right, left_key=0, right_key=0, how='invalid')


if __name__ == '__main__':
    unittest.main()
