import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine


class Australia8WinnersTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.e=Engine(self.temp.name)
        for key in self.e.s['games']:self.e.configure(key,dict(mode='manual',period=600))

    def settle(self):
        self.e.settle('australia8',self.e.game('australia8')['issue'],[13,6,2,12,3,14,19,4],'manual')
        return next(m for m in reversed(self.e.game('australia8')['chat']) if m['kind']=='SETTLEMENT')

    def test_winners_snapshot_per_order_excludes_losses_pushes_refunds(self):
        for text,ball in [('1番10',1),('2番20',2),('1番30',8),('1念2/10',2)]:
            self.e.submit('localdemo','australia8',text,ball)
        self.e.submit('localdemo','australia8','4番10',8)
        self.e.cancel('localdemo','australia8',self.e.pending('australia8')[-1]['id'])
        message=self.settle();d=message['details']
        self.assertEqual([(o['ball'],o['amount'],o['profit']) for o in d['winningOrders']],[(1,1000,2910),(2,2000,5820)])
        self.assertEqual(d['draw']['numbers'],[13,6,2,12,3,14,19,4])
        self.e.save();self.e=Engine(self.temp.name)
        self.assertEqual(next(m for m in reversed(self.e.public('localdemo','australia8')['chat']) if m['kind']=='SETTLEMENT')['details'],d)

    def test_old_records_enriched_read_only_when_complete(self):
        self.e.submit('localdemo','australia8','1番10',1);m=self.settle()
        expected=copy.deepcopy(m['details'])
        del m['details']['winningOrders'];del m['details']['draw']
        before=copy.deepcopy(self.e.s)
        projected=next(x for x in reversed(self.e.public('localdemo','australia8')['chat']) if x['kind']=='SETTLEMENT')
        self.assertEqual(projected['details'],expected);self.assertEqual(self.e.s,before)
        self.e.s['orders'].clear()
        projected=next(x for x in reversed(self.e.public('localdemo','australia8')['chat']) if x['kind']=='SETTLEMENT')
        self.assertNotIn('winningOrders',projected['details'])

    def test_no_winner_and_other_rooms_unchanged(self):
        self.e.submit('localdemo','australia8','1番10',8)
        self.assertEqual(self.settle()['details']['winningOrders'],[])
        for key in ('canada28','australia8ball'):
            self.e.settle(key,self.e.game(key)['issue'],[0,0,1],'manual')
            d=next(x for x in reversed(self.e.game(key)['chat']) if x['kind']=='SETTLEMENT')['details']
            self.assertEqual(d['winningOrders'],[]);self.assertEqual(d['draw']['numbers'],[0,0,1])

    def test_simulated_identity_is_preserved_on_order_snapshot(self):
        self.e.s['users']['localdemo']['robot']=True
        self.e.submit('localdemo','australia8','1番10',1)
        self.e.s['users']['localdemo']['robot']=False
        self.assertTrue(self.settle()['details']['winningOrders'][0]['simulated'])


if __name__=='__main__':unittest.main()
