"""Check both admin buttons and the member review path with isolated wallets."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES, Handler


class ScoreRoomReplies(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / 'test-tmp'
        self.directory = tempfile.TemporaryDirectory(prefix='score-room-replies-', dir=root)
        self.addCleanup(self.directory.cleanup)
        self.engine = Engine(self.directory.name)
        self.handler = SimpleNamespace(engine=self.engine)
        self.user = self.engine.s['users']['localdemo']
        self.user['nickname'] = '别吵'
        for game in GAMES:
            self.engine.game(game)['bot'] = True
        self.engine.credit('localdemo','canada28',60000-self.user['balance'],'fixture','opening')

    def mutate(self, method, game, **data):
        return Handler.mutate(self.handler, '/api/admin/'+method, 'localadmin', game, data)

    def test_direct_buttons_reply_only_in_source_room_with_final_balance(self):
        for game in GAMES:
            for action, amount, expected in [('下分',100,'@别吵 下100成功，剩余共享积分500'),
                                             ('上分',100,'@别吵 上100成功，剩余共享积分600')]:
                with self.subTest(game=game,action=action):
                    counts={g:len(self.engine.game(g)['chat']) for g in GAMES}
                    self.mutate('score',game,username='localdemo',action=action,amount=amount)
                    message=self.engine.game(game)['chat'][-1]
                    self.assertEqual(message['content'],expected)
                    self.assertEqual(message['details']['balance'],self.user['balance'])
                    for other in GAMES:
                        self.assertEqual(len(self.engine.game(other)['chat']),counts[other]+(other==game))
        self.mutate('score','canada28',username='localdemo',action='下分',amount='0.25')
        self.assertEqual(self.engine.game('canada28')['chat'][-1]['content'],
                         '@别吵 下0.25成功，剩余共享积分599.75')

    def test_failed_deduction_does_not_broadcast_success_or_change_wallet(self):
        before=copy.deepcopy(self.engine.s)
        with self.assertRaises(ValueError):
            self.mutate('score','canada28',username='localdemo',action='下分',amount=601)
        self.assertEqual(self.engine.s,before)

    def test_withdrawal_request_and_review_reply_in_request_room(self):
        for game in GAMES:
            with self.subTest(game=game):
                self.engine.request_score('localdemo',game,'下分',100)
                self.assertEqual(self.engine.game(game)['chat'][-1]['content'],
                                 '@别吵下分100，待管理员审核请稍后')
                request=self.engine.s['requests'][-1]
                expected=self.user['balance']//100-100
                self.mutate('review','canada28',id=request['id'],approve=True)
                self.assertEqual(self.engine.game(game)['chat'][-1]['content'],
                                 f'@别吵 下100成功，剩余共享积分{expected}')
                before=copy.deepcopy(self.engine.s)
                with self.assertRaises(ValueError):
                    self.mutate('review','canada28',id=request['id'],approve=True)
                self.assertEqual(self.engine.s,before)


if __name__ == '__main__':
    unittest.main()
