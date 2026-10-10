import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, parse_bets

class NaturalPlayRules(unittest.TestCase):
    def test_formats_and_aliases(self):
        cases = {
            '1番10':'1番','1翻10':'1番','1花10':'1番','1番头10':'1番',
            '12角10':'12角','12架杆10':'12角','1车10':'123车','2推车10':'234车','124/10':'124车',
            '1念2/10':'1念2','1严2/10':'1念2','1严23/10':'1念23','1念23/10':'1念23','1+3=10':'1念3','1+23=10':'1念23',
            '1正10':'1正','1/10':'1正','3通12/10':'3通12','01-02-03特10':'01特',
        }
        for text, selection in cases.items():
            with self.subTest(text=text): self.assertEqual(parse_bets(text)[0]['selection'],selection)

    def test_natural_mod4_and_all_outcomes(self):
        with tempfile.TemporaryDirectory() as folder:
            e=Engine(folder);g=e.game('australia8ball')
            odds=dict(g['odds']);odds.update({'大/小':1,'单/双':1,'小单':1,'小双':1,'大单':1,'大双':1});e.configure('australia8ball',{'mode':'manual','period':600,'odds':odds})
            e.submit('localdemo','australia8ball','1番10,12角10,123车10,1念2/10,1念23/10,1正10,3通12/10,大10,双10')
            # 和值为6：2番，12角，123车，3通12，双；1念、1正、大小和特号按规则结算。
            e.settle('australia8ball',g['issue'],[1,2,3],'manual')
            orders=e.s['orders'];status={o['selection']:o['status'] for o in orders}
            self.assertEqual(status['1番'],'未中');self.assertEqual(status['12角'],'中奖');self.assertEqual(status['123车'],'中奖')
            self.assertEqual(status['1念2'],'和局');self.assertEqual(status['1念23'],'和局');self.assertEqual(status['1正'],'和局')
            self.assertEqual(status['3通12'],'中奖');self.assertEqual(status['大'],'未中');self.assertEqual(status['双'],'中奖')

    def test_slash_shorthand_from_chat_creates_order_and_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            e=Engine(folder)
            e.configure('australia8ball', {'mode':'manual','period':600,'maxBet':100000})
            e.message('localdemo','australia8ball','12/100',8)
            orders=e.pending('australia8ball')
            self.assertEqual(len(orders),1)
            self.assertEqual((orders[0]['selection'], orders[0]['amount']), ('12角',10000))
            self.assertTrue(any(m.get('kind') == 'RECEIPT' and '12/100' in m.get('content','')
                                for m in e.game('australia8ball')['chat']))
            e.message('localdemo','australia8ball','12／100',8)
            self.assertEqual([o['selection'] for o in e.pending('australia8ball')], ['12角','12角'])

    def test_yan_alias_from_chat_uses_nian_settlement(self):
        with tempfile.TemporaryDirectory() as folder:
            e=Engine(folder)
            e.configure('canada28', {'mode':'manual','period':600,'maxBet':100000})
            e.message('localdemo','canada28','1严2/300',8)
            order=e.pending('canada28')[0]
            self.assertEqual((order['selection'], order['amount']), ('1念2',30000))
            self.assertTrue(any(m.get('kind') == 'RECEIPT' and '1严2/300' in m.get('content','')
                                for m in e.game('canada28')['chat']))

if __name__=='__main__':unittest.main()
