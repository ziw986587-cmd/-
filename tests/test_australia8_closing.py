import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'room-engine'))
from engine import Engine
import workbench
import simulated_users


class Australia8ClosingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=1800000000
        clock=patch('engine.time.time',side_effect=lambda:self.now);clock.start();self.addCleanup(clock.stop)
        self.e=Engine(self.temp.name);workbench.initialize(self.e)
        for key in self.e.s['games']:
            self.e.configure(key,dict(mode='manual',period=120,closeSeconds=10,maxBet='1000000'))
        self.e.credit('localdemo','australia8',10000000,'test','test')

    def test_warning_60_before_close_at_50_after_open_once_per_issue(self):
        self.now+=49;self.e.tick()
        self.assertFalse(any(m['kind']=='A8_CLOSE_RULES' for m in self.e.game('australia8')['chat']))
        self.now+=1;self.e.tick()
        messages=[m for m in self.e.game('australia8')['chat'] if m['kind']=='A8_CLOSE_RULES']
        self.assertEqual(len(messages),1)
        self.assertEqual(messages[0]['content'],'离封盘还剩60秒！\n60秒以内禁止取消\n开奖后0至50秒单注最高：30000\n开奖后50至110秒个人累计最高：10\n开奖后110秒起至封盘个人累计最高：不限')
        self.e.save();self.e=Engine(self.temp.name);self.now+=5;self.e.tick()
        self.assertEqual(sum(m['kind']=='A8_CLOSE_RULES' for m in self.e.game('australia8')['chat']),1)
        for key in ['canada28','australia8ball']:
            self.assertFalse(any(m['kind']=='A8_CLOSE_RULES' for m in self.e.game(key)['chat']))
        self.e.settle('australia8',self.e.game('australia8')['issue'],[1,2,3,4,5,6,7,8],'manual')
        self.now+=50;self.e.tick()
        self.assertEqual(sum(m['kind']=='A8_CLOSE_RULES' for m in self.e.game('australia8')['chat']),2)

    def test_limits_and_cancellation_at_exact_boundary(self):
        self.now+=49
        self.e.submit('localdemo','australia8','1番30000')
        before=copy.deepcopy(self.e.s)
        with self.assertRaises(ValueError):self.e.submit('localdemo','australia8','1番30000.01')
        self.assertEqual(self.e.s,before)
        self.e.cancel('localdemo','australia8')
        self.e.submit('localdemo','australia8','1番20')
        self.now+=1
        before=copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError,'禁止取消'):self.e.cancel('localdemo','australia8')
        with self.assertRaises(ValueError):self.e.submit('localdemo','australia8','1番10,2番10.01')
        self.assertEqual(self.e.s,before)
        self.e.submit('localdemo','australia8','1番10,2番10')
        self.assertEqual(self.e.public('localdemo','australia8')['limits']['maxBet'],1000)
        for key in ['canada28','australia8ball']:
            self.e.submit('localdemo',key,'1番20');self.e.cancel('localdemo',key)
        self.now+=60
        with self.assertRaises(ValueError):self.e.submit('localdemo','australia8','1番1')

    def test_lower_admin_limits_preserved_and_ordinary_admin_cancel_restricted(self):
        self.e.configure('australia8',dict(maxBet='5'))
        self.e.submit('localdemo','australia8','1番5');self.now+=50
        self.assertEqual(self.e.bet_limits('australia8')['maxBet'],500)
        with self.assertRaises(ValueError):self.e.submit('localdemo','australia8','1番5.01')
        workbench.mutate(self.e,'workbench.save','australia8',dict(reportConnected=True,failCancel=True))
        before=copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError,'禁止取消'):
            workbench.mutate(self.e,'workbench.report','australia8',dict(id=self.e.pending('australia8')[0]['id'],fail=True))
        self.assertEqual(self.e.s,before)

    def test_simulated_orders_use_same_dynamic_limit(self):
        self.e.s['users']['localdemo']['robot']=True
        simulated_users.initialize(self.e)
        simulated_users.configure(self.e,'australia8',dict(username='localdemo',enabled=True,amountMin='20',amountMax='30',selections=['1番'],intervalSeconds=5,betsPerRound=10,ball=8))
        self.now+=50;simulated_users.tick(self.e,self.now)
        self.assertEqual(self.e.pending('australia8'),[])
        self.assertEqual(self.e.s['users']['localdemo']['autoBetStatus']['australia8']['state'],'invalid-limits')

    def test_custom_threshold_boundary_persistence_and_new_round(self):
        self.e.configure('australia8',dict(a8Thresholds=dict(switchSeconds=30,firstMax='200',secondMax='25.50')))
        self.now+=29.999
        self.e.submit('localdemo','australia8','1番200')
        self.now+=.001
        before=copy.deepcopy(self.e.s)
        with self.assertRaises(ValueError):self.e.submit('localdemo','australia8','1番25.51')
        self.assertEqual(before,self.e.s)
        with self.assertRaises(ValueError):self.e.submit('localdemo','australia8','1番25.50')
        self.e.submit('localdemo','australia8','1番25')
        self.e.cancel('localdemo','australia8')  # Cancellation remains tied to closure, not the configurable switch.
        self.e.save();self.e=Engine(self.temp.name)
        self.assertEqual(self.e.public('localdemo','australia8')['limits']['maxBet'],2550)
        self.assertEqual(self.e.admin_state()['games']['australia8']['a8Thresholds']['switchSeconds'],30)
        self.e.settle('australia8',self.e.game('australia8')['issue'],[1,2,3,4,5,6,7,8],'manual')
        self.assertEqual(self.e.bet_limits('australia8')['maxBet'],20000)

    def test_threshold_validation_is_atomic_and_room_scoped(self):
        valid=dict(switchSeconds=70,firstMax='200',secondMax='30')
        for rules in [dict(valid,switchSeconds=0),dict(valid,switchSeconds=110),dict(valid,switchSeconds=1.5),dict(valid,switchSeconds=True),dict(valid,firstMax='0'),dict(valid,secondMax='NaN'),{'switchSeconds':20}]:
            before=copy.deepcopy(self.e.s)
            with self.assertRaises(ValueError):self.e.configure('australia8',dict(notice='should not persist',a8Thresholds=rules))
            self.assertEqual(before,self.e.s)
        for key in ['canada28','australia8ball']:
            with self.assertRaises(ValueError):self.e.configure(key,dict(a8Thresholds=valid))
            self.assertNotIn('a8Thresholds',self.e.admin_state()['games'][key])
        self.e.configure('australia8',dict(a8Thresholds=valid))
        before=copy.deepcopy(self.e.s)
        with self.assertRaises(ValueError):self.e.configure('australia8',dict(period=60))
        self.assertEqual(before,self.e.s)

    def test_warning_stays_at_60_and_uses_custom_schedule(self):
        self.e.configure('australia8',dict(a8Thresholds=dict(switchSeconds=70,firstMax='200',secondMax='30')))
        self.now+=50;self.e.tick()
        message=next(m['content'] for m in self.e.game('australia8')['chat'] if m['kind']=='A8_CLOSE_RULES')
        self.assertIn('离封盘还剩60秒',message)
        self.assertIn('0至70秒单注最高：200',message)
        self.assertIn('70至110秒个人累计最高：30',message)
        self.assertEqual(self.e.bet_limits('australia8')['maxBet'],20000)
        self.now+=20
        self.assertEqual(self.e.bet_limits('australia8')['maxBet'],3000)
        self.e.configure('australia8',dict(maxBet='20'))
        self.assertEqual(self.e.bet_limits('australia8')['maxBet'],2000)

    def test_three_stage_schedule_and_personal_cross_play_final_total(self):
        self.e.configure('australia8',dict(maxBet='1000',a8Thresholds=dict(
            middleSwitchSeconds=30, finalSwitchSeconds=70,
            firstMax='200', middleMax='500', finalTotal='500')))
        self.now += 20
        self.e.submit('localdemo','australia8','1番200')
        self.now += 10
        self.e.submit('localdemo','australia8','1番300')
        self.e.submit('localdemo','australia8','1角199')
        with self.assertRaises(ValueError):
            self.e.submit('localdemo','australia8','1念2')
        self.e.configure('australia8',dict(maxBet='5'))
        other=copy.deepcopy(self.e.s['users']['localdemo']);other['username']='other';other['nickname']='其他会员';self.e.s['users']['other']=other
        self.e.submit('other','australia8','1番500')
        self.now += 40
        # Each later stage starts a fresh per-user cumulative allowance.
        self.assertEqual(self.e.bet_limits('australia8',username='localdemo')['maxBet'],50000)
        self.e.submit('localdemo','australia8','1番500')
        with self.assertRaises(ValueError):
            self.e.submit('localdemo','australia8','1角1')
        self.e.submit('other','australia8','1番500')


if __name__=='__main__':unittest.main()
