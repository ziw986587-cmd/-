import copy
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'room-engine'))
from engine import Engine
import australia8_feed as feed
import draw_collector

URL='https://api.byw.bet/api?token=fixture-secret&t=114&p=json&limit=20&nexttime=1'


def row(number, when='2026-10-05 17:33:40', code='4,10,6,9,15,18,16,20'):
    return dict(Expect=str(number), Opencode=code, Opentime=when)


def payload(rows, nxt='2026-10-05 17:38:40'):
    return dict(Rows=len(rows), Data=rows, Nexttime=nxt)


class BywFeedTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.e=Engine(directory.name)
        self.e.configure('australia8',dict(mode='external',period=300,
            feed=dict(format='byw-a8',url=URL,interval=10)))
        self.cfg=self.e.game('australia8')['feed']
        self.now=feed.timestamp('2026-10-05 17:34:00')

    def apply(self,obj):
        with patch('engine.time.time',return_value=self.now):
            return self.e.external_result('australia8',obj,self.cfg)

    def test_upper_lower_case_and_beijing_clock_preserve_number_order(self):
        obj=payload([row(31398436)])
        expected=feed.latest(obj)
        lower={k.lower():([{x.lower():v for x,v in r.items()} for r in value] if k=='Data' else value) for k,value in obj.items()}
        self.assertEqual(expected,feed.latest(lower))
        self.assertEqual(expected['nextTime'],1791193120)
        self.apply(obj)
        g=self.e.game('australia8')
        self.assertEqual(g['issue'],'31398437')
        self.assertEqual(g['history'][0]['numbers'],[4,10,6,9,15,18,16,20])
        self.assertEqual(g['endAt'],self.now+280)

    def test_unsorted_reconnect_history_pays_once_and_fills_no_bet_periods(self):
        self.apply(payload([row(100)]))
        with patch('engine.time.time',return_value=self.now):self.e.submit('localdemo','australia8','大10',8)
        self.now+=900
        obj=payload([row(103,'2026-10-05 17:48:40'),row(101,'2026-10-05 17:38:40'),row(102,'2026-10-05 17:43:40')],'2026-10-05 17:53:40')
        with patch('draw_collector.fetch_json',return_value=obj),patch('engine.time.time',return_value=self.now),patch('sys.stderr',new_callable=io.StringIO):
            draw_collector.sample(self.e,'australia8',self.cfg)
        g=self.e.game('australia8')
        self.assertEqual([r['issue'] for r in g['history']],['103','102','101','100'])
        self.assertEqual(self.e.s['orders'][-1]['status'],'中奖')
        before=copy.deepcopy(self.e.s);self.apply(obj);self.assertEqual(before,self.e.s)

    def test_missing_history_keeps_pending_and_balance(self):
        self.apply(payload([row(100)]))
        with patch('engine.time.time',return_value=self.now):self.e.submit('localdemo','australia8','大10',8)
        before=copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(ValueError,'缺期'):self.apply(payload([row(102)]))
        self.assertEqual(self.e.s,before)

    def test_latest_list_is_used_before_requesting_history(self):
        self.apply(payload([row(100)]))
        obj=payload([row(102),row(101)])
        with patch('draw_collector.fetch_json',return_value=obj) as fetch:
            result=feed.fetch_payload(self.e,'australia8',self.cfg,fetch)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(len(result['history']),2)

    def test_history_date_request_keeps_114_and_token(self):
        self.apply(payload([row(100)]))
        latest=payload([row(103,'2026-10-05 00:08:40')],'2026-10-05 00:13:40')
        with patch('draw_collector.fetch_json',side_effect=[latest,payload([row(101)]),payload([row(102)])]) as fetch:
            feed.fetch_payload(self.e,'australia8',self.cfg,fetch)
        queries=[parse_qs(urlsplit(call.args[0]['url']).query) for call in fetch.call_args_list[1:]]
        self.assertEqual([q['date'][0] for q in queries],['20261004','20261005'])
        self.assertTrue(all(q['t']==['114'] and q['token']==['fixture-secret'] for q in queries))

    def test_duplicate_conflict_bad_numbers_and_stale_results_rejected(self):
        self.apply(payload([row(100)]));before=copy.deepcopy(self.e.s)
        bad=[payload([row(99)]),payload([row(100,code='1,2,3,4,5,6,7,8')]),payload([row(101,code='1,1,2,3,4,5,6,7')]),payload([row(101,code='0,2,3,4,5,6,7,8')])]
        for obj in bad:
            with self.assertRaises(ValueError):self.apply(obj)
            self.assertEqual(before,self.e.s)

    def test_no_guessed_date_period_rollover(self):
        with self.assertRaisesRegex(ValueError,'日期式期号'):feed.latest(payload([row(20261005288)]))

    def test_api_auth_and_quota_errors_never_echo_secret(self):
        for code in ('1001','1002','1004','3004'):
            with self.assertRaises(feed.FeedAccessError) as caught:feed.latest({'error':True,'code':code,'message':URL})
            self.assertNotIn('fixture-secret',str(caught.exception))
        with self.assertRaises(feed.FeedRateLimit):feed.latest({'error':True,'code':'3003'})
        self.assertEqual(draw_collector.retry_delay(feed.FeedRateLimit(),3,10),60)

    def test_url_validation_wrong_lottery_or_missing_token(self):
        for url in (URL.replace('t=114','t=116'), URL.replace('token=fixture-secret','token='), URL.replace('https:','http:'),URL+'&date=20261005',URL.replace('/api?', '/test?')):
            with self.assertRaises(ValueError):feed.validate_url(url)

    def test_trial_data_rejected_even_if_random_ball_is_in_range(self):
        obj=payload([row(31398448)])
        obj['message']='试用接口首位号码随机变化,仅供对接测试使用'
        before=copy.deepcopy(self.e.s)
        with self.assertRaisesRegex(feed.FeedAccessError,'试用随机号码'):self.apply(obj)
        self.assertEqual(before,self.e.s)

    def test_response_wrong_lottery_is_rejected(self):
        obj=payload([row(31398448)]);obj['type']='116'
        with self.assertRaisesRegex(ValueError,'不是114'):self.apply(obj)

    def test_restart_uses_persisted_history_and_failed_save_rolls_back(self):
        self.apply(payload([row(100)]));self.e=Engine(self.e.path.parent);self.cfg=self.e.game('australia8')['feed']
        before=copy.deepcopy(self.e.s)
        self.apply(payload([row(100)]));self.assertEqual(before,self.e.s)
        with patch.object(self.e,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.apply(payload([row(101)]))
        self.assertEqual(before,self.e.s)

    def test_future_timestamp_rejected_and_late_result_stays_closed(self):
        with self.assertRaisesRegex(ValueError,'未来'):self.apply(payload([row(100,'2026-10-05 18:33:40')],'2026-10-05 18:38:40'))
        self.now+=600;self.apply(payload([row(100)]));self.assertTrue(self.e.game('australia8')['closed'])

    def test_cannot_switch_local_pending_bets_to_real_draw(self):
        self.e.configure('australia8',dict(mode='simulation'))
        self.e.submit('localdemo','australia8','大10',8)
        with self.assertRaisesRegex(ValueError,'先结算或退还'):
            self.e.configure('australia8',dict(mode='external'))


if __name__=='__main__':unittest.main()
