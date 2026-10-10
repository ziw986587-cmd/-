import copy
import itertools
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, SUM_ROOMS, sum_rule_values


class DigitSumRuleTests(unittest.TestCase):
    def engine(self):
        # No live data or filesystem writes: all balances are isolated in memory.
        with patch.object(Engine, 'save'):
            return Engine(Path(__file__).parent)

    def test_all_1000_draws(self):
        for digits in itertools.product(range(10), repeat=3):
            natural, special, fan = sum_rule_values(digits)
            self.assertEqual(fan, sum(digits) % 4 or 4)
            self.assertEqual(special, int(''.join(map(str, digits))) % 20 or 20)
        self.assertEqual(sum_rule_values([5, 6, 7])[2], 2)
        self.assertEqual(sum_rule_values([0, 0, 0])[2], 4)
        self.assertEqual(sum_rule_values([4, 4, 4])[2], 4)

    def test_both_rooms_settle_new_and_legacy_orders(self):
        for key in SUM_ROOMS:
            e = self.engine()
            g = e.game(key)
            # 567: old natural number gives 3; new sum gives 2.
            e.submit('localdemo', key, '3番10,大10')
            for o in e.pending(key): o['settlementRule'] = 'sum-v2'
            e.submit('localdemo', key, '2番10,小10,双10,1念2/10')
            self.assertTrue(all(o['settlementRule'] == 'sum-v4' for o in e.pending(key)[2:]))
            prior = e.s['users']['localdemo']['balance']
            issue = g['issue']
            with patch.object(Engine, 'save'):
                e.settle(key, issue, [5, 6, 7], 'manual')
            self.assertEqual([o['status'] for o in e.s['orders']],
                             ['中奖', '中奖', '中奖', '未中', '中奖', '和局'])
            self.assertEqual(e.s['users']['localdemo']['balance'], prior + sum(o['payout'] for o in e.s['orders']))
            draw = g['history'][0]
            self.assertEqual((draw['total'], draw['fan'], draw['special'], draw['settlementRule']), (18, 2, 7, 'sum-v4'))
            self.assertIn('18和值', next(m['content'] for m in g['chat'] if m['kind'] == 'JIEGUO'))
            saved = copy.deepcopy(e.s)
            self.assertFalse(e.settle(key, issue, [5, 6, 7], 'manual'))
            self.assertEqual(saved, e.s)

    def test_australia8_still_uses_selected_ball(self):
        e = self.engine()
        e.submit('localdemo', 'australia8', '2番1', 2)
        self.assertEqual(e.pending('australia8')[0]['settlementRule'], 'a8-number-v1')
        e.settle('australia8', e.game('australia8')['issue'], [5, 6, 7, 8, 9, 10, 11, 12], 'manual')
        self.assertEqual(e.s['orders'][0]['status'], '中奖')
        self.assertEqual(e.game('australia8')['history'][0]['fan'], 4)
        self.assertNotIn('total', e.game('australia8')['history'][0])

    def test_v3_pending_keeps_fan_rule_while_v4_uses_total(self):
        for key in SUM_ROOMS:
            e = self.engine()
            g = e.game(key)
            for selection in ('小单', '小双', '大单', '大双'):
                g['odds'][selection] = 2
            e.submit('localdemo', key, '小10,大10,小双10,大双10,2番10')
            old = list(e.pending(key))
            for order in old:
                order['settlementRule'] = 'sum-v3'
            e.submit('localdemo', key, '小10,大10,小双10,大双10,2番10')
            new = e.pending(key)[5:]
            e.settle(key, g['issue'], [4, 5, 5], 'manual')
            self.assertEqual([o['status'] for o in old], ['中奖', '未中', '中奖', '未中', '中奖'])
            self.assertEqual([o['status'] for o in new], ['未中', '中奖', '未中', '中奖', '中奖'])

    def test_special_bets_rejected_atomically_only_in_sum_rooms(self):
        for key in SUM_ROOMS:
            e = self.engine()
            before = copy.deepcopy(e.s)
            for text in ('01特10', '2番10,07特10'):
                with self.assertRaisesRegex(ValueError, '取消特码'):
                    e.message('localdemo', key, text, 8)
                self.assertEqual(e.s, before)
            self.assertNotIn('特', e.public('localdemo', key)['odds'])
            with self.assertRaisesRegex(ValueError, '取消特码'):
                e.bet_rate(key, '07特')
        e = self.engine()
        e.submit('localdemo', 'australia8', '07特10', 8)
        self.assertEqual(e.pending('australia8')[0]['selection'], '07特')

    def test_existing_special_order_keeps_original_settlement(self):
        e = self.engine()
        key = 'canada28'
        e.submit('localdemo', key, '1番10')
        order = e.pending(key)[0]
        order.update(selection='07特', rate=18, settlementRule='sum-v2')
        e.settle(key, e.game(key)['issue'], [5, 6, 7], 'manual')
        self.assertEqual((order['status'], order['payout']), ('中奖', 19000))


if __name__ == '__main__':
    unittest.main()
