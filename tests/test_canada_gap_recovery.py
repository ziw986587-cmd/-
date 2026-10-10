import copy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'room-engine'))
from engine import Engine
import history_feed

class CanadaGapTests(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);self.e=Engine(d.name);self.now=1800000000
        self.e.configure('canada28',dict(mode='external',period=210,feed=dict(format='pc28-history',interval=2,url='https://example.invalid/history')))
        self.cfg=self.e.game('canada28')['feed']
    def row(self,n,code='8,0,9'):
        return dict(expect=str(n),lottery_id=2,opencode=code,opentime=self.now-30,createtime=self.now-10)
    def apply(self,rows):
        with patch('engine.time.time',return_value=self.now):return self.e.external_result('canada28',{'data':rows},self.cfg)
    def bet(self):
        with patch('engine.time.time',return_value=self.now):self.e.submit('localdemo','canada28','1番100')
    def test_old_pending_preserved_current_result_not_used_for_old_bet(self):
        self.apply([self.row(100)]);self.bet();balance=self.e.s['users']['localdemo']['balance']
        self.apply([self.row(103,'1,1,1')]);g=self.e.game('canada28')
        self.assertEqual(g['issue'],'104');self.assertFalse(g['closed'])
        self.assertEqual(g['feedGaps'],[[101,102]])
        self.assertEqual(self.e.s['orders'][0]['status'],'待开奖');self.assertEqual(self.e.s['users']['localdemo']['balance'],balance)
        self.bet();active={k:g[k] for k in ('issue','endAt','closed','warned')}
        self.apply([self.row(101),self.row(103,'1,1,1')])
        self.assertEqual(self.e.s['orders'][0]['status'],'中奖');self.assertEqual(self.e.s['orders'][1]['status'],'待开奖')
        self.assertEqual({k:g[k] for k in active},active);self.assertEqual(g['history'][0]['issue'],'103')
        after=copy.deepcopy(self.e.s);self.apply([self.row(101),self.row(103,'1,1,1')]);self.assertEqual(after,self.e.s)
    def test_gap_persists_restart_late_single_issue_import_and_next_draw(self):
        self.apply([self.row(100)]);self.bet();self.apply([self.row(103)])
        self.e=Engine(self.e.path.parent);self.apply([self.row(101)])
        self.assertEqual(self.e.game('canada28')['issue'],'104');self.assertEqual(self.e.game('canada28')['feedGaps'],[[102,102]])
        self.assertEqual(self.e.s['orders'][0]['status'],'中奖');self.apply([self.row(102),self.row(104)])
        self.assertEqual(self.e.game('canada28')['issue'],'105');self.assertNotIn('feedGaps',self.e.game('canada28'))
    def test_range_representation_handles_large_jump_without_fabricated_draws(self):
        self.apply([self.row(100)]);self.apply([self.row(10**12)])
        self.assertEqual(self.e.game('canada28')['feedGaps'],[[101,10**12-1]])
        self.assertEqual(len(self.e.game('canada28')['history']),2)
    def test_unchanged_poll_does_not_copy_or_save_full_state(self):
        self.apply([self.row(100)]);self.apply([self.row(103)]);original=copy.deepcopy
        def guarded(obj,*a,**kw):
            if obj is self.e.s:raise AssertionError('Full snapshot on unchanged poll')
            return original(obj,*a,**kw)
        with patch('history_feed.copy.deepcopy',side_effect=guarded),patch.object(self.e,'save',side_effect=AssertionError('Unchanged write')):self.apply([self.row(103)])
    def test_failed_gap_recovery_rolls_back_and_retry_pays_once(self):
        self.apply([self.row(100)]);self.bet();self.apply([self.row(103)]);before=copy.deepcopy(self.e.s)
        with patch.object(self.e,'save',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.apply([self.row(101),self.row(104)])
        self.assertEqual(before,self.e.s);self.apply([self.row(101),self.row(104)]);after=copy.deepcopy(self.e.s)
        self.apply([self.row(101),self.row(104)]);self.assertEqual(after,self.e.s)
    def test_other_rooms_unchanged_on_gap_recovery(self):
        self.apply([self.row(100)]);before=copy.deepcopy(self.e.s);self.apply([self.row(103)])
        for k in ('australia8','australia8ball'):self.assertEqual(before['games'][k],self.e.s['games'][k])
        for k in ('users','orders','ledger','requests'):self.assertEqual(before[k],self.e.s[k])
    def test_current_cancel_cannot_refund_unresolved_old_order(self):
        self.apply([self.row(100)]);self.bet();old=self.e.s['orders'][0]
        self.apply([self.row(103)]);self.bet()
        with patch('engine.time.time',return_value=self.now):
            with self.assertRaisesRegex(ValueError,'没有可退'):self.e.cancel('localdemo','canada28',old['id'])
            self.e.cancel('localdemo','canada28')
        self.assertEqual(old['status'],'待开奖');self.assertEqual(self.e.s['orders'][1]['status'],'已退单')
    def test_current_close_report_excludes_old_pending(self):
        self.apply([self.row(100)]);self.bet();self.apply([self.row(103)]);self.bet()
        self.e.close_round('canada28')
        msg=self.e.game('canada28')['chat'][-1]
        self.assertEqual(msg['kind'],'HEDUI');self.assertEqual(msg['details']['issue'],'104')
        self.assertEqual(len(msg['details']['closeOrders']),1)

if __name__=='__main__':unittest.main()
