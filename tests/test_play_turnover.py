import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
import turnover
import member_rebate
import workbench
from tests.test_member_rebate import MemberRebateTests

CASES = json.loads(Path(__file__).with_name('turnover-cases.json').read_text(encoding='utf-8'))


class PlayTurnoverTests(unittest.TestCase):
    def test_all_plays_and_statuses_use_confirmed_rules(self):
        for case in CASES:
            for status in ['中奖', '未中', '和局', '待开奖', '已退单', '已取消']:
                with self.subTest(selection=case['selection'], amount=case['amount'], status=status):
                    order = {**case, 'status':status}
                    expected = case['expected'] if status == '中奖' else case['amount'] if status == '未中' else 0
                    before = copy.deepcopy(order)
                    for calculate in [turnover.effective_turnover, member_rebate.effective_turnover, workbench.effective_turnover]:
                        self.assertEqual(calculate(order), expected)
                    self.assertEqual(order, before)


class RebateConfirmationTests(unittest.TestCase):
    setUp = MemberRebateTests.setUp

    def test_changed_selection_rejects_stale_preview(self):
        plan = member_rebate.preview(self.e, 'localdemo')
        self.e.s['orders'][0]['selection'] = '123车'
        before = copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError, '变化'):
            member_rebate.pay(self.e, 'canada28', dict(username='localdemo', fingerprint=plan['fingerprint'], confirmed=True))
        self.assertEqual(self.e.s, before)
