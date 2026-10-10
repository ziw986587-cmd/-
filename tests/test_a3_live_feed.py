import copy, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'room-engine'))
if os.environ.get('A3_STAGE'): sys.path.insert(0, os.environ['A3_STAGE'])
from engine import Engine
import australia3_feed as feed
import draw_collector

class Australia3FeedTests(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup); self.e=Engine(d.name)
        self.key='australia8ball';self.now=1800000000
        self.cfg=dict(url=feed.URL,format='json',rootPath='',issuePath='latest.period',numbersPath='latest.numbers',nextIssuePath='currentIssue',nextTimePath='nextAt',headers={},interval=3)
        self.e.game(self.key).update(mode='external',feed=self.cfg,issue='100',endAt=self.now+120,closed=False)
    def rec(self,n,numbers=None):return dict(period=str(n),numbers=numbers or [1,2,3],openedAt=self.now-10)
    def raw(self,n=100,**kw):return dict(ok=True,game='australia3',latest=self.rec(n),currentIssue=str(n+1),nextAt=self.now+110,**kw)
    def apply(self,raw,history=None):
        with patch('engine.time.time',return_value=self.now):
            return self.e.external_result(self.key,dict(latest=raw,history=history or []),self.cfg)
    def bet(self):
        with patch('engine.time.time',return_value=self.now): self.e.submit('localdemo',self.key,'小100')
    def test_normal_next_round_and_restart_dedup(self):
        self.bet();self.apply(self.raw());g=self.e.game(self.key)
        self.assertEqual(g['issue'],'101');self.assertFalse(g['closed'])
        self.assertEqual(self.e.s['orders'][-1]['status'],'中奖')
        self.e=Engine(self.e.path.parent);before=copy.deepcopy(self.e.s);self.apply(self.raw());self.assertEqual(before,self.e.s)
    def test_unchanged_poll_does_not_copy_business_state(self):
        self.apply(self.raw());before=copy.deepcopy(self.e.s);original=copy.deepcopy
        def guarded(value,*args,**kw):
            if value is self.e.s:raise AssertionError('Unchanged poll copied all records')
            return original(value,*args,**kw)
        with patch('australia3_feed.copy.deepcopy',side_effect=guarded):self.apply(self.raw())
        self.assertEqual(before,self.e.s)
    def test_jump_backfills_correct_issue_without_inventing_gap(self):
        self.bet();latest=self.raw(103);latest['latest']['numbers']=[9,9,9]
        self.apply(latest,[self.rec(100),self.rec(102)])
        self.assertEqual(self.e.s['orders'][-1]['status'],'中奖')
        self.assertEqual([h['issue'] for h in self.e.game(self.key)['history']],['103','102','100'])
        self.assertEqual(self.e.game(self.key)['issue'],'104')
    def test_missing_pending_does_not_block_latest_then_late_result_settles(self):
        self.bet();self.apply(self.raw(103))
        self.assertEqual(self.e.s['orders'][0]['status'],'待开奖')
        self.assertEqual(self.e.game(self.key)['issue'],'104')
        self.bet();active=copy.deepcopy(self.e.game(self.key)); self.apply(self.raw(103),[self.rec(100)])
        self.assertEqual(self.e.s['orders'][0]['status'],'中奖')
        self.assertEqual(self.e.s['orders'][1]['status'],'待开奖')
        for k in ('issue','endAt','closed','warned'):self.assertEqual(self.e.game(self.key)[k],active[k])
        self.assertEqual(self.e.game(self.key)['history'][0]['issue'],'103')
        before=copy.deepcopy(self.e.s);self.apply(self.raw(103),[self.rec(100)]);self.assertEqual(before,self.e.s)
    def test_manual_and_expired_deadlines_still_settle_and_close(self):
        for nt in (None,self.now-100):
            with self.subTest(nt=nt):
                r=self.raw();r['nextAt']=nt;self.apply(r)
                self.assertEqual(self.e.game(self.key)['history'][0]['issue'],'100')
                self.assertTrue(self.e.game(self.key)['closed'])
    def test_no_change_to_other_rooms_and_unrelated_data(self):
        before=copy.deepcopy(self.e.s);self.apply(self.raw())
        for k in ('canada28','australia8'):self.assertEqual(before['games'][k],self.e.s['games'][k])
        for k in ('requests','dedup','users','orders','ledger'):self.assertEqual(before[k],self.e.s[k])
    def test_invalid_conflicting_future_data_no_partial_mutation(self):
        self.apply(self.raw());before=copy.deepcopy(self.e.s)
        bad=self.rec(100,[9,9,9])
        with self.assertRaises(ValueError):self.apply(self.raw(101),[bad])
        self.assertEqual(before,self.e.s)
        for nums in ([1,2,10],[True,2,3],[1,2],['1',2,3]):
            r=self.raw(101);r['latest']['numbers']=nums
            with self.assertRaises(ValueError):self.apply(r)
        r=self.raw(101);r['latest']['openedAt']=self.now+30
        with self.assertRaises(ValueError):self.apply(r)
        self.assertEqual(before,self.e.s)
    def test_failed_save_rolls_back_balance_orders_history(self):
        self.bet();before=copy.deepcopy(self.e.s)
        with patch.object(self.e,'save',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.apply(self.raw(102),[self.rec(100)])
        self.assertEqual(before,self.e.s)
    def test_source_regression_never_rewinds_active_round(self):
        self.apply(self.raw(103));before=copy.deepcopy(self.e.game(self.key));self.apply(self.raw(102))
        for k in ('issue','endAt','closed','warned'):self.assertEqual(before[k],self.e.game(self.key)[k])
        self.assertEqual(self.e.game(self.key)['history'][0]['issue'],'103')
    def test_fetch_gap_history_and_throttle_absent_old_issue(self):
        self.bet();calls=[]
        def fetch(cfg):
            calls.append(cfg['url']);return self.raw(103) if cfg['url']==feed.URL else dict(ok=True,records=[self.rec(102)],pages=1)
        obj=feed.fetch_payload(self.e,self.key,self.cfg,fetch);self.assertEqual(len(calls),2)
        self.apply(obj['latest'],obj['history']);feed.fetch_payload(self.e,self.key,self.cfg,fetch)
        self.assertEqual(len(calls),3)
    def test_history_network_error_does_not_stop_latest(self):
        self.bet()
        def fetch(cfg):
            if cfg['url']==feed.URL:return self.raw(103)
            raise TimeoutError()
        obj=feed.fetch_payload(self.e,self.key,self.cfg,fetch)
        with patch('engine.time.time',return_value=self.now):status=self.e.external_result(self.key,obj,self.cfg)
        self.assertIn('历史补抓暂不可用',status);self.assertEqual(self.e.game(self.key)['issue'],'104')
        self.assertEqual(self.e.s['orders'][0]['status'],'待开奖')
    def test_collector_routing_and_metrics(self):
        with patch('draw_collector.fetch_json',return_value=self.raw()) as fetch,patch('engine.time.time',return_value=self.now):
            metrics=draw_collector.sample(self.e,self.key,self.cfg)
        self.assertEqual(fetch.call_count,1);self.assertEqual(metrics['latestIssue'],'100');self.assertEqual(metrics['failures'],0)
        self.assertFalse(feed.supports('canada28',self.cfg));self.assertFalse(feed.supports(self.key,{**self.cfg,'url':'https://example.com/latest'}))
    def test_history_failure_without_bets_retries_after_restart(self):
        self.apply(self.raw(100))
        def failed(cfg):
            if cfg['url']==feed.URL:return self.raw(103)
            raise TimeoutError()
        obj=feed.fetch_payload(self.e,self.key,self.cfg,failed)
        with patch('engine.time.time',return_value=self.now):self.e.external_result(self.key,obj,self.cfg)
        self.assertEqual(self.e.game(self.key)['a3HistoryFrom'],101)
        self.e=Engine(self.e.path.parent)
        def success(cfg):return self.raw(104) if cfg['url']==feed.URL else dict(ok=True,pages=1,records=[self.rec(101),self.rec(102),self.rec(103)])
        obj=feed.fetch_payload(self.e,self.key,self.cfg,success)
        with patch('engine.time.time',return_value=self.now):self.e.external_result(self.key,obj,self.cfg)
        self.assertNotIn('a3HistoryFrom',self.e.game(self.key))
        self.assertEqual([r['issue'] for r in self.e.game(self.key)['history']],['104','103','102','101','100'])

if __name__=='__main__':unittest.main()
