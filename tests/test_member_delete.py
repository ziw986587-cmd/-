import copy
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine
from unified import mutate_member
import simulated_users

class MemberDeleteTests(unittest.TestCase):
    def test_deleted_member_orders_still_settle_and_history_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            e=Engine(directory)
            for game in e.s['games']:
                e.configure(game,dict(mode='manual',period=3600,paused=False))
            mutate_member(e,'member.create','canada28',dict(username='deleteuser',nickname='待删除用户',amount=100))
            e.submit('deleteuser','canada28','1番10')
            old_orders=copy.deepcopy(e.s['orders'])
            mutate_member(e,'member.delete','canada28',dict(username='deleteuser'))
            self.assertEqual(e.s['orders'],old_orders)
            u=e.s['users']['deleteuser']
            self.assertFalse(u['enabled']);self.assertTrue(u['deleted'])
            issue=e.game('canada28')['issue']
            e.settle('canada28',issue,[0,0,1],'manual')
            order=next(o for o in e.s['orders'] if o['username']=='deleteuser')
            self.assertEqual(order['status'],'中奖')
            self.assertEqual(u['balance'],9000+order['payout'])
            self.assertEqual(u['balance'],sum(l['delta'] for l in e.s['ledger'] if l['username']=='deleteuser'))
            e.save();e=Engine(directory)
            self.assertTrue(e.s['users']['deleteuser']['deleted'])
            with self.assertRaises(ValueError):
                simulated_users.configure_batch(e,dict(username='deleteuser',enabled=True,activateMember=True,rooms=['canada28']))
            issue=e.game('canada28')['issue']
            e.settle('canada28',issue,[0,0,1],'manual')
            rows=next(m for m in reversed(e.game('canada28')['chat']) if m['kind']=='YINGLI')['details']['rows']
            self.assertFalse(any(r['username']=='deleteuser' for r in rows))

if __name__=='__main__': unittest.main()
