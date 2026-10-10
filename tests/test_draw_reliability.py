import copy
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine
import draw_collector
import history_feed


class DrawReliabilityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.e = Engine(directory.name)
        self.e.configure('canada28', dict(mode='external', period=210,
            feed=dict(format='pc28-history', interval=2, url='https://example.invalid/history')))
        self.cfg = self.e.game('canada28')['feed']
        self.now = 1800000000

    def row(self, issue, opened=None, code='8,0,9'):
        opened = self.now-30 if opened is None else opened
        return dict(expect=str(issue), opencode=code, lottery_id='2', opentime=opened, createtime=opened+20)

    def apply(self, rows):
        with patch('engine.time.time', return_value=self.now):
            return self.e.external_result('canada28', {'data': {'list': rows}}, self.cfg)

    def test_uses_actual_draw_time_not_delayed_receipt_or_creation(self):
        self.apply([self.row(100)])
        g = self.e.game('canada28')
        self.assertEqual(g['endAt'], self.now+180)
        self.assertEqual(g['history'][0]['sourceOpenTime'], self.now-30)
        self.assertEqual(g['history'][0]['sourcePublishedAt'], self.now-10)
        self.assertEqual(g['history'][0]['receivedAt'], self.now)
        self.assertFalse(g['closed'])

    def test_reconnect_without_bets_replays_all_contiguous_results(self):
        self.apply([self.row(100)])
        self.now += 630
        self.apply([self.row(103), self.row(101, self.now-450), self.row(102, self.now-240)])
        g = self.e.game('canada28')
        self.assertEqual([h['issue'] for h in g['history']], ['103','102','101','100'])
        self.assertEqual(g['issue'], '104')
        self.assertEqual(g['endAt'], self.now+180)

    def test_reconnect_settles_correct_issue_exactly_once(self):
        self.apply([self.row(100)])
        with patch('engine.time.time', return_value=self.now): self.e.submit('localdemo','canada28','1番10')
        balance = self.e.s['users']['localdemo']['balance']
        self.now += 630
        rows = [self.row(101,self.now-450),self.row(102,self.now-240,'1,1,1'),self.row(103)]
        self.apply(rows)
        self.assertEqual(self.e.s['orders'][-1]['status'], '中奖')
        after = copy.deepcopy(self.e.s)
        self.assertGreater(after['users']['localdemo']['balance'], balance)
        self.apply(rows)
        self.assertEqual(self.e.s, after)

    def test_missing_intermediate_result_does_not_block_new_draws(self):
        self.apply([self.row(100)])
        self.apply([self.row(102)])
        self.assertEqual(self.e.game('canada28')['issue'],'103')
        self.assertEqual(self.e.game('canada28')['feedGaps'],[[101,101]])
        self.apply([self.row(101),self.row(102)])
        self.assertEqual(self.e.game('canada28')['issue'], '103')
        self.assertNotIn('feedGaps',self.e.game('canada28'))

    def test_conflict_in_batch_has_no_partial_settlement(self):
        self.apply([self.row(100)])
        before = copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError,'修改已记录'):
            self.apply([self.row(101),self.row(100,code='1,2,3')])
        self.assertEqual(before,self.e.s)

    def test_save_failure_rolls_back_memory_and_retry_pays_once(self):
        self.apply([self.row(100)])
        with patch('engine.time.time', return_value=self.now): self.e.submit('localdemo','canada28','1番10')
        before = copy.deepcopy(self.e.s)
        with patch.object(self.e,'save',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): self.apply([self.row(101)])
        self.assertEqual(self.e.s,before)
        self.apply([self.row(101)])
        after = copy.deepcopy(self.e.s)
        self.apply([self.row(101)])
        self.assertEqual(self.e.s,after)

    def test_restart_rejects_source_regression_using_persisted_history(self):
        self.apply([self.row(100)])
        self.e = Engine(self.e.path.parent)
        self.cfg = self.e.game('canada28')['feed']
        with self.assertRaisesRegex(ValueError,'较旧'): self.apply([self.row(99)])
        self.assertEqual(self.e.game('canada28')['issue'],'101')

    def test_duplicate_after_restart_calibrates_without_payout_or_messages(self):
        self.apply([self.row(100)])
        g = self.e.game('canada28');g['endAt'] += 30;self.e.save()
        before_count = len(g['chat'])
        self.e = Engine(self.e.path.parent);self.cfg = self.e.game('canada28')['feed']
        self.apply([self.row(100)])
        self.assertEqual(self.e.game('canada28')['endAt'], self.now+180)
        self.assertEqual(len(self.e.game('canada28')['chat']), before_count)

    def test_late_result_and_future_timestamp_never_open_for_full_new_cycle(self):
        self.apply([self.row(100,self.now-300)])
        self.assertTrue(self.e.game('canada28')['closed'])
        before = copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError,'未来'): self.apply([self.row(101,self.now+50)])
        self.assertEqual(self.e.s,before)

    def test_prediction_nested_inside_real_row_is_not_a_result(self):
        row=self.row(100);row['predict']={'1':dict(expect='100',lottery_id=2,scheme_id=1,opencode='1,2,3')}
        self.apply([row]);self.assertEqual(self.e.game('canada28')['history'][0]['numbers'],[8,0,9])

    def test_pause_and_reconfigure_during_fetch_discards_response(self):
        def fetch(_): self.e.game('canada28')['paused']=True;return {'data':[self.row(100)]}
        with patch('draw_collector.fetch_json',side_effect=fetch):
            self.assertIsNone(draw_collector.sample(self.e,'canada28',copy.deepcopy(self.cfg)))
        self.assertEqual(self.e.game('canada28')['history'],[])
        self.e.game('canada28')['paused']=False
        def changed(_): self.e.game('canada28')['feed']['url']='https://new.invalid';return {'data':[self.row(100)]}
        with patch('draw_collector.fetch_json',side_effect=changed):
            self.assertIsNone(draw_collector.sample(self.e,'canada28',copy.deepcopy(self.cfg)))
        self.assertEqual(self.e.game('canada28')['history'],[])

    def test_diagnostics_distinguish_network_and_source_delay(self):
        with patch('draw_collector.fetch_json',return_value={'data':[self.row(100)]}),patch('engine.time.time',return_value=self.now),patch('sys.stderr',new_callable=io.StringIO) as log:
            metrics=draw_collector.sample(self.e,'canada28',self.cfg)
        self.assertEqual(metrics['publishDelaySeconds'],20)
        self.assertEqual(metrics['receiptLagSeconds'],10)
        self.assertNotIn('example.invalid',log.getvalue())
        self.assertIn('源站发布延迟20秒',self.e.feed_status['canada28'])

    def test_slow_room_does_not_block_other_room_or_business_lock(self):
        entered,release,other=threading.Event(),threading.Event(),threading.Event()
        stop=threading.Event()
        self.e.game('australia8').update(mode='external',paused=False)
        def fetch(cfg):
            if cfg['url']==self.cfg['url']:
                entered.set();release.wait(3);return {'data':[self.row(100)]}
            other.set();raise TimeoutError()
        with patch('draw_collector.fetch_json',side_effect=fetch),patch('sys.stderr',new_callable=io.StringIO):
            worker=threading.Thread(target=draw_collector.run,args=(self.e,stop));worker.start()
            try:
                self.assertTrue(entered.wait(2));self.assertTrue(other.wait(2))
                acquired=self.e.lock.acquire(timeout=.2);self.assertTrue(acquired)
                if acquired:self.e.lock.release()
            finally:stop.set();release.set();worker.join(5)
        self.assertFalse(worker.is_alive())


