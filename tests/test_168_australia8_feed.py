import copy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'room-engine'))
from engine import Engine
import lottery168_feed as feed
import draw_collector

def raw(n, when='2026-10-05 17:33:40', code='4,10,6,9,15,18,16,20'):
 return dict(preDrawIssue=n,preDrawTime=when,preDrawCode=code)
def response(data):return dict(errorCode=0,result=dict(businessCode=0,data=data))
def latest(n=100,when='2026-10-05 17:33:40',nxt='2026-10-05 17:38:40'):
 return response(dict(lotCode=10006,**raw(n,when),drawIssue=n+1,drawTime=nxt))

class FeedTests(unittest.TestCase):
 def setUp(self):
  d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);self.e=Engine(d.name)
  self.e.configure('australia8',dict(mode='external',period=300,feed=dict(format='168-a8',url=feed.URL,interval=2)))
  self.cfg=self.e.game('australia8')['feed'];self.now=feed.timestamp('2026-10-05 17:34:00')
 def apply(self,obj):
  with patch('engine.time.time',return_value=self.now):return self.e.external_result('australia8',obj,self.cfg)
 def test_mapping_timezone_order_and_next_issue(self):
  self.apply(latest());g=self.e.game('australia8')
  self.assertEqual(g['issue'],'101');self.assertEqual(g['history'][0]['issue'],'100')
  self.assertEqual(g['history'][0]['numbers'],[4,10,6,9,15,18,16,20])
  self.assertEqual(g['endAt'],self.now+280)
  self.assertEqual(feed.timestamp('2026-10-05 17:33:40'),1791192820)
 def test_unchanged_poll_does_not_copy_business_state(self):
  self.apply(latest());before=copy.deepcopy(self.e.s);original=copy.deepcopy
  def guarded(value,*args,**kw):
   if value is self.e.s:raise AssertionError('Unchanged poll copied all records')
   return original(value,*args,**kw)
  with patch('lottery168_feed.copy.deepcopy',side_effect=guarded):self.apply(latest())
  self.assertEqual(before,self.e.s)
 def test_wrong_lottery_invalid_balls_duplicate_future_and_api_errors(self):
  bads=[]
  for change in ({'lotCode':10010},{'preDrawCode':'1,2,3,4,5,6,7,7'},{'preDrawCode':'0,2,3,4,5,6,7,8'},{'drawIssue':105},{'preDrawTime':'2026-10-06 17:33:40'}):
   obj=latest();obj['result']['data'].update(change);bads.append(obj)
  bads.append(dict(errorCode=1))
  for obj in bads:
   with self.subTest(obj=obj),self.assertRaises(ValueError):self.apply(obj)
  self.assertEqual(self.e.game('australia8')['history'],[])
 def test_gap_backfill_with_bets_exactly_once_and_ball_position(self):
  self.apply(latest())
  with patch('engine.time.time',return_value=self.now):self.e.submit('localdemo','australia8','大10',8)
  self.now+=600
  obj=dict(latest=latest(102,'2026-10-05 17:43:40','2026-10-05 17:48:40'),history=[raw(101,'2026-10-05 17:38:40'),raw(102,'2026-10-05 17:43:40')])
  self.apply(obj);self.assertEqual(self.e.s['orders'][-1]['status'],'中奖')
  before=copy.deepcopy(self.e.s);self.apply(obj);self.assertEqual(self.e.s,before)
  self.assertEqual([h['issue'] for h in self.e.game('australia8')['history']],['102','101','100'])
 def test_gap_without_bets_and_missing_record_preserves_state(self):
  self.apply(latest());self.now+=600;before=copy.deepcopy(self.e.s)
  with self.assertRaisesRegex(ValueError,'缺期'):self.apply(latest(102,'2026-10-05 17:43:40','2026-10-05 17:48:40'))
  self.assertEqual(self.e.s,before)
 def test_history_conflict_is_atomic(self):
  self.apply(latest());before=copy.deepcopy(self.e.s)
  with self.assertRaisesRegex(ValueError,'修改已记录'):
   self.apply(dict(latest=latest(101),history=[raw(100,code='1,2,3,4,5,6,7,8')]))
  self.assertEqual(before,self.e.s)
 def test_restart_regression_duplicate_and_persistence(self):
  self.apply(latest());self.e=Engine(self.e.path.parent);before=copy.deepcopy(self.e.s)
  self.apply(latest());self.assertEqual(before,self.e.s)
  with self.assertRaisesRegex(ValueError,'倒退'):self.apply(latest(99))
 def test_failed_save_rolls_back(self):
  before=copy.deepcopy(self.e.s)
  with patch.object(self.e,'save',side_effect=OSError('disk')):
   with self.assertRaises(OSError):self.apply(latest())
  self.assertEqual(self.e.s,before)
 def test_expired_result_remains_closed(self):
  self.now+=500;self.apply(latest());self.assertTrue(self.e.game('australia8')['closed'])
 def test_cross_day_backfill_fetches_both_dates(self):
  self.e.game('australia8')['issue']='100'
  calls=[]
  def fetch(cfg):
   calls.append(cfg['url'])
   return latest(102,'2026-10-06 00:03:40','2026-10-06 00:08:40') if len(calls)==1 else response([])
  feed.fetch_payload(self.e,'australia8',self.cfg,fetch)
  self.assertEqual(len(calls),3)
  self.assertIn('date=2026-10-05',calls[1]);self.assertIn('date=2026-10-06',calls[2])
 def test_correct_latest_needs_no_history_request(self):
  with patch('draw_collector.fetch_json',return_value=latest()) as fetch:
   feed.fetch_payload(self.e,'australia8',self.cfg,fetch);self.assertEqual(fetch.call_count,1)
 def test_config_rejects_wrong_room_and_pending_switch(self):
  with self.assertRaises(ValueError):self.e.configure('canada28',dict(mode='external',period=300,feed=dict(format='168-a8',url=feed.URL)))
  self.apply(latest())
  with patch('engine.time.time',return_value=self.now):self.e.submit('localdemo','australia8','大10',8)
  with self.assertRaises(ValueError):self.e.configure('australia8',dict(mode='simulation'))
 def test_local_pending_cannot_use_website_numbers(self):
  g=self.e.game('australia8');g.update(mode='simulation',closed=False,endAt=self.now+300)
  with patch('engine.time.time',return_value=self.now):self.e.submit('localdemo','australia8','大10',8)
  g['mode']='external';before=copy.deepcopy(self.e.s)
  with self.assertRaisesRegex(ValueError,'本地期号'):self.apply(latest())
  self.assertEqual(before,self.e.s)
 def test_scheduled_cutover_settles_old_round_before_activating(self):
  g=self.e.game('australia8');g.update(mode='simulation',closed=False,endAt=self.now+20)
  with patch('engine.time.time',return_value=self.now):self.e.submit('localdemo','australia8','大10',8)
  old_issue=g['issue'];g['pending168Feed']=copy.deepcopy(self.cfg);g['closed']=True
  with patch('engine.time.time',return_value=self.now):self.e.tick()
  self.assertEqual(g['mode'],'simulation')
  with patch('engine.time.time',return_value=self.now+25):self.e.tick()
  self.assertEqual(g['mode'],'external');self.assertTrue(g['closed']);self.assertNotIn('pending168Feed',g)
  self.assertEqual(self.e.s['orders'][0]['issue'],old_issue);self.assertNotEqual(self.e.s['orders'][0]['status'],'待开奖')
  self.apply(latest());self.assertEqual(g['issue'],'101');self.assertEqual(len(self.e.s['orders']),1)
 def test_url_cannot_select_other_lottery_or_fixed_history(self):
  for url in (feed.URL.replace('10006','10010'),feed.URL+'&date=2026-10-05',feed.URL.replace('issue=','issue=1'),feed.URL.replace('168kj168.com','example.com')):
   with self.subTest(url=url),self.assertRaises(ValueError):feed.validate_url(url)

if __name__=='__main__':unittest.main()
