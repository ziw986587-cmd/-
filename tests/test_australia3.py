import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, Handler


class Australia3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = patch('engine.time.time', return_value=1800000000)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.e = Engine(self.temp.name)
        self.g = self.e.game('australia8ball')

    def test_manual_120_seconds_waits_for_admin_and_reopens_after_draw(self):
        self.assertEqual((self.g['mode'], self.g['period']), ('manual', 120))
        self.e.submit('localdemo', 'australia8ball', '2番10')
        with patch('engine.time.time', return_value=1800000110):
            self.e.tick()
            self.assertTrue(self.g['closed'])
        with patch('engine.time.time', return_value=1800000800):
            self.e.tick()
            self.assertEqual(self.g['history'], [])
            self.assertEqual(len(self.e.pending('australia8ball')), 1)
            Handler.mutate(SimpleNamespace(engine=self.e), '/api/admin/draw', 'localadmin',
                           'australia8ball', {'numbers': '8,2,0'})
            self.assertEqual(self.g['endAt'], 1800000920)
            self.assertTrue(self.e.accepting('australia8ball'))
        self.assertEqual(self.g['history'][0]['special'], 20)
        self.assertEqual(self.g['history'][0]['fan'], 2)
        order = self.e.s['orders'][0]
        self.assertEqual((order['ball'], order['status'], order['profit']), (0, '中奖', 2910))
        user = self.e.s['users']['localdemo']
        self.assertEqual(user['balance'], sum(l['delta'] for l in self.e.s['ledger'] if l['username']=='localdemo'))
        self.assertEqual(len(set(user['wallets'].values())), 1)

    def test_three_digits_duplicates_zero_and_maximum(self):
        for numbers, fan in [([0, 0, 0], 4), ([9, 9, 9], 3), ([1, 1, 2], 4)]:
            with self.subTest(numbers=numbers):
                self.e.settle('australia8ball', self.g['issue'], numbers, 'manual')
                result = self.g['history'][0]
                natural=int(''.join(map(str,numbers)))
                self.assertEqual((result['special'], result['fan'], result['drawRule']), (natural%20 or 20, fan, 'sum3'))

    def test_invalid_numbers_and_blank_manual_draw_do_not_mutate(self):
        for numbers in ['', '1,2', '1,2,3,4,5,6,7,8', '1,2,10', '-1,2,3', '1.5,2,3']:
            before = copy.deepcopy(self.e.s)
            with self.subTest(numbers=numbers), self.assertRaises(ValueError):
                Handler.mutate(SimpleNamespace(engine=self.e), '/api/admin/draw', 'localadmin',
                               'australia8ball', {'numbers': numbers})
            self.assertEqual(self.e.s, before)

    def test_old_orders_cannot_be_settled_using_new_rule(self):
        self.e.submit('localdemo', 'australia8ball', '1番10')
        self.e.s['orders'][0]['ball'] = 8
        before = copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError, '旧版'):
            self.e.settle('australia8ball', self.g['issue'], [0, 0, 1], 'manual')
        self.assertEqual(self.e.s, before)

    def test_other_rooms_keep_their_rules(self):
        self.e.settle('canada28', self.e.game('canada28')['issue'], [9, 1, 7], 'manual')
        self.assertEqual(self.e.game('canada28')['history'][0]['special'], 17)
        self.e.settle('australia8', self.e.game('australia8')['issue'], [1,2,3,4,5,6,7,8], 'manual')
        self.assertEqual(self.e.game('australia8')['history'][0]['special'], 8)


if __name__ == '__main__':
    unittest.main()
