import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine


class HistoryFeedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = Engine(self.directory.name)
        self.engine.configure('canada28', dict(mode='external', period=210,
            feed=dict(format='pc28-history', interval=2, url='https://example.invalid/history')))
        self.config = self.engine.game('canada28')['feed']
        self.now = 1800000000

    def receive(self, issue, code='8,0,9'):
        with patch('engine.time.time', return_value=self.now):
            return self.engine.external_result('canada28', {'data': {'1': {
                'id': 7203097, 'scheme_id': 1, 'lottery_id': 2,
                'expect': str(issue), 'opencode': code, 'createtime': 0}}}, self.config)

    def test_baseline_closed_then_sync_duplicate_and_settlement(self):
        self.receive(3488004)
        g = self.engine.game('canada28')
        self.assertTrue(g['closed'])
        self.assertEqual(g['endAt'], 0)
        self.assertEqual(g['issue'], '3488005')
        self.now += 2
        self.receive(3488004)
        self.assertEqual(g['endAt'], 0)
        self.now += 2
        self.receive(3488005)
        self.assertEqual(g['endAt'], self.now + 210)
        self.assertFalse(g['closed'])
        with patch('engine.time.time', return_value=self.now):
            self.engine.submit('localdemo', 'canada28', '1番10', 8)
        # Continue observing unchanged results until the actual next period.
        for _ in range(104):
            self.now += 2
            self.receive(3488005)
        self.now += 2
        self.receive(3488006)
        score = self.engine.s['users']['localdemo']['wallets']['canada28']
        order = self.engine.s['orders'][-1]
        self.assertEqual(order['status'], '中奖')
        self.receive(3488006)
        self.assertEqual(self.engine.s['users']['localdemo']['wallets']['canada28'], score)
        self.assertEqual(len(g['history']), 3)

    def test_long_disconnection_does_not_open_on_stale_update(self):
        self.receive(3488004)
        self.now += 60
        self.receive(3488005)
        self.assertTrue(self.engine.game('canada28')['closed'])

    def test_conflicting_and_malformed_results_rejected(self):
        self.receive(3488004)
        with self.assertRaisesRegex(ValueError, '修改已记录'):
            self.receive(3488004, '1,2,3')
        with self.assertRaises(ValueError):
            self.receive(3488005, '30,2,3')
        with self.assertRaises(ValueError):
            self.engine.external_result('canada28', {'error': 'failed'}, self.config)

    def test_missing_pending_period_preserves_order(self):
        self.receive(3488004)
        self.now += 2
        self.receive(3488005)
        with patch('engine.time.time', return_value=self.now):
            self.engine.submit('localdemo', 'canada28', '1番10', 8)
        self.receive(3488007)
        self.assertEqual(self.engine.s['orders'][-1]['status'], '待开奖')
        self.assertEqual(self.engine.game('canada28')['issue'], '3488008')
        self.assertEqual(self.engine.game('canada28')['feedGaps'], [[3488006,3488006]])


if __name__ == '__main__':
    unittest.main()
