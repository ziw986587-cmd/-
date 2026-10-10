import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES
import member_rebate
import workbench


class MemberRebateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = patch('engine.time.time', return_value=1800000000)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.e = Engine(self.temp.name)
        workbench.initialize(self.e)
        self.e.s['users']['localdemo']['rebate'] = 1.5
        for game, amount in zip(GAMES, [10, 20, 30]):
            self.e.configure(game, {'mode':'manual','period':120})
            self.e.submit('localdemo', game, '1番'+str(amount))
            self.e.settle(game, self.e.game(game)['issue'],
                          [0,0,1] if game!='australia8' else [2,3,4,5,6,7,8,1], 'manual')

    def pay(self, plan=None):
        plan = plan or member_rebate.preview(self.e, 'localdemo')
        return member_rebate.pay(self.e, 'canada28', dict(username='localdemo',
            fingerprint=plan['fingerprint'], confirmed=True))

    def test_three_rooms_exact_credit_and_persistent_no_duplicate(self):
        before=copy.deepcopy(self.e.s)
        plan=member_rebate.preview(self.e, 'localdemo')
        self.assertEqual(self.e.s,before)
        self.assertEqual((plan['count'],plan['turnover'],plan['amount']), (3,6000,90))
        self.pay(plan)
        user=self.e.s['users']['localdemo']
        self.assertEqual(user['balance'],before['users']['localdemo']['balance']+90)
        self.assertEqual(set(user['wallets'].values()),{user['balance']})
        self.assertEqual(self.e.s['ledger'][-1]['rebateScope'],'all')
        self.assertEqual(len(self.e.s['rebateBatches'][0]['orderIds']),3)
        for game in GAMES:
            workbench.mutate(self.e,'workbench.stats.reset',game,{})
        self.e.save()
        self.e=Engine(self.temp.name)
        self.assertEqual(member_rebate.preview(self.e,'localdemo')['count'],0)
        unchanged=copy.deepcopy(self.e.s)
        with self.assertRaises(ValueError):self.pay(plan)
        self.assertEqual(self.e.s,unchanged)
        self.assertEqual(user['balance'],sum(l['delta'] for l in self.e.s['ledger'] if l['username']=='localdemo'))

    def test_pending_refunded_legacy_and_other_members_excluded(self):
        self.e.submit('localdemo','canada28','1番5')
        self.e.cancel('localdemo','canada28')
        self.e.submit('localdemo','canada28','1番6')
        for changes in [dict(id='legacy',legacy=True),dict(id='other',username='another')]:
            self.e.s['orders'].append({**self.e.s['orders'][0],**changes})
        plan=member_rebate.preview(self.e,'localdemo')
        self.assertEqual((plan['count'],plan['turnover']),(3,6000))
        self.pay()
        self.e.settle('canada28',self.e.game('canada28')['issue'],[0,0,1],'manual')
        self.assertEqual(member_rebate.preview(self.e,'localdemo')['turnover'],600)

    def test_changed_rate_or_settlement_invalidates_confirmation(self):
        plan=member_rebate.preview(self.e,'localdemo')
        self.e.s['users']['localdemo']['rebate']=2
        before=copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError,'变化'):self.pay(plan)
        self.assertEqual(self.e.s,before)
        plan=member_rebate.preview(self.e,'localdemo')
        self.e.submit('localdemo','canada28','1番1')
        self.e.settle('canada28',self.e.game('canada28')['issue'],[0,0,1],'manual')
        before=copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError,'变化'):self.pay(plan)
        self.assertEqual(self.e.s,before)

    def test_zero_invalid_rate_and_rounding(self):
        for rate in [0,-1,101,float('nan'),float('inf')]:
            self.e.s['users']['localdemo']['rebate']=rate
            with self.assertRaises(ValueError):self.pay()
        self.e.s['users']['localdemo']['rebate']=0.00001
        with self.assertRaisesRegex(ValueError,'不足'):self.pay()
        self.assertTrue(all(not o.get('rebateBatch') for o in self.e.s['orders']))
        self.e.s['users']['localdemo']['rebate']=0.025
        self.assertEqual(member_rebate.preview(self.e,'localdemo')['amount'],2)


if __name__=='__main__':unittest.main()
