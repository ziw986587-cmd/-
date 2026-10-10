import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine
import workbench


class AccountingViewTests(unittest.TestCase):
    def test_turnover_and_effective_turnover_rules(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(folder);workbench.initialize(engine)
            engine.s['orders']=[
                dict(username='localdemo',game='canada28',status='未中',amount=200,profit=-200),
                dict(username='localdemo',game='canada28',status='中奖',amount=200,profit=100),
                dict(username='localdemo',game='canada28',status='和局',amount=200,profit=0),
                dict(username='localdemo',game='canada28',status='待开奖',amount=200,profit=None),
                dict(username='localdemo',game='canada28',status='已退单',amount=200,profit=0),
            ]
            stats=workbench.view(engine,'canada28')['memberStats']['localdemo']
            self.assertEqual(stats,dict(turnover=800,effectiveTurnover=300,profit=-100))

    def test_full_history_room_totals_reset_and_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(folder);workbench.initialize(engine)
            engine.s['orders']=[dict(username='localdemo',game='canada28',status='中奖',amount=100,profit=200) for _ in range(510)]
            engine.s['orders'] += [dict(username='localdemo',game='australia8',status='未中',amount=500,profit=-500),
                                   dict(username='localdemo',game='australia8ball',status='待开奖',amount=600,profit=None),
                                   dict(username='localdemo',game='canada28',status='已退单',amount=10000,profit=0)]
            before=copy.deepcopy(engine.s)
            view=workbench.view(engine,'canada28')
            self.assertEqual(view['memberStats']['localdemo'],dict(turnover=51000,effectiveTurnover=102000,profit=102000))
            self.assertEqual(view['memberStatsByRoom']['australia8']['localdemo'],dict(turnover=500,effectiveTurnover=500,profit=-500))
            self.assertEqual(view['memberStatsByRoom']['australia8ball']['localdemo'],dict(turnover=600,effectiveTurnover=0,profit=0))
            self.assertEqual(engine.s,before)
            engine.s['workbench']['canada28']['statFrom']=500
            view=workbench.view(engine,'canada28')
            self.assertEqual(view['memberStats']['localdemo'],dict(turnover=1000,effectiveTurnover=2000,profit=2000))
            self.assertEqual(view['memberStatsByRoom']['australia8']['localdemo']['turnover'],500)


if __name__=='__main__':unittest.main()
