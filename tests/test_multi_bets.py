import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES, parse_bets, outcome


class MultiBetTests(unittest.TestCase):
    def test_separators_and_short_nian(self):
        expected = [{'selection': '12角', 'amount': 10000},
                    {'selection': '1念2', 'amount': 10000}]
        for sep in (',', '，', '\n', '\r\n', '\r'):
            with self.subTest(separator=repr(sep)):
                self.assertEqual(parse_bets('12角100' + sep + '12念100'), expected)
                self.assertEqual([b['selection'] for b in parse_bets('大100'+sep+'小100')], ['大', '小'])
        self.assertEqual(parse_bets('\n12角100\n\n12念100\n'), expected)
        self.assertEqual(parse_bets('12严100'), [expected[1]])
        self.assertEqual(parse_bets('12念/100'), [expected[1]])
        self.assertEqual([outcome('1念2', n) for n in (1, 2, 3, 4)], ['win', 'push', 'lose', 'lose'])

    def test_punctuation_and_space_stake_separators(self):
        expected = [{'selection': '12角', 'amount': 10000},
                    {'selection': '23角', 'amount': 10000}]
        for text in ('12、100 23-100', '12，100 23.100', '12角100 23角100'):
            with self.subTest(text=text):
                self.assertEqual(parse_bets(text), expected)

    def test_chat_batches_all_rooms_debit_once_and_keep_ball(self):
        for room in GAMES:
            for text in ('12角100,12念100', '大100，小100', '12角100\n12念100', '12/100\n23/100'):
                with self.subTest(room=room, text=text), patch.object(Engine, 'save'):
                    e = Engine(Path(__file__).parent)
                    before = e.s['users']['localdemo']['balance']
                    ledger_count = len(e.s['ledger'])
                    e.message('localdemo', room, text, 3)
                    orders = e.pending(room)
                    self.assertEqual(len(orders), 2)
                    self.assertEqual(e.s['users']['localdemo']['balance'], before-20000)
                    self.assertEqual(len({o['batch'] for o in orders}), 1)
                    self.assertEqual(len(e.s['ledger']), ledger_count + 1)
                    if room == 'australia8': self.assertEqual([o['ball'] for o in orders], [3, 3])

    def test_invalid_batch_never_partially_debits(self):
        for room in GAMES:
            with patch.object(Engine, 'save'):
                e = Engine(Path(__file__).parent)
                before = copy.deepcopy(e.s)
                for text in ('12角100\n11念100', '12角100\n错误100', '12角100,,12念100', '1番\n100', ','.join(['1番1']*31)):
                    with self.subTest(room=room, text=text):
                        with self.assertRaises(ValueError): e.message('localdemo', room, text, 3)
                        self.assertEqual(e.s, before)


if __name__ == '__main__':
    unittest.main()
