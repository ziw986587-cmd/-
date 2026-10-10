import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine
from unified import mutate_member


class CloseFooterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.e = Engine(self.temp.name)
        for key in self.e.s['games']: self.e.configure(key, {})

    def test_all_rooms_have_fixed_title_and_independent_footer(self):
        for i, key in enumerate(self.e.s['games']):
            self.e.configure(key, {'closeFooter': f'联系方式：qq{i}\n服务时间：全天'})
        self.e.save(); self.e = Engine(self.temp.name)
        for i, key in enumerate(self.e.s['games']):
            self.e.close_round(key)
            messages = [m for m in self.e.game(key)['chat'] if m['kind'] == 'HEDUI']
            self.assertEqual(len(messages), 1)
            text = messages[0]['content']
            self.assertTrue(text.startswith(self.e.game(key)['issue']+'期已封盘\n'))
            self.assertIn('期核对列表\n', text)
            self.assertTrue(text.endswith(f'以系统注单记录和退单状态为准。\n联系方式：qq{i}\n服务时间：全天'))
            self.e.close_round(key)
            self.assertEqual(len([m for m in self.e.game(key)['chat'] if m['kind']=='HEDUI']),1)

    def test_clearing_affects_future_messages_only(self):
        key='canada28'; self.e.configure(key, {'closeFooter':'旧联系信息'})
        self.e.close_round(key); old=copy.deepcopy(self.e.game(key)['chat'][-1])
        self.e.configure(key, {'closeFooter':''})
        self.assertEqual(self.e.game(key)['chat'][-1],old)
        self.e.game(key).update(closed=False,issue='L000002')
        self.e.close_round(key)
        self.assertTrue(self.e.game(key)['chat'][-1]['content'].endswith('以系统注单记录和退单状态为准。'))

    def test_close_groups_accounts_and_preserves_full_names_and_ball_positions(self):
        self.e.s['users']['localdemo']['nickname'] = '老兵甲'
        mutate_member(self.e, 'member.create', 'canada28', dict(username='other', nickname='老兵乙', amount=1000))
        for key in self.e.s['games']:
            self.e.configure(key, dict(mode='manual', period=3600, minBet=1, maxBet=1000, paused=False))
            self.e.submit('localdemo', key, '2正10', 1)
            self.e.submit('other', key, '1番20', 8)
            self.e.submit('localdemo', key, '2番30,13无4/40', 3)
            self.e.close_round(key)
            message = next(m for m in reversed(self.e.game(key)['chat']) if m['kind']=='HEDUI')
            orders = message['details']['closeOrders']
            self.assertEqual(len(orders), 4)
            self.assertEqual([r['username'] for r in orders].count('localdemo'), 3)
            self.assertEqual(message['content'].count('(老兵甲)'), 1)
            self.assertEqual(message['content'].count('(老兵乙)'), 1)
            expected = '第1球 2正10, 第3球 2番30, 第3球 13无4/40' if key=='australia8' else '2正10, 2番30, 13无4/40'
            self.assertIn('(老兵甲) “'+expected+'”', message['content'])
            before = copy.deepcopy(self.e.s)
            self.e.public('localdemo', key)
            self.assertEqual(self.e.s, before)
        self.assertEqual(self.e.s['users']['localdemo']['nickname'], '老兵甲')

    def test_validation_is_atomic_and_partial_config_preserves_footer(self):
        self.e.configure('australia8', {'closeFooter':'  联系方式：qq123\r\n第二行  '})
        self.e.configure('australia8', {'notice':'公告'})
        self.assertEqual(self.e.admin_state()['games']['australia8']['closeFooter'],'联系方式：qq123\n第二行')
        for value in ['x'*501,None,10,{}]:
            before=copy.deepcopy(self.e.s)
            with self.assertRaises(ValueError):self.e.configure('australia8',{'closeFooter':value,'notice':'不应保存'})
            self.assertEqual(self.e.s,before)

    def test_old_messages_project_title_without_rewriting_or_changing_member_text(self):
        key='canada28';self.e.bot(key,'L000001期停止\n核对列表\n客户文字：停止','HEDUI')
        self.e.chat(key,'L000001期停止\n用户消息','localdemo',kind='HEDUI')
        before=copy.deepcopy(self.e.s)
        chat=self.e.public('localdemo',key)['chat']
        self.assertEqual(chat[-2]['content'],'L000001期已封盘\n核对列表\n客户文字：停止')
        self.assertEqual(chat[-1]['content'],'L000001期停止\n用户消息')
        self.assertEqual(self.e.s,before)


if __name__=='__main__':unittest.main()
