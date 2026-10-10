import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES
import robot_messages


class QueryBetDetailsTests(unittest.TestCase):
    def test_details_show_only_own_current_pending_orders_in_each_room(self):
        with tempfile.TemporaryDirectory() as folder:
            e = Engine(folder)
            for game in GAMES:
                e.configure(game, dict(mode='manual', period=3600, minBet='1', maxBet='1000', bot=True))
                e.message('localdemo', game, '查', 8)
                self.assertIn('暂无下注\n合计：0（0笔）', e.game(game)['chat'][-1]['content'])
                e.submit('localdemo', game, '1番100,12角50', 1)
                e.submit('localdemo', game, '2番30', 3)
                orders = e.pending(game, 'localdemo')
                first, second, third = orders
                # Excluded orders use a recognizable selection to catch leakage.
                for changes in [dict(username='localadmin'), dict(issue='old'), dict(status='中奖'),
                                dict(status='已退单'), dict(game=next(g for g in GAMES if g != game))]:
                    e.s['orders'].append({**first, 'id':'excluded'+str(len(e.s['orders'])), 'selection':'4番', **changes})
                before = copy.deepcopy((e.s['users'], e.s['orders'], e.s['ledger']))
                e.message('localdemo', game, '查流水', 8)
                reply = e.game(game)['chat'][-1]['content']
                prefix1 = '第1球 ' if game=='australia8' else ''
                prefix3 = '第3球 ' if game=='australia8' else ''
                self.assertIn(f'{prefix1}1番：100\n{prefix1}12角：50\n{prefix3}2番：30\n合计：180（3笔）', reply)
                self.assertNotIn('4番', reply)
                self.assertIn('当局下注明细（'+e.game(game)['issue']+'期）', reply)
                self.assertEqual((e.s['users'], e.s['orders'], e.s['ledger']), before)
                e.cancel('localdemo', game, third['id'])
                e.message('localdemo', game, '查', 8)
                reply = e.game(game)['chat'][-1]['content']
                self.assertNotIn('2番：30', reply)
                self.assertIn('合计：150（2笔）', reply)
                # Remove injected cross-room fixtures before exercising the next room.
                e.s['orders'] = [o for o in e.s['orders'] if not o['id'].startswith('excluded')]

    def test_old_saved_token_updates_without_overwriting_custom_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            e = Engine(folder); game = 'australia8'
            e.configure(game, dict(mode='manual', period=3600, minBet='1', maxBet='1000', bot=True))
            e.submit('localdemo', game, '1番100', 2)
            room = e.game(game)
            room['robotMessages'] = {'balance':dict(text='自定义\n当局下注（{期号}期）：{当局下注}\n金额{当局下注金额}', enabled=True)}
            saved = copy.deepcopy(room['robotMessages'])
            config = robot_messages.config(e, game)
            entry = next(r for r in config['entries'] if r['key']=='balance')
            self.assertIn('{当局下注明细}', entry['text'])
            self.assertIn('当局下注明细', entry['sample'])
            self.assertNotIn('当局下注', entry['sample'])
            e.message('localdemo', game, '查', 8)
            reply = room['chat'][-1]['content']
            self.assertIn('自定义\n当局下注明细', reply)
            self.assertIn('第2球 1番：100\n金额100', reply)
            self.assertEqual(room['robotMessages'], saved)
            entries = {r['key']:dict(text=r['text'], enabled=r['enabled']) for r in config['entries']}
            entries['balance']['text'] = saved['balance']['text']
            robot_messages.save(e, game, dict(revision=config['revision'], name=config['name'], bot=True, entries=entries))
            self.assertIn('{当局下注明细}', room['robotMessages']['balance']['text'])


if __name__ == '__main__': unittest.main()
