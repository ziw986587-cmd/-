import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, A8_COMBOS, SUM_GROUPS, RULES


class A8NumberRulesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.e = Engine(self.temp.name)
        self.e.configure('australia8', {'mode': 'manual', 'period': 600})

    def enable(self):
        odds = dict(self.e.game('australia8')['odds'])
        odds.update(dict(zip(A8_COMBOS, [2.1, 2.2, 2.3, 2.4])))
        self.e.configure('australia8', {'odds': odds})

    def test_every_number_at_every_ball_all_eight_selections(self):
        self.enable()
        for ball in range(1, 9):
            for number in range(1, 21):
                with self.subTest(ball=ball, number=number):
                    numbers = [n for n in range(1, 21) if n != number][:7]
                    numbers.insert(ball - 1, number)
                    before = self.e.s['users']['localdemo']['balance']
                    self.e.submit('localdemo', 'australia8', ','.join(s+'1' for s in SUM_GROUPS), ball)
                    orders = list(self.e.pending('australia8'))
                    self.assertTrue(all(o['settlementRule'] == 'a8-number-v1' for o in orders))
                    issue = self.e.game('australia8')['issue']
                    self.e.settle('australia8', issue, numbers, 'manual')
                    size = '小' if number <= 10 else '大'
                    parity = '单' if number % 2 else '双'
                    for order in orders:
                        win = order['selection'] in (size, parity, size+parity)
                        self.assertEqual(order['status'], '中奖' if win else '未中')
                        self.assertEqual(order['profit'], round(order['amount']*order['rate']) if win else -order['amount'])
                    self.assertEqual(self.e.s['users']['localdemo']['balance'], before + sum(o['profit'] for o in orders))
                    self.assertEqual(self.e.game('australia8')['history'][0]['settlementRule'], 'a8-number-v1')
                    self.assertFalse(self.e.settle('australia8', issue, numbers, 'manual'))

    def test_legacy_pending_and_rates_survive_restart(self):
        self.enable()
        self.e.submit('localdemo', 'australia8', '大10,小10', 1)
        for order in self.e.pending('australia8'):
            order.pop('settlementRule')
        self.e.submit('localdemo', 'australia8', '大10,小10,大双10,14特10,2番10,1念2/10', 1)
        self.e.game('australia8')['odds']['大双'] = 9
        self.e.save()
        self.e = Engine(self.temp.name)
        self.e.settle('australia8', self.e.game('australia8')['issue'], [14,1,2,3,4,5,6,7], 'manual')
        rows = self.e.s['orders']
        self.assertEqual([o['status'] for o in rows], ['未中','中奖','中奖','未中','中奖','中奖','中奖','和局'])
        self.assertEqual(rows[4]['profit'], 2400)

    def test_unset_disabled_atomic_validation_and_migration(self):
        self.assertTrue(all(self.e.game('australia8')['odds'][s] is None for s in A8_COMBOS))
        before = copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError, '尚未设置'):
            self.e.submit('localdemo', 'australia8', '大1,小单1')
        self.assertEqual(before, self.e.s)
        self.enable()
        self.e.configure('australia8', {'odds': dict(RULES)})
        self.assertEqual(self.e.game('australia8')['odds']['大双'], 2.4)
        for bad in (True, 0, -1, 101, float('nan'), '2'):
            before = copy.deepcopy(self.e.s)
            with self.assertRaises(ValueError):
                self.e.configure('australia8', {'odds': {**self.e.game('australia8')['odds'], '小单': bad}})
            self.assertEqual(before, self.e.s)
        for s in A8_COMBOS:
            self.e.game('australia8')['odds'].pop(s)
        self.e.save()
        self.e = Engine(self.temp.name)
        self.assertTrue(all(self.e.game('australia8')['odds'][s] is None for s in A8_COMBOS))

    def test_draw_range_and_cancel_are_atomic(self):
        self.enable()
        before = self.e.s['users']['localdemo']['balance']
        self.e.submit('localdemo', 'australia8', '大双10', 6)
        self.e.cancel('localdemo', 'australia8')
        self.assertEqual(self.e.s['users']['localdemo']['balance'], before)
        for numbers in ([0,1,2,3,4,5,6,7], [21,1,2,3,4,5,6,7], [1,1,2,3,4,5,6,7]):
            snapshot = copy.deepcopy(self.e.s)
            with self.assertRaises(ValueError):
                self.e.settle('australia8', self.e.game('australia8')['issue'], numbers, 'manual')
            self.assertEqual(snapshot, self.e.s)


if __name__ == '__main__': unittest.main()