class TransportTests(unittest.TestCase):
    def test_bounded_retry_and_server_retry_after(self):
        error=TimeoutError()
        self.assertEqual([draw_collector.retry_delay(error,n,2) for n in range(1,7)],[2,4,8,16,30,30])
        limited=urllib.error.HTTPError('https://secret.invalid',429,'limited',{'Retry-After':'60'},None)
        self.assertEqual(draw_collector.retry_delay(limited,1,2),60)
        self.assertEqual(draw_collector.retry_delay(ValueError('missing period'),9,2),2)

    def test_http_denial_does_not_retry_until_configuration_changes(self):
        class FakeEngine:
            lock=threading.RLock()
            feed_status={}
            feed_metrics={}
            def game(self,key): return dict(mode='external',paused=False,feed=dict(url='https://example.invalid',headers={},interval=2))
        stop=threading.Event()
        error=urllib.error.HTTPError('https://example.invalid',403,'denied',{},None)
        with patch('draw_collector.sample',side_effect=error) as fetch,patch('sys.stderr',new_callable=io.StringIO):
            worker=threading.Thread(target=draw_collector.run_room,args=(FakeEngine(),'canada28',stop))
            worker.start()
            try:
                time.sleep(.6)
                self.assertEqual(fetch.call_count,1)
            finally: stop.set();worker.join(2)

    def test_timeout_recovers_and_clears_failure_status(self):
        class FakeEngine:
            lock=threading.RLock()
            feed_status={}
            feed_metrics={}
            def game(self,key): return dict(mode='external',paused=False,feed=dict(url='https://example.invalid',headers={},interval=2))
        stop=threading.Event();calls=[]
        def sample(*args):
            calls.append(1)
            if len(calls)==1:raise TimeoutError()
            stop.set()
        with patch('draw_collector.sample',side_effect=sample),patch('draw_collector.retry_delay',return_value=.01),patch('sys.stderr',new_callable=io.StringIO):
            worker=threading.Thread(target=draw_collector.run_room,args=(FakeEngine(),'canada28',stop))
            worker.start();worker.join(3)
            stop.set();worker.join(1)
        self.assertEqual(len(calls),2)

    def test_request_no_cache_and_size_guard(self):
        cfg={'url':'https://example.invalid','headers':{}}
        opener=unittest.mock.Mock()
        response=io.BytesIO(b'{"ok":true}')
        opener.open.return_value=response
        with patch('urllib.request.build_opener',return_value=opener): self.assertEqual(draw_collector.fetch_json(cfg),{'ok':True})
        request=opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Cache-control'),'no-cache')
        self.assertEqual(opener.open.call_args.kwargs['timeout'],6)
        opener.open.return_value=io.BytesIO(b'x'*(1024*1024+1))
        with patch('urllib.request.build_opener',return_value=opener):
            with self.assertRaisesRegex(ValueError,'1MB'):draw_collector.fetch_json(cfg)


if __name__ == '__main__': unittest.main()
