import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES


class BetOnlyChatTests(unittest.TestCase):
    def test_invalid_input_never_broadcasts_or_changes_financial_data(self):
        with tempfile.TemporaryDirectory() as folder:
            e = Engine(folder)
            for game in GAMES:
                e.configure(game, dict(mode='manual', period=3600, minBet='1', maxBet='1000'))
                for text in ['3在100', '你好', '123', '测试1番10', '1番10,你好',
                             '1番1.50', '1番10,2番0.01', '1番999999']:
                    with self.subTest(game=game, text=text):
                        before = copy.deepcopy(e.s)
                        with self.assertRaises(ValueError): e.message('localdemo', game, text, 8)
                        self.assertEqual(e.s, before)
                e.s['users']['localdemo']['balance'] = 0
                before = copy.deepcopy(e.s)
                with self.assertRaisesRegex(ValueError, '积分不足'): e.message('localdemo', game, '1番10', 8)
                self.assertEqual(e.s, before)
                e.s['users']['localdemo']['balance'] = 100000
                e.game(game)['closed'] = True
                before = copy.deepcopy(e.s)
                with self.assertRaises(ValueError): e.message('localdemo', game, '1番10', 8)
                self.assertEqual(e.s, before)

    def test_success_and_turnover_queries_broadcast_but_help_is_private(self):
        with tempfile.TemporaryDirectory() as folder:
            e = Engine(folder)
            for game in GAMES:
                e.configure(game, dict(mode='manual', period=3600, minBet='1', maxBet='1000', bot=True))
                before = copy.deepcopy(e.s)
                self.assertTrue(e.message('localdemo', game, '帮助', 8))
                self.assertEqual(e.s, before)
                for text in ['查', '查流水', '流水', '查余额', '余额']:
                    count = len(e.game(game)['chat'])
                    e.message('localdemo', game, text, 8)
                    messages = e.game(game)['chat'][count:]
                    self.assertEqual(len(messages), 2)
                    self.assertEqual(messages[0]['content'], text)
                    self.assertIn('有效流水', messages[1]['content'])
                    self.assertEqual(e.s['users'], before['users'])
                    self.assertEqual(e.s['orders'], before['orders'])
                    self.assertEqual(e.s['ledger'], before['ledger'])
                count = len(e.game(game)['chat'])
                balance = e.s['users']['localdemo']['balance']
                e.message('localdemo', game, '1番10', 8)
                messages = e.game(game)['chat'][count:]
                self.assertEqual(len(messages), 2)
                self.assertEqual(messages[0]['username'], 'localdemo')
                self.assertEqual(messages[1]['kind'], 'RECEIPT')
                self.assertEqual(e.s['users']['localdemo']['balance'], balance - 1000)
                e.message('localdemo', game, '退', 8)
                self.assertEqual(e.s['users']['localdemo']['balance'], balance)
                e.message('localdemo', game, '上500', 8)
                self.assertEqual(e.game(game)['chat'][-1]['kind'], 'SCORE_REQUEST')


if __name__ == '__main__': unittest.main()
