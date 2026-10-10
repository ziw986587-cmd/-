import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine
import workbench


class Australia8BallSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1800000000
        clock = patch('engine.time.time', side_effect=lambda: self.now)
        clock.start(); self.addCleanup(clock.stop)
        self.e = Engine(self.temp.name)
        workbench.initialize(self.e)
        self.e.configure('australia8', dict(mode='manual', period=120, closeSeconds=10))
        self.numbers = [13, 6, 2, 12, 3, 14, 19, 4]

    def settle(self):
        return self.e.settle('australia8', self.e.game('australia8')['issue'], self.numbers, 'manual')

    def test_each_selected_ball_drives_its_own_result(self):
        for ball, n in enumerate(self.numbers, 1):
            self.e.submit('localdemo', 'australia8', f'{n % 4 or 4}番10', ball)
        self.assertEqual([o['ball'] for o in self.e.pending('australia8')], list(range(1, 9)))
        self.settle()
        self.assertEqual([o['status'] for o in self.e.s['orders']], ['中奖'] * 8)
        self.assertEqual(self.e.game('australia8')['history'][0]['special'], 4)
        self.assertEqual(self.e.game('australia8')['history'][0]['fan'], 4)

    def test_same_bet_different_positions_win_and_lose_and_restart(self):
        self.e.submit('localdemo', 'australia8', '1番10', 1)
        self.e.submit('localdemo', 'australia8', '1番10', 8)
        self.e.save(); self.e = Engine(self.temp.name)
        self.settle()
        self.assertEqual([o['status'] for o in self.e.s['orders']], ['中奖', '未中'])
        self.assertEqual([o['profit'] for o in self.e.s['orders']], [2910, -1000])

    def test_special_and_push_use_selected_number(self):
        self.e.submit('localdemo', 'australia8', '13特10', 1)
        self.e.submit('localdemo', 'australia8', '13特10', 8)
        self.e.submit('localdemo', 'australia8', '1念2/10', 2)
        self.settle()
        self.assertEqual([o['status'] for o in self.e.s['orders']], ['中奖', '未中', '和局'])

    def test_numbers_above_four_map_to_independent_fans(self):
        numbers=[12,1,2,3,4,5,8,20]
        for ball, fan in enumerate([4,1,2,3,4,1,4,4], 1):
            self.e.submit('localdemo','australia8',f'{fan}番10',ball)
        self.e.settle('australia8',self.e.game('australia8')['issue'],numbers,'manual')
        self.assertEqual([o['status'] for o in self.e.s['orders']],['中奖']*8)

    def test_australia8_rejects_zero_and_keeps_eight_unique_balls(self):
        before=copy.deepcopy(self.e.s)
        with self.assertRaises(ValueError):
            self.e.settle('australia8',self.e.game('australia8')['issue'],[0,1,2,3,4,5,6,7],'manual')
        self.assertEqual(before, self.e.s)
        self.e=Engine(self.temp.name)
        self.e.configure('australia8',dict(mode='manual',period=120))
        with self.assertRaises(ValueError): self.e.settle('australia8',self.e.game('australia8')['issue'],[8,1,2,3,4,5,6,6],'manual')

    def test_default_old_orders_remain_eighth_ball_and_cancel_refunds(self):
        balance = self.e.s['users']['localdemo']['balance']
        self.e.submit('localdemo', 'australia8', '4番10')
        self.assertEqual(self.e.pending('australia8')[0]['ball'], 8)
        self.e.cancel('localdemo', 'australia8')
        self.assertEqual(self.e.s['users']['localdemo']['balance'], balance)
        self.e.submit('localdemo', 'australia8', '4番10')
        del self.e.pending('australia8')[0]['ball']
        self.settle()
        self.assertEqual(self.e.s['orders'][-1]['status'], '中奖')

    def test_invalid_ball_is_atomic_and_closing_rules_still_apply(self):
        for ball in [0, 9, True, 1.5, None, '1.0', 'not-a-ball']:
            before = copy.deepcopy(self.e.s)
            with self.assertRaises(ValueError): self.e.submit('localdemo', 'australia8', '1番10', ball)
            self.assertEqual(self.e.s, before)
        self.e.message('localdemo', 'australia8', '1番10', 1)
        self.assertIn('第1球', self.e.game('australia8')['chat'][-1]['content'])
        self.now += 50
        with self.assertRaises(ValueError): self.e.submit('localdemo', 'australia8', '1番11', 1)
        with self.assertRaises(ValueError): self.e.cancel('localdemo', 'australia8')
        self.e.submit('localdemo', 'australia8', '1番10', 1)

    def test_other_rooms_use_sum_rule_independent_of_ball(self):
        for key in ('canada28', 'australia8ball'):
            self.e.configure(key, dict(mode='manual', period=120))
            self.e.submit('localdemo', key, '1番10', 1)
        self.assertEqual(self.e.pending('canada28')[0]['ball'], 8)
        self.assertEqual(self.e.pending('australia8ball')[0]['ball'], 0)
        self.e.settle('canada28', self.e.game('canada28')['issue'], [1, 0, 1], 'manual')
        self.e.settle('australia8ball', self.e.game('australia8ball')['issue'], [0, 0, 1], 'manual')
        self.assertEqual([o['status'] for o in self.e.s['orders']], ['未中', '中奖'])


if __name__ == '__main__': unittest.main()
