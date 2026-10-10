import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine
import force_open


class ForceOpenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.e = Engine(temp.name)
        self.e.configure('canada28', dict(mode='external', period=210,
            feed=dict(format='pc28-history', interval=2, url='https://example.invalid')))
        self.g = self.e.game('canada28')
        self.g.update(issue='100', closed=False, endAt=1800000210)
        with patch('engine.time.time', return_value=1800000000):
            self.e.submit('localdemo', 'canada28', '1番10')
        self.g['closed'] = True
        self.data = dict(issue='100', latestIssue='200', pendingIds=sorted(o['id'] for o in self.e.pending('canada28')),
                         confirmed=True, refundConfirmed=True)

    def run_open(self, rows=None):
        with patch('force_open.read_latest', return_value=rows or [('200', [8, 0, 9])]), \
                patch('force_open.time.time', return_value=1800000000):
            return force_open.run(self.e, 'canada28', self.data)

    def test_refund_then_reopen_and_real_result_settles_only_new_orders(self):
        starting = self.e.s['users']['localdemo']['balance']
        self.run_open()
        self.assertEqual(self.e.s['users']['localdemo']['balance'], starting + 1000)
        self.assertEqual(self.g['issue'], '201')
        self.assertEqual(self.g['endAt'], 1800000210)
        self.assertEqual(self.e.s['orders'][0]['status'], '已退单')
        with patch('engine.time.time', return_value=1800000002):
            self.e.submit('localdemo', 'canada28', '1番10')
            self.e.external_result('canada28', [dict(expect='201', opencode='8,0,9', lottery_id=2)], self.g['feed'])
        self.assertEqual(self.e.s['orders'][0]['status'], '已退单')
        self.assertEqual(self.e.s['orders'][1]['status'], '中奖')
        self.assertEqual(self.g['issue'], '202')
        self.assertEqual(self.g['endAt'], 1800000212)
        self.assertEqual(len([l for l in self.e.s['ledger'] if l['reason']=='强制开盘退还本金']), 1)

    def test_without_refund_consent_no_mutation(self):
        self.data['refundConfirmed'] = False
        before = copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError, '确认'):
            self.run_open()
        self.assertEqual(self.e.s, before)

    def test_stale_confirmation_no_mutation(self):
        self.data['pendingIds'] = []
        before = copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError, '变化'):
            self.run_open()
        self.assertEqual(self.e.s, before)

    def test_unavailable_source_no_mutation(self):
        before = copy.deepcopy(self.e.s)
        with patch('force_open.read_latest', side_effect=ValueError('unavailable')):
            with self.assertRaises(ValueError):
                force_open.run(self.e, 'canada28', self.data)
        self.assertEqual(self.e.s, before)

    def test_old_or_conflicting_source_no_mutation(self):
        for rows in [[('98', [8, 0, 9])], [('99', [1, 2, 3])]]:
            self.g['history'] = [dict(issue='99', numbers=[8, 0, 9])]
            before = copy.deepcopy(self.e.s)
            with self.assertRaises(ValueError):
                self.run_open(rows)
            self.assertEqual(self.e.s, before)

    def test_cannot_repeat_open_or_modify_other_rooms(self):
        self.run_open()
        before = copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError, '已经开盘'):
            self.run_open()
        with self.assertRaisesRegex(ValueError, '仅支持'):
            force_open.run(self.e, 'australia8', self.data)
        self.assertEqual(self.e.s, before)


if __name__ == '__main__':
    unittest.main()
