import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES
import robot_messages
import workbench


class QueryEffectiveTurnoverTests(unittest.TestCase):
    def query(self, engine, game):
        engine.message('localdemo', game, '查流水', 8)
        return engine.game(game)['chat'][-1]['content']

    def test_pending_settled_push_and_refund_match_admin_calculation(self):
        for game in GAMES:
            for fan, status, expected in [(1, '中奖', 11000), (2, '和局', 0), (3, '未中', 20000)]:
                with self.subTest(game=game, status=status), tempfile.TemporaryDirectory() as folder:
                    e = Engine(folder)
                    odds = dict(e.game(game)['odds']); odds['念'] = .5
                    e.configure(game, dict(mode='manual', period=3600, minBet='1', maxBet='1000', odds=odds, bot=True))
                    e.submit('localdemo', game, '1念2/200', 8)
                    self.assertIn('有效流水：0', self.query(e, game))
                    numbers = [n for n in range(1, 9) if n != fan] + [fan] if game == 'australia8' else [0, 0, fan]
                    e.settle(game, e.game(game)['issue'], numbers, 'manual')
                    order = e.s['orders'][-1]
                    self.assertEqual(order['status'], status)
                    self.assertEqual(workbench.effective_turnover(order), expected)
                    # Other users and rooms must never enter this user's room query.
                    e.s['orders'].append({**order, 'username':'localadmin', 'amount':99000000, 'profit':99000000})
                    e.s['orders'].append({**order, 'game':next(g for g in GAMES if g != game), 'amount':99000000, 'profit':99000000})
                    before = copy.deepcopy((e.s['users'], e.s['orders'], e.s['ledger']))
                    self.assertIn('有效流水：' + str(expected // 100), self.query(e, game))
                    self.assertNotIn('累计流水：', self.query(e, game))
                    self.assertEqual((e.s['users'], e.s['orders'], e.s['ledger']), before)
                    e.submit('localdemo', game, '1番200', 8)
                    e.cancel('localdemo', game)
                    self.assertIn('有效流水：' + str(expected // 100), self.query(e, game))

    def test_saved_legacy_and_new_template_tokens_both_use_effective_amount(self):
        with tempfile.TemporaryDirectory() as folder:
            e = Engine(folder); game = 'canada28'
            e.configure(game, dict(mode='manual', period=3600, bot=True))
            issue = e.game(game)['issue']
            e.s['orders'] = [dict(username='localdemo', game=game, issue=issue,
                                status=status, amount=20000, profit=profit, selection='旧玩法')
                             for status, profit in [('待开奖', None), ('和局', 0), ('中奖', 10000), ('未中', -20000), ('已退单', 0)]]
            config = robot_messages.config(e, game)
            entries = {r['key']:dict(text=r['text'], enabled=r['enabled']) for r in config['entries']}
            entries['balance']['text'] = '有效={有效流水}；旧占位符={累计流水}'
            robot_messages.save(e, game, dict(revision=config['revision'], name=config['name'], bot=True, entries=entries))
            self.assertEqual(self.query(e, game), '有效=300；旧占位符=300')


if __name__ == '__main__': unittest.main()
