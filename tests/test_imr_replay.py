import tempfile
import unittest
from pathlib import Path

from statcraft.app import Presenter, format_entry
from statcraft.imr_replay import approve, preview, replay
from statcraft.model import Column, Worksheet


class ReplayTests(unittest.TestCase):
    def test_replay_mapping_acceptance_and_roundtrip(self):
        p = Presenter()
        p.worksheet = Worksheet('Baseline', [Column('Reading', 'number', [10, 10, 11, 9], metadata={'unit': 'mm'})])
        baseline = p.imr_chart({'variables': [0], 'options': {'historical_mean': 10, 'historical_sigma': 1}})
        approve(p, baseline, 0)
        p.add_worksheet('Batch').columns = [Column('Lot', 'text', ['B'] * 4),
            Column('New Reading', 'number', [10, 10, 18, 10], metadata={'unit': 'in'})]
        template = baseline['result']['workflow_replay']
        with self.assertRaisesRegex(ValueError, 'differs'):
            replay(p, template, 1)
        self.assertEqual(len(p.history), 1)
        p.worksheet.columns[1].metadata['unit'] = 'mm'
        self.assertIn('C2 New Reading', preview(p, template, 1))
        entry = replay(p, template, 1)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'replay.mpx'
            p.save(path)
            p.load(path)
        saved = next(result for result in p.history if result['entry_id'] == entry['entry_id'])
        self.assertIn('Acceptance: Fail', format_entry(saved))
        self.assertIn('Individuals signals: 0', format_entry(saved))
        approve(p, saved, 5)
        self.assertIn('Acceptance: Fail', format_entry(saved))
        self.assertEqual(saved['result']['workflow_replay']['max_signals'], 5)
