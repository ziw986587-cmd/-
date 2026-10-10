import copy
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES, Handler
import robot_messages
import force_open


class RobotMessagesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.e=Engine(self.temp.name)
        self.user=self.e.s['users']['localdemo']
        self.user['nickname']='小明{金额}<b>'
        for game in GAMES:
            self.e.configure(game,dict(mode='manual',period=3600,minBet='1',maxBet='1000',bot=True))

    def payload(self,game):
        c=robot_messages.config(self.e,game)
        return dict(revision=c['revision'],name=c['name'],bot=c['bot'],entries={r['key']:dict(text=r['text'],enabled=r['enabled']) for r in c['entries']})

    def mutate(self,method,game,**data):
        return Handler.mutate(SimpleNamespace(engine=self.e),'/api/admin/'+method,'localadmin',game,data)

    def test_all_live_templates_receive_their_documented_variables(self):
        for game in GAMES:
            payload=self.payload(game)
            for row in robot_messages.catalog(game):
                payload['entries'][row['key']]['text']=row['key']+'|'+'|'.join('{'+key+'}' for key in row['sample'])
            payload['name']='房间助手'
            robot_messages.save(self.e,game,payload)
            self.e.submit('localdemo',game,'1番10',8)
            self.e.message('localdemo',game,'查',8)
            self.assertTrue(self.e.game(game)['chat'][-1]['content'].startswith('balance|'))
            self.assertTrue(self.e.message('localdemo',game,'帮助',8).startswith('help|'))
            self.e.cancel('localdemo',game)
            for action in ('上分','下分'):
                self.e.request_score('localdemo',game,action,100)
                self.mutate('review',game,id=self.e.s['requests'][-1]['id'],approve=True)
                self.mutate('score',game,username='localdemo',action=action,amount=10)
            self.e.request_score('localdemo',game,'下分',1)
            self.mutate('review',game,id=self.e.s['requests'][-1]['id'],approve=False)
            self.mutate('refund',game)
            self.e.submit('localdemo',game,'1番10',8)
            self.e.game(game).update(endAt=time.time()+45,warned=False)
            self.e.tick()
            numbers=[2,3,4,5,6,7,8,1] if game=='australia8' else [0,0,1]
            self.e.settle(game,self.e.game(game)['issue'],numbers,'manual')
            messages=[m for m in self.e.game(game)['chat'] if m.get('details',{}).get('robotTemplate')]
            keys={m['details']['robotTemplate'] for m in messages}
            expected={r['key'] for r in robot_messages.catalog(game)}-{'force_open','force_refund','ready','help'}
            self.assertEqual(keys,expected)
            self.assertTrue(all(m['who']=='房间助手' for m in messages))
            self.assertIn('小明{金额}<b>',next(m['content'] for m in messages if m['kind']=='RECEIPT'))
            winner=next(m for m in messages if m['kind']=='SETTLEMENT')
            self.assertIn('盈：29.10',winner['content'])

    def test_validation_is_atomic_and_revisions_prevent_lost_edits(self):
        original=self.payload('canada28')
        for invalid in ['{不支持}', '{昵称.__class__}', '{金额', '', 'x'*2001]:
            bad=copy.deepcopy(original);bad['entries']['up_request']['text']=invalid
            before=copy.deepcopy(self.e.s)
            with self.assertRaises(ValueError):robot_messages.save(self.e,'canada28',bad)
            self.assertEqual(before,self.e.s)
        robot_messages.save(self.e,'canada28',original)
        self.assertEqual(self.e.game('canada28')['robotMessages'],{})
        with self.assertRaises(ValueError):robot_messages.save(self.e,'canada28',original)

    def test_disabled_reply_does_not_disable_orders_and_room_config_persists(self):
        payload=self.payload('canada28');payload['entries']['receipt']['enabled']=False
        payload['entries']['down_request']['text']='@{昵称} 请求下分{金额}'
        robot_messages.save(self.e,'canada28',payload)
        before=len(self.e.game('canada28')['chat']);balance=self.user['balance']
        self.e.submit('localdemo','canada28','1番10')
        self.assertEqual(len(self.e.game('canada28')['chat']),before+1)
        self.assertEqual(self.user['balance'],balance-1000)
        self.e.save();self.e=Engine(self.temp.name)
        self.e.request_score('localdemo','canada28','下分',2)
        self.assertEqual(self.e.game('canada28')['chat'][-1]['content'],'@小明{金额}<b> 请求下分2')
        self.e.request_score('localdemo','australia8','下分',2)
        self.assertIn('待管理员审核',self.e.game('australia8')['chat'][-1]['content'])

    def test_historical_text_keeps_its_template_snapshot_and_reset_works(self):
        game='canada28';payload=self.payload(game);payload['entries']['up_request']['text']='旧版{金额}'
        robot_messages.save(self.e,game,payload);self.e.request_score('localdemo',game,'上分',1)
        old=copy.deepcopy(self.e.game(game)['chat'][-1]);payload=self.payload(game)
        payload['entries']['up_request']['text']='新版{金额}';robot_messages.save(self.e,game,payload)
        self.e.request_score('localdemo',game,'上分',2)
        self.assertEqual(self.e.game(game)['chat'][-2],old)
        self.assertEqual(self.e.game(game)['chat'][-1]['content'],'新版2')
        payload=self.payload(game);payload['entries']['up_request']['text']=next(r['default'] for r in robot_messages.catalog(game) if r['key']=='up_request')
        robot_messages.save(self.e,game,payload);self.e.request_score('localdemo',game,'上分',3)
        self.assertNotIn('robotTemplate',self.e.game(game)['chat'][-1].get('details',{}))

    def test_forced_open_templates_and_global_switch(self):
        game='canada28';payload=self.payload(game)
        for key in ['force_open','force_refund']:
            payload['entries'][key]['text']='自定义'+payload['entries'][key]['text']
        robot_messages.save(self.e,game,payload)
        self.e.configure(game,dict(mode='external',period=210,feed=dict(format='pc28-history',interval=2,url='https://example.invalid')))
        g=self.e.game(game);g.update(issue='100',closed=False,endAt=time.time()+210)
        self.e.submit('localdemo',game,'1番10')
        g['closed']=True
        with patch('force_open.read_latest',return_value=[('200',[8,0,9])]):
            force_open.run(self.e,game,dict(issue='100',latestIssue='200',pendingIds=sorted(o['id'] for o in self.e.pending(game)),confirmed=True,refundConfirmed=True))
        self.assertEqual({m.get('details',{}).get('robotTemplate') for m in g['chat'] if m['content'].startswith('自定义')},{'force_open','force_refund'})
        payload=self.payload(game);payload['bot']=False;robot_messages.save(self.e,game,payload)
        before=len(g['chat']);self.e.request_score('localdemo',game,'上分',1)
        self.assertEqual(len(g['chat']),before)


if __name__=='__main__':unittest.main()
