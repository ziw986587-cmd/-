"""Shared wallet migration and multi-room scheduling, using isolated fixtures."""
import copy
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES, Handler
import simulated_users
from unified import mutate_member


class SharedWalletTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='shared-wallet-test-')
        self.addCleanup(self.directory.cleanup)
        self.now = 1800000000.0
        self.clock = patch('engine.time.time', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.engine = Engine(self.directory.name)
        for game in GAMES:
            self.engine.configure(game, dict(mode='manual', period=3600,
                minBet='0.01', maxBet='1000', closeSeconds=10))
        self.user.update(robot=True, enabled=True, accessVersion='old-test-version')
        self.engine.credit('localdemo', 'canada28', 10000 - self.user['balance'],
                           'test opening adjustment', 'opening')
        simulated_users.initialize(self.engine)

    @property
    def user(self):
        return self.engine.s['users']['localdemo']

    def batch(self, **values):
        data = dict(username='localdemo', rooms=list(GAMES), enabled=True,
                    amountMin='2', amountMax='2', selections=['1番'],
                    intervalSeconds=5, betsPerRound=1, ball=2)
        data.update(values)
        return simulated_users.configure_batch(self.engine, data)

    def tick(self, seconds=5):
        self.now += seconds
        self.engine.tick()

    def assert_balance(self, expected):
        self.assertEqual(self.user['balance'], expected)
        self.assertEqual(self.user['wallets'], {game: expected for game in GAMES})
        for game in GAMES:
            public = self.engine.public('localdemo', game)
            self.assertEqual(public['score'], expected)
            self.assertEqual(public['balance'], expected)
        ledger = [row for row in self.engine.s['ledger'] if row['username'] == 'localdemo']
        self.assertEqual(sum(row['delta'] for row in ledger), expected)

    def legacy_fixture(self, wallets=None, missing_ledger_amount=0):
        """An existing pre-shared installation with a paid, unsettled order."""
        wallets = wallets or dict(canada28=1000, australia8=3400, australia8ball=5600)
        self.user.pop('balance', None)
        self.user.pop('walletVersion', None)
        self.user.pop('walletMigration', None)
        self.user['wallets'] = copy.deepcopy(wallets)
        self.engine.s.pop('sharedWalletVersion', None)
        rows = []
        for game, amount in wallets.items():
            rows.append(dict(id='old-opening-' + game, username='localdemo', game=game,
                delta=amount + (200 if game == 'canada28' else 0),
                balance=amount + (200 if game == 'canada28' else 0),
                reason='old opening', ref='old', time='2026-09-29 12:00:00',
                historicalMetadata={'unchanged': True}))
        rows.append(dict(id='old-debit', username='localdemo', game='canada28',
            delta=-200, balance=wallets['canada28'], reason='提交注单', ref='old-batch',
            time='2026-09-29 12:00:01'))
        rows[0]['delta'] -= missing_ledger_amount
        self.engine.s['ledger'] = rows
        self.engine.s['orders'] = [dict(id='old-order', batch='old-batch',
            username='localdemo', game='canada28', issue=self.engine.game('canada28')['issue'],
            selection='1番', amount=200, ball=8, status='待开奖', rate=2.91,
            profit=None, payout=None, time='2026-09-29 12:00:01', report='未上报')]
        self.engine.save()
        self.engine = Engine(self.directory.name)
        return wallets, copy.deepcopy(rows)

    def test_old_wallets_sum_once_and_original_ledger_survives_restart(self):
        wallets, old_rows = self.legacy_fixture()
        self.assert_balance(10000)
        self.assertEqual(self.user['walletMigration']['originalWallets'], wallets)
        self.assertEqual(self.engine.s['sharedWalletVersion'], 1)
        self.assertEqual(self.user['walletVersion'], 1)
        for old in old_rows:
            self.assertEqual(next(row for row in self.engine.s['ledger'] if row['id'] == old['id']), old)
        ledger = copy.deepcopy(self.engine.s['ledger'])
        for _ in range(3):
            self.engine.save()
            self.engine = Engine(self.directory.name)
            self.assert_balance(10000)
            self.assertEqual(self.engine.s['ledger'], ledger)

    def test_equal_legacy_wallets_are_summed_but_shared_mirrors_are_not(self):
        self.legacy_fixture({game: 1000 for game in GAMES})
        self.assert_balance(3000)
        self.engine.save()
        self.engine = Engine(self.directory.name)
        self.assert_balance(3000)

    def test_first_migration_balances_missing_old_ledger_without_rewriting_history(self):
        _, old_rows = self.legacy_fixture(missing_ledger_amount=17)
        self.assert_balance(10000)
        old_ids = {row['id'] for row in old_rows}
        extra = [row for row in self.engine.s['ledger']
                 if row['username'] == 'localdemo' and row['id'] not in old_ids]
        self.assertEqual(sum(row['delta'] for row in extra), 17)
        for row in old_rows:
            self.assertEqual(next(current for current in self.engine.s['ledger']
                                  if current['id'] == row['id']), row)

    def test_already_shared_corrupt_ledger_is_rejected_without_rewriting_file(self):
        self.user['balance'] += 1
        self.user['wallets'] = {game: self.user['balance'] for game in GAMES}
        self.engine.save()
        original = self.engine.path.read_bytes()
        with self.assertRaises(ValueError):
            Engine(self.directory.name)
        self.assertEqual(self.engine.path.read_bytes(), original)

    def test_migration_keeps_pending_order_and_settles_once_into_shared_funds(self):
        self.legacy_fixture()
        order = self.engine.s['orders'][0]
        self.assertEqual(order['status'], '待开奖')
        self.assertTrue(self.engine.settle('canada28', order['issue'], [0, 0, 1], 'manual'))
        self.assertEqual(order['payout'], 782)
        self.assert_balance(10782)
        credit = next(row for row in self.engine.s['ledger'] if row['ref'] == 'old-order')
        self.assertEqual(credit['walletScope'], 'shared')
        self.assertEqual(credit['balance'], 10782)
        self.assertFalse(self.engine.settle('canada28', order['issue'], [0, 0, 1], 'manual'))
        self.assert_balance(10782)

    def test_shared_transfer_is_rejected_without_ledger_changes(self):
        before = copy.deepcopy(self.engine.s)
        with self.assertRaises(ValueError):
            Handler.mutate(SimpleNamespace(engine=self.engine), '/api/transfer',
                'localdemo', 'canada28', dict(target='australia8', amount='10'))
        self.assertEqual(self.engine.s, before)

    def test_concurrent_direct_bets_cannot_spend_one_balance_three_times(self):
        self.engine.credit('localdemo', 'canada28', -9000, 'test limit', 'limit')
        barrier = threading.Barrier(3)

        def place(game):
            barrier.wait(timeout=5)
            try:
                self.engine.submit('localdemo', game, '1番7', 1)
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=3) as pool:
            result = list(pool.map(place, GAMES))
        self.assertEqual(result.count(True), 1)
        self.assertEqual(len(self.engine.s['orders']), 1)
        self.assert_balance(300)

    def test_three_due_timers_share_funds_and_never_overspend(self):
        self.engine.credit('localdemo', 'canada28', -9000, 'test limit', 'limit')
        self.batch(amountMin='7', amountMax='7')
        self.tick()
        self.assertEqual(len(self.engine.s['orders']), 1)
        self.assertEqual(sum(status['count'] for status in self.user['autoBetStatus'].values()), 1)
        self.assert_balance(300)
        self.tick(20)
        self.assertEqual(len(self.engine.s['orders']), 1)
        self.assert_balance(300)

    def test_batch_three_rooms_and_unselected_rooms_stop(self):
        self.batch(betsPerRound=3)
        self.tick()
        self.assertEqual({order['game'] for order in self.engine.s['orders']}, set(GAMES))
        self.assert_balance(9400)
        self.batch(rooms=['australia8ball'], betsPerRound=3)
        self.tick()
        self.assertEqual(len(self.engine.s['orders']), 4)
        self.assertEqual(self.engine.s['orders'][-1]['game'], 'australia8ball')
        self.assertFalse(self.user['autoBet']['canada28']['enabled'])
        self.assertFalse(self.user['autoBet']['australia8']['enabled'])
        self.assertTrue(self.user['autoBet']['australia8ball']['enabled'])
        self.assert_balance(9200)
        simulated_users.configure_batch(self.engine, dict(username='localdemo', rooms=[], enabled=False))
        self.tick(20)
        self.assertEqual(len(self.engine.s['orders']), 4)
        self.assertFalse(self.user['auto'])

    def test_batch_requires_explicit_activation_and_rotates_disabled_link(self):
        self.user.update(enabled=False, robot=False)
        before = copy.deepcopy(self.engine.s)
        with self.assertRaises(ValueError):
            self.batch()
        self.assertEqual(self.engine.s, before)
        self.batch(activateMember=True)
        self.assertTrue(self.user['enabled'])
        self.assertTrue(self.user['robot'])
        self.assertNotEqual(self.user['accessVersion'], 'old-test-version')
        version = self.user['accessVersion']
        self.batch(activateMember=True)
        self.assertEqual(self.user['accessVersion'], version,
                         'already enabled identity must not revoke its link on each save')
        self.tick()
        self.assertEqual(len(self.engine.s['orders']), 3)

    def test_batch_ordinary_enabled_member_requires_explicit_robot_activation(self):
        self.user['robot'] = False
        with self.assertRaises(ValueError):
            self.batch()
        self.batch(activateMember=True)
        self.assertTrue(self.user['robot'])
        self.assertTrue(self.user['enabled'])
        self.assertEqual(self.user['accessVersion'], 'old-test-version')

    def test_batch_invalid_room_or_room_limit_is_atomic_including_activation(self):
        self.user.update(robot=False, enabled=False)
        self.engine.configure('australia8ball', dict(minBet='5'))
        invalid = [dict(), dict(rooms=['canada28', 'unknown']), dict(rooms=[]),
                   dict(rooms='canada28'), dict(rooms=['canada28', 'canada28']),
                   dict(activateMember='true'), dict(amountMin='0')]
        for values in invalid:
            with self.subTest(values=values):
                before = copy.deepcopy(self.engine.s)
                with self.assertRaises(ValueError):
                    self.batch(**dict(dict(activateMember=True), **values))
                self.assertEqual(self.engine.s, before)

    def test_batch_resaves_toggles_and_restart_preserve_each_room_quota(self):
        self.batch()
        self.tick()
        for _ in range(2):
            self.batch()
            self.tick(10)
            self.assertEqual(len(self.engine.s['orders']), 3)
        simulated_users.configure_batch(self.engine, dict(username='localdemo', rooms=[], enabled=False))
        self.batch()
        self.engine.save()
        self.engine = Engine(self.directory.name)
        simulated_users.initialize(self.engine)
        self.tick(10)
        self.assertEqual(len(self.engine.s['orders']), 3)
        self.assertEqual([self.user['autoBetStatus'][game]['count'] for game in GAMES], [1, 1, 1])
        self.assert_balance(9400)

    def test_refund_and_approved_score_request_update_every_room(self):
        self.engine.submit('localdemo', 'australia8', '1番7')
        self.assert_balance(9300)
        Handler.mutate(SimpleNamespace(engine=self.engine), '/api/admin/refund',
                       'localadmin', 'australia8', {})
        self.assert_balance(10000)
        self.engine.request_score('localdemo', 'australia8ball', '上分', '1.23')
        request = self.engine.s['requests'][-1]
        Handler.mutate(SimpleNamespace(engine=self.engine), '/api/admin/review',
                       'localadmin', 'canada28', dict(id=request['id'], approve=True))
        self.assert_balance(10123)
        with self.assertRaises(ValueError):
            Handler.mutate(SimpleNamespace(engine=self.engine), '/api/admin/review',
                           'localadmin', 'canada28', dict(id=request['id'], approve=True))
        self.assert_balance(10123)


if __name__ == '__main__':
    unittest.main()
