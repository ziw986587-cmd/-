import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, SUM_ROOMS, SUM_GROUPS, SUM_ODDS, RULES, parse_bets
import simulated_users


class SumPlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.e = Engine(self.temp.name)
        for key in self.e.s['games']:
            self.e.configure(key, {'mode': 'manual', 'period': 600})

    def enable(self, key):
        odds = dict(self.e.game(key)['odds'])
        odds.update({'大/小': .8, '单/双': .9, '小单': 2.5, '小双': 2.6, '大单': 3.1, '大双': 3.2})
        self.e.configure(key, {'odds': odds})

    def test_all_sums_all_eight_selections_and_fans(self):
        for key in SUM_ROOMS:
            self.enable(key)
            for total in range(28):
                numbers = [min(total, 9), min(max(total - 9, 0), 9), max(total - 18, 0)]
                fan = total % 4 or 4
                size = '大' if total >= 14 else '小'
                parity = '单' if total % 2 else '双'
                winning = {size, parity, size+parity}
                before = self.e.s['users']['localdemo']['balance']
                self.e.submit('localdemo',key,','.join(s+'10' for s in SUM_GROUPS))
                orders = self.e.pending(key)
                self.e.settle(key,self.e.game(key)['issue'],numbers,'manual')
                for o in orders:
                    with self.subTest(key=key,total=total,selection=o['selection']):
                        win = o['selection'] in winning
                        self.assertEqual(o['status'],'中奖' if win else '未中')
                        self.assertEqual(o['profit'],round(1000*o['rate']) if win else -1000)
                self.assertEqual(self.e.s['users']['localdemo']['balance'],before+sum(o['profit'] for o in orders))
                draw = self.e.game(key)['history'][0]
                natural = int(''.join(map(str, numbers)))
                self.assertEqual((draw['total'],draw['special'],draw['fan'],draw['drawRule'],draw['settlementRule']),(total,natural%20 or 20,fan,'sum3','sum-v4'))

    def test_old_pending_and_new_orders_have_distinct_rules_and_locked_rates(self):
        for key in SUM_ROOMS:
            self.enable(key)
            self.e.submit('localdemo',key,'大10,1番10')
            old = self.e.pending(key)
            for o in old: o.pop('settlementRule')
            self.e.submit('localdemo',key,'大10,1番10,小单10')
            new = self.e.pending(key)[2:]
            # 9+1+7=17 -> 1番、大单；新规则按真实和值判大单。
            odds = dict(self.e.game(key)['odds']); odds['大/小']=9
            self.e.configure(key,{'odds':odds})
            self.e.save(); self.e=Engine(self.temp.name)
            self.e.settle(key,self.e.game(key)['issue'],[9,1,7],'manual')
            settled=self.e.s['orders'][-5:]
            self.assertEqual([o['status'] for o in settled],['未中','中奖','中奖','中奖','未中'])
            self.assertEqual(settled[2]['profit'],800)
        # Distinguish Canada's old last-two fan from new sum fan.
        key='canada28'
        self.e.submit('localdemo',key,'1番10');self.e.pending(key)[0].pop('settlementRule')
        self.e.submit('localdemo',key,'2番10')
        self.e.settle(key,self.e.game(key)['issue'],[1,0,1],'manual')
        self.assertEqual([o['status'] for o in self.e.s['orders'][-2:]],['中奖','中奖'])

    def test_unconfigured_and_invalid_batch_are_atomic(self):
        for key in SUM_ROOMS:
            self.assertIsNone(self.e.game(key)['odds']['小单'])
            for text in ['1番10,小单10','小单0','大双-1','小单10,垃圾','大小10','单小10']:
                before=copy.deepcopy(self.e.s)
                with self.assertRaises(ValueError):self.e.submit('localdemo',key,text)
                self.assertEqual(self.e.s,before)
            self.enable(key)
            self.e.message('localdemo',key,'小单10，大双/20',8)
            self.assertEqual([o['selection'] for o in self.e.pending(key)],['小单','大双'])

    def test_config_validation_migration_and_a8_unchanged(self):
        for key in SUM_ROOMS:
            self.enable(key)
            for value in [-1,0,101,True,'2',float('nan')]:
                before=copy.deepcopy(self.e.s);odds=dict(self.e.game(key)['odds']);odds['小单']=value
                with self.assertRaises(ValueError):self.e.configure(key,{'odds':odds})
                self.assertEqual(self.e.s,before)
            self.e.configure(key,{'odds':dict(RULES)})
            self.assertEqual(self.e.game(key)['odds']['小单'],2.5)
            for group in SUM_ODDS:self.e.game(key)['odds'].pop(group)
        self.e.save();self.e=Engine(self.temp.name)
        for key in SUM_ROOMS:
            self.assertEqual(self.e.game(key)['odds']['大/小'],.97)
            self.assertIsNone(self.e.game(key)['odds']['小单'])
            self.assertNotIn('大小单双',self.e.public('localdemo',key)['odds'])
        self.assertEqual(self.e.game('australia8')['odds'],{**RULES, **dict.fromkeys(('小单','小双','大单','大双'))})
        before=copy.deepcopy(self.e.s)
        with self.assertRaises(ValueError):self.e.submit('localdemo','australia8','小单10')
        self.assertEqual(self.e.s,before)
        self.e.submit('localdemo','australia8','大10,双10')
        self.e.settle('australia8',self.e.game('australia8')['issue'],[1,2,3,4,5,6,7,8],'manual')
        self.assertEqual([o['status'] for o in self.e.s['orders']],['未中','中奖'])

    def test_simulated_config_obeys_room_and_enabled_rates(self):
        self.e.s['users']['localdemo']['robot']=True
        data=dict(username='localdemo',enabled=True,amountMin='1',amountMax='2',selections=['小单'],intervalSeconds=10,betsPerRound=1)
        for key in ('canada28','australia8'):
            with self.assertRaises(ValueError):simulated_users.configure(self.e,key,data)
        self.enable('canada28')
        simulated_users.configure(self.e,'canada28',data)

    def test_split_migrates_old_rates_and_preserves_pending_snapshots(self):
        for key in SUM_ROOMS:
            self.enable(key)
            self.e.submit('localdemo',key,'小单10,小双10')
            odds=self.e.game(key)['odds']
            for k in ('小单','小双','大单','大双'):odds.pop(k)
            odds.update({'小单/小双':2.5,'大单/大双':None})
        old_orders=copy.deepcopy(self.e.s['orders'])
        self.e.save();self.e=Engine(self.temp.name)
        self.assertEqual(self.e.s['orders'],old_orders)
        for key in SUM_ROOMS:
            odds=self.e.game(key)['odds']
            self.assertNotIn('小单/小双',odds)
            self.assertEqual((odds['小单'],odds['小双'],odds['大单'],odds['大双']),(2.5,2.5,None,None))
            self.e.configure(key,{'odds':{**odds,'小单':None,'小双':8}})
            with self.assertRaisesRegex(ValueError,'尚未设置'):self.e.submit('localdemo',key,'小单10')
            self.e.submit('localdemo',key,'小双10')
            self.e.settle(key,self.e.game(key)['issue'],[0,0,0],'manual')
            orders=[o for o in self.e.s['orders'] if o['game']==key]
            self.assertEqual([o['profit'] for o in orders],[-1000,2600,8000])
            before=copy.deepcopy(self.e.s)
            with self.assertRaisesRegex(ValueError,'刷新'):
                self.e.configure(key,{'odds':{**odds,'小单/小双':9}})
            self.assertEqual(self.e.s,before)
        self.e.save();self.e=Engine(self.temp.name)
        for key in SUM_ROOMS:
            self.assertIsNone(self.e.game(key)['odds']['小单'])
            self.assertEqual(self.e.game(key)['odds']['小双'],8)


if __name__ == '__main__':unittest.main()
