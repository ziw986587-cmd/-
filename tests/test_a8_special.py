import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, SUM_ROOMS, parse_bets


class A8SpecialTests(unittest.TestCase):
    def test_examples_and_mixed_batch(self):
        for text, expected in {
            '01/10': [('01特', 1000)],
            '11/18/10': [('11特', 1000), ('18特', 1000)],
            '特12/20': [('12特', 2000)],
            '特1/20/10': [('01特', 1000), ('20特', 1000)],
            '特1/2/3/4/5各30': [('01特', 3000), ('02特', 3000), ('03特', 3000), ('04特', 3000), ('05特', 3000)],
            '01／10，11/18/10\n特12/20,2番10,12角10':
                [('01特', 1000), ('11特', 1000), ('18特', 1000), ('12特', 2000), ('2番', 1000), ('12角', 1000)],
            '12/100,1/10,124/10': [('12角', 10000), ('1正', 1000), ('124车', 1000)],
        }.items():
            with self.subTest(text=text):
                self.assertEqual([(b['selection'], b['amount']) for b in parse_bets(text, 'australia8')], expected)
        for n in range(1, 21):
            self.assertEqual(parse_bets(f'特{n}/10', 'australia8')[0]['selection'], f'{n:02d}特')

    def test_selected_ball_exact_number_and_fan_settle_independently(self):
        numbers = [1, 5, 9, 12, 16, 18, 19, 20]
        with patch.object(Engine, 'save'):
            e = Engine(Path(__file__).parent)
            before = e.s['users']['localdemo']['balance']
            for ball, n in enumerate(numbers, 1):
                other = n+4 if n <= 16 else n-4
                e.message('localdemo', 'australia8', f'特{n}/1,特{other}/1,{n%4 or 4}番1', ball)
            orders = e.pending('australia8')
            self.assertEqual(len(orders), 24)
            self.assertEqual(e.s['users']['localdemo']['balance'], before-2400)
            e.settle('australia8', e.game('australia8')['issue'], numbers, 'manual')
            self.assertEqual([o['status'] for o in orders], ['中奖', '未中', '中奖']*8)
            self.assertEqual([o['ball'] for o in orders], [n for n in range(1, 9) for _ in range(3)])
            self.assertEqual(e.s['users']['localdemo']['balance'], before-2400+sum(o['payout'] for o in orders))

    def test_group_cost_and_atomic_errors(self):
        with patch.object(Engine, 'save'):
            e = Engine(Path(__file__).parent)
            before = e.s['users']['localdemo']['balance']
            e.message('localdemo', 'australia8', '11/18/10', 6)
            self.assertEqual(e.s['users']['localdemo']['balance'], before-2000)
            self.assertEqual([(o['selection'], o['ball']) for o in e.pending('australia8')], [('11特', 6), ('18特', 6)])
            snapshot = copy.deepcopy(e.s)
            for text in ('01/10,特21/10', '00/10', '11/11/10', '特12/0', '01/10,错误20', ','.join(['特01/1']*31)):
                with self.subTest(text=text):
                    with self.assertRaises(ValueError): e.message('localdemo', 'australia8', text, 6)
                    self.assertEqual(e.s, snapshot)

    def test_other_rooms_keep_no_special_and_shorthand(self):
        for key in SUM_ROOMS:
            with patch.object(Engine, 'save'):
                e = Engine(Path(__file__).parent)
                before = copy.deepcopy(e.s)
                for text in ('01特10', '特12/20', '01/10', '11/18/10'):
                    with self.assertRaises(ValueError): e.submit('localdemo', key, text)
                    self.assertEqual(e.s, before)
                self.assertEqual(parse_bets('12/100', key)[0]['selection'], '12角')


if __name__ == '__main__':
    unittest.main()
