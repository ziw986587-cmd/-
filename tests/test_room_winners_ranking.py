import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES


class RoomWinnersRankingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.e = Engine(self.temp.name)
        for key in GAMES:
            self.e.configure(key, {'mode':'manual', 'period':600})

    def messages(self, key):
        chat = self.e.public('localdemo', key)['chat']
        return [next(m for m in reversed(chat) if m['kind'] == kind) for kind in ('SETTLEMENT', 'YINGLI')]

    def test_all_rooms_win_details_and_net_ranking_are_distinct_snapshots(self):
        for key in GAMES:
            with self.subTest(key=key):
                self.e.submit('localdemo', key, '1番10,2番50,2念1/10', 1)
                self.e.submit('localdemo', key, '1番20', 1)
                self.e.cancel('localdemo', key, self.e.pending(key)[-1]['id'])
                numbers = [1,2,3,4,5,6,7,8] if key == 'australia8' else [0,0,1]
                issue = self.e.game(key)['issue']
                self.e.settle(key, issue, numbers, 'manual')
                settlement, ranking = self.messages(key)
                winner, = settlement['details']['winningOrders']
                self.assertEqual((winner['selection'],winner['amount'],winner['profit']),('1番',1000,2910))
                row, = ranking['details']['rows']
                self.assertEqual(row['profit'], -2090)  # winning order, less losing order; push/refund add zero
                self.assertEqual(row['balance'], self.e.s['users']['localdemo']['balance'])
                self.assertEqual((ranking['details']['game'],ranking['details']['issue']),(key,issue))
                self.assertIn('(-20.90)', ranking['content'])
                snapshot = copy.deepcopy(ranking)
                self.e.credit('localdemo','canada28',10000,'test','later')
                self.assertEqual(ranking,snapshot)
                state = copy.deepcopy(self.e.s)
                self.assertFalse(self.e.settle(key,issue,numbers,'manual'))
                self.assertEqual(state,self.e.s)
        self.e.save()
        restarted = Engine(self.temp.name)
        for key in GAMES:
            self.assertEqual(restarted.public('localdemo',key)['chat'], self.e.public('localdemo',key)['chat'])

    def test_historical_enrichment_all_rooms_is_read_only_and_requires_complete_orders(self):
        for key in GAMES:
            self.e.submit('localdemo', key, '1番10', 1)
            self.e.settle(key,self.e.game(key)['issue'],[1,2,3,4,5,6,7,8] if key=='australia8' else [0,0,1],'manual')
            saved = self.e.game(key)['chat']
            settlement = next(m for m in reversed(saved) if m['kind']=='SETTLEMENT')
            ranking = next(m for m in reversed(saved) if m['kind']=='YINGLI')
            expected = copy.deepcopy(settlement['details'])
            del settlement['details']['winningOrders']
            del settlement['details']['draw']
            del ranking['details']
            before = copy.deepcopy(self.e.s)
            projected, board = self.messages(key)
            self.assertEqual(projected['details'],expected)
            self.assertEqual(board['details']['rows'],expected['rows'])
            self.assertEqual(before,self.e.s)
            self.e.s['orders'] = [o for o in self.e.s['orders'] if o['game']!=key]
            projected, board = self.messages(key)
            self.assertNotIn('winningOrders',projected['details'])
            self.assertEqual(board['details']['rows'],expected['rows'])

    def test_empty_round_zero_net_and_same_issue_different_rooms(self):
        for key in GAMES:
            self.e.settle(key,'L000001',[1,2,3,4,5,6,7,8] if key=='australia8' else [0,0,1],'manual')
            settlement, ranking = self.messages(key)
            self.assertEqual(settlement['details']['winningOrders'],[])
            self.assertEqual(ranking['details']['game'],key)
            self.assertEqual(ranking['details']['rows'][0]['profit'],0)
            self.assertIn('(+0)',ranking['content'])

if __name__=='__main__':unittest.main()
