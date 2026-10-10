import copy
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, Handler
from types import SimpleNamespace
import retention
import shared_wallet
import workbench


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.e = Engine(self.temp.name)
        workbench.initialize(self.e)
        self.now = time.time()
        self.cutoff = self.now - 7 * 86400
        self.old = datetime.fromtimestamp(self.cutoff - 60).isoformat()
        self.recent = datetime.fromtimestamp(self.now - 60).isoformat()

    def order(self, name, status, timestamp, **more):
        return dict(id=name, game='canada28', username='localdemo',
                    issue='old', selection='1番', amount=100,
                    status=status, profit=0, time=timestamp, **more)

    def test_boundary_pending_users_settings_and_all_record_types(self):
        orders = [self.order('old', '未中', self.old),
                  self.order('pending', '待开奖', self.old),
                  self.order('legacy', '待手动结算', self.old),
                  self.order('boundary', '中奖', self.cutoff),
                  self.order('recent', '未中', self.recent),
                  self.order('newly-settled', '中奖', self.old, completedAt=self.now)]
        self.e.s['orders'] = orders
        for prefs in self.e.s['workbench'].values():
            prefs['statFrom'] = 4
        self.e.s['requests'] = [dict(id='old', status='已通过', time=self.old),
                               dict(id='pending', status='待审核', time=self.old),
                               dict(id='reviewed', status='已通过', time=self.old, reviewedAt=self.now)]
        self.e.s['adminLog'] = [dict(time=self.old), dict(time=self.recent)]
        self.e.s['rebateBatches'] = [dict(time=self.old), dict(time=self.recent)]
        for g in self.e.s['games'].values():
            g['chat'] = [dict(time=self.old), dict(time=self.recent)]
            g['history'] = [dict(time=self.old), dict(time=self.recent)]
        users = copy.deepcopy(self.e.s['users'])
        configs = {key: {k:v for k,v in g.items() if k not in ('chat','history')}
                   for key,g in copy.deepcopy(self.e.s['games']).items()}
        retention.prune(self.e, now=self.now, force=True)
        self.assertEqual([o['id'] for o in self.e.s['orders']],
                         ['pending', 'legacy', 'boundary', 'recent', 'newly-settled'])
        self.assertEqual([r['id'] for r in self.e.s['requests']], ['pending', 'reviewed'])
        self.assertEqual(self.e.s['users'], users)
        for key, g in self.e.s['games'].items():
            self.assertEqual({k:v for k,v in g.items() if k not in ('chat','history')}, configs[key])
            self.assertEqual(len(g['chat']), 1)
            self.assertEqual(len(g['history']), 1)
            self.assertEqual(self.e.s['workbench'][key]['statFrom'], 3)
        for field in ('adminLog', 'rebateBatches'):
            self.assertEqual(len(self.e.s[field]), 1)

    def test_ledger_checkpoint_repeated_cleanup_restart_and_next_credit(self):
        for row in self.e.s['ledger']:
            row['time'] = self.old
        self.e.credit('localdemo', 'canada28', 5000, 'recent', 'recent')
        before = copy.deepcopy(self.e.s['users'])
        retention.prune(self.e, self.now, force=True)
        self.assertEqual(self.e.s['users'], before)
        self.assertEqual(len(self.e.s['ledger']), 1)
        checkpoint = copy.deepcopy(self.e.s['ledgerOpening'])
        self.assertFalse(retention.prune(self.e, self.now, force=True))
        self.assertEqual(self.e.s['ledgerOpening'], checkpoint)
        self.e = Engine(self.temp.name)
        self.assertEqual(self.e.s['users'], before)
        self.e.credit('localdemo', 'canada28', 100, 'after restart', 'next')
        self.e.save_light()
        self.e.save()
        reloaded = Engine(self.temp.name)
        self.assertEqual(reloaded.s['users']['localdemo']['balance'], before['localdemo']['balance'] + 100)
        for row in self.e.s['ledger']:
            row['time'] = self.old
        retention.prune(self.e, self.now, force=True)
        self.assertEqual(self.e.s['ledger'], [])
        self.assertEqual(self.e.s['ledgerOpening']['localdemo'], before['localdemo']['balance'] + 100)
        shared_wallet.initialize(self.e)

    def test_recent_completion_protects_overdue_pending_order_and_request(self):
        self.e.configure('canada28', dict(mode='manual', period=120))
        self.e.submit('localdemo', 'canada28', '1番10')
        self.e.request_score('localdemo', 'canada28', '上分', '1')
        for row in self.e.s['orders'] + self.e.s['requests']:
            row['time'] = self.old
        retention.prune(self.e, self.now, force=True)
        self.e.settle('canada28', self.e.game('canada28')['issue'], [0,0,1], 'manual')
        Handler.mutate(SimpleNamespace(engine=self.e), '/api/admin/review', 'localadmin',
                       'canada28', dict(id=self.e.s['requests'][0]['id'], approve=True))
        retention.prune(self.e, self.now, force=True)
        self.assertEqual(len(self.e.s['orders']), 1)
        self.assertEqual(len(self.e.s['requests']), 1)

    def test_legacy_timezone_and_unknown_dates(self):
        boundary = datetime.fromtimestamp(self.cutoff, timezone(timedelta(hours=8)))
        row = dict(time=boundary.strftime('%Y-%m-%d %H:%M:%S'), legacy=True)
        self.assertAlmostEqual(retention.record_time(row), self.cutoff, delta=1)
        self.e.s['adminLog'] = [dict(time='invalid')]
        retention.prune(self.e, self.now, force=True)
        self.assertEqual(self.e.s['adminLog'], [dict(time='invalid')])

    def test_failed_save_rolls_back_and_dedup_expiry(self):
        self.e.s['orders'] = [self.order('old', '未中', self.old)]
        self.e.s['unifiedDedup'] = dict(old=dict(time=self.old),
                                      recent=dict(time=self.recent),
                                      undated=dict(result=dict(message='ok')))
        before = copy.deepcopy(self.e.s)
        with patch.object(self.e, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                retention.prune(self.e, self.now, force=True)
        self.assertEqual(self.e.s, before)
        retention.prune(self.e, self.now, force=True)
        self.assertEqual(set(self.e.s['unifiedDedup']), {'recent', 'undated'})
        self.assertEqual(self.e.s['unifiedDedup']['undated']['time'], self.now)


if __name__ == '__main__':
    unittest.main()
