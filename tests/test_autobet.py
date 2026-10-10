"""Deterministic scheduler tests; all balances and files live in temporary data."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine
import simulated_users
from unified import mutate_member


class SimulatedAutoBetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='local-autobet-test-')
        self.addCleanup(self.directory.cleanup)
        self.now = 1800000000.0
        self.clock = patch('engine.time.time', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.engine = Engine(self.directory.name)
        for game in self.engine.s['games']:
            self.engine.configure(game, dict(mode='manual', period=3600,
                closeSeconds=10, minBet='0.01', maxBet='1000', paused=False))
        member = self.engine.s['users']['localdemo']
        member.update(robot=True, auto=False)
        self.engine.credit('localdemo', 'canada28', 100000 - member['balance'],
                           'test opening adjustment', 'opening')
        simulated_users.initialize(self.engine)
        self.engine.save()

    @property
    def member(self):
        return self.engine.s['users']['localdemo']

    def configure(self, game='canada28', **values):
        data = dict(username='localdemo', enabled=True, amountMin='10',
                    amountMax='10', selections=['1番'], intervalSeconds=5,
                    betsPerRound=1, ball=8)
        data.update(values)
        result = simulated_users.configure(self.engine, game, data)
        self.engine.save()
        return result

    def step(self, seconds=5):
        self.now += seconds
        self.engine.tick()

    def orders(self, game=None):
        return [order for order in self.engine.s['orders']
                if order['username'] == 'localdemo' and
                (game is None or order['game'] == game)]

    def restart(self):
        self.engine.save()
        self.engine = Engine(self.directory.name)
        simulated_users.initialize(self.engine)

    def test_legacy_flags_and_robot_identity_alone_do_not_place_orders(self):
        self.member['auto'] = True
        self.step(60)
        self.assertEqual(self.orders(), [])
        self.restart()
        self.step(60)
        self.assertEqual(self.orders(), [])

    def test_first_due_time_and_real_order_accounting(self):
        self.configure()
        stored = self.member['autoBet']['canada28']
        self.assertEqual((stored['amountMin'], stored['amountMax']), (1000, 1000))
        self.step(4)
        self.assertEqual(self.orders(), [])
        self.step(1)
        order, = self.orders()
        self.assertEqual(order['source'], 'simulated-auto')
        self.assertIs(order['simulated'], True)
        self.assertEqual((order['selection'], order['amount'], order['status']),
                         ('1番', 1000, '待开奖'))
        self.assertEqual(self.member['wallets']['canada28'], 99000)
        self.assertTrue(any(message.get('username') == 'localdemo' and
                            message.get('simulated') is True
                            for message in self.engine.game('canada28')['chat']))
        debit = [row for row in self.engine.s['ledger'] if row['ref'] == order['batch']]
        self.assertEqual(len(debit), 1)
        self.assertEqual(debit[0]['delta'], -1000)
        self.assertIs(debit[0]['simulated'], True)
        public = self.engine.public('localdemo', 'canada28')
        self.assertEqual(public['orders'][0]['id'], order['id'])
        self.assertEqual(public['score'], 99000)

    def test_orders_settle_once_using_odds_locked_at_placement(self):
        self.configure()
        self.step()
        order = self.orders()[0]
        rate = order['rate']
        simulated_users.configure(self.engine, 'canada28',
                                  dict(username='localdemo', enabled=False))
        self.engine.game('canada28')['odds']['番'] = 9
        issue = order['issue']
        self.assertTrue(self.engine.settle('canada28', issue, [0, 0, 1], 'manual'))
        expected_payout = 1000 + round(1000 * rate)
        self.assertEqual(order['status'], '中奖')
        self.assertEqual(order['payout'], expected_payout)
        self.assertEqual(self.member['wallets']['canada28'], 99000 + expected_payout)
        self.assertFalse(self.engine.settle('canada28', issue, [0, 0, 1], 'manual'))
        self.assertEqual(self.member['wallets']['canada28'], 99000 + expected_payout)
        ledger = [row for row in self.engine.s['ledger']
                  if row['username'] == 'localdemo']
        self.assertEqual(sum(row['delta'] for row in ledger), self.member['wallets']['canada28'])

    def test_each_interval_places_at_most_one_order_without_catch_up_burst(self):
        self.configure(betsPerRound=3)
        self.step(100)
        self.assertEqual(len(self.orders()), 1)
        self.engine.tick()
        self.assertEqual(len(self.orders()), 1)
        self.step(4)
        self.assertEqual(len(self.orders()), 1)
        self.step(1)
        self.assertEqual(len(self.orders()), 2)
        self.step(5)
        self.assertEqual(len(self.orders()), 3)
        self.step(20)
        self.assertEqual(len(self.orders()), 3)

    def test_closed_paused_and_external_unsynced_rooms_never_place_orders(self):
        for blocked in ('closed', 'paused', 'unsynced'):
            with self.subTest(blocked=blocked):
                self.configure()
                game = self.engine.game('canada28')
                game.update(closed=blocked == 'closed', paused=blocked == 'paused',
                            mode='external' if blocked == 'unsynced' else 'manual',
                            endAt=0 if blocked == 'unsynced' else self.now + 3600)
                self.step(30)
                self.assertEqual(self.orders(), [])

    def test_close_seconds_boundary_is_respected_before_scheduler(self):
        self.configure()
        self.engine.game('canada28')['endAt'] = self.now + 15
        self.step(5)
        self.assertEqual(self.orders(), [])
        self.assertTrue(self.engine.game('canada28')['closed'])

    def test_disabled_config_or_member_cannot_place_orders(self):
        self.configure()
        simulated_users.configure(self.engine, 'canada28',
                                  dict(username='localdemo', enabled=False))
        self.step(10)
        self.assertEqual(self.orders(), [])
        self.configure()
        mutate_member(self.engine, 'member.edit', 'canada28',
                      dict(username='localdemo', enabled=False))
        self.step(10)
        self.assertEqual(self.orders(), [])

    def test_ordinary_and_disabled_users_cannot_enable_automation(self):
        for flags in (dict(robot=False, enabled=True), dict(robot=True, enabled=False)):
            with self.subTest(flags=flags):
                self.member.update(flags)
                before = copy.deepcopy(self.engine.s)
                with self.assertRaises(ValueError):
                    self.configure()
                self.assertEqual(self.engine.s, before)
                self.step(10)
                self.assertEqual(self.orders(), [])

    def test_reenabling_identity_requires_explicit_automation_opt_in(self):
        self.configure(betsPerRound=3)
        self.configure('australia8ball', betsPerRound=3)
        self.step()
        mutate_member(self.engine, 'member.edit', 'canada28',
                      dict(username='localdemo', robot=False))
        mutate_member(self.engine, 'member.edit', 'canada28',
                      dict(username='localdemo', robot=True))
        self.step(20)
        self.assertEqual(len(self.orders()), 2)
        self.assertFalse(self.member['autoBet']['canada28']['enabled'])
        self.assertFalse(self.member['autoBet']['australia8ball']['enabled'])
        self.configure(betsPerRound=3)
        self.step()
        self.assertEqual(len(self.orders('canada28')), 2)
        self.assertEqual(len(self.orders('australia8ball')), 1)

    def test_removing_robot_identity_stops_automation(self):
        self.configure(betsPerRound=3)
        self.step()
        mutate_member(self.engine, 'member.edit', 'canada28',
                      dict(username='localdemo', robot=False))
        self.step(20)
        self.assertEqual(len(self.orders()), 1)

    def test_insufficient_funds_auto_top_up_once_and_continue_betting(self):
        self.engine.credit('localdemo', 'canada28', 999 - self.member['balance'],
                           'test low balance', 'low-balance')
        self.configure()
        with patch('simulated_users.secrets.randbelow', return_value=0):
            self.step(10)
        self.assertEqual(len(self.orders()), 1)
        self.assertEqual(self.member['balance'], 999 + 100000 - 1000)
        self.assertEqual(set(self.member['wallets'].values()), {99999})
        status = self.member['autoBetStatus']['canada28']
        self.assertEqual(status['count'], 1)
        request = self.engine.s['requests'][-1]
        self.assertEqual((request['amount'], request['status'], request['autoApproved']), (100000, '已通过', True))
        chat = self.engine.game('canada28')['chat']
        self.assertTrue(any(m['username']=='localdemo' and m['content']=='上分1000' for m in chat))
        success = next(m for m in chat if m['kind']=='SCORE_REVIEW')
        self.assertEqual(success['details']['balance'], 100999)
        self.assertFalse(any(m['kind']=='SCORE_REQUEST' for m in chat))
        self.step(10)
        self.assertEqual(len(self.orders()), 1)
        self.assertEqual(len(self.engine.s['requests']), 1)

    def test_top_up_cooldown_shared_by_rooms_and_survives_restart(self):
        self.engine.credit('localdemo', 'canada28', -self.member['balance'], 'test empty', 'empty')
        for game in self.engine.s['games']:
            self.engine.configure(game, dict(maxBet=10000))
            self.configure(game, amountMin=6000, amountMax=6000)
        with patch('simulated_users.secrets.randbelow', side_effect=lambda n: n-1):
            self.step()
        self.assertEqual(self.engine.s['requests'][-1]['amount'], 500000)
        self.assertEqual(len(self.engine.s['requests']), 1)
        self.assertEqual(self.orders(), [])
        self.engine = Engine(self.directory.name)
        simulated_users.initialize(self.engine)
        self.step(1)
        self.assertEqual(len(self.engine.s['requests']), 1)
        self.assertEqual(self.member['balance'], 500000)

    def test_stopped_or_real_accounts_never_receive_scheduler_funds(self):
        self.engine.credit('localdemo', 'canada28', -self.member['balance'], 'test empty', 'empty')
        self.configure()
        self.engine.game('canada28')['paused'] = True
        self.step()
        self.assertEqual(self.engine.s['requests'], [])
        self.engine.game('canada28')['paused'] = False
        self.member['robot'] = False
        self.step()
        self.assertEqual(self.engine.s['requests'], [])
        self.member.update(robot=True, enabled=False)
        self.step()
        self.assertEqual(self.engine.s['requests'], [])

    def test_cap_survives_resave_toggle_restart_and_cancellation(self):
        self.configure()
        self.step()
        order = self.orders()[0]
        self.engine.cancel('localdemo', 'canada28', order['id'])
        self.configure()
        self.step(10)
        self.assertEqual(len(self.orders()), 1)
        simulated_users.configure(self.engine, 'canada28',
                                  dict(username='localdemo', enabled=False))
        self.configure()
        self.step(10)
        self.assertEqual(len(self.orders()), 1)
        self.restart()
        self.step(10)
        self.assertEqual(len(self.orders()), 1)
        self.assertEqual(self.member['autoBetStatus']['canada28']['count'], 1)
        self.assertEqual(self.member['wallets']['canada28'], 100000)

    def test_restart_reconciles_count_from_history(self):
        self.configure()
        self.step()
        self.member['autoBetStatus']['canada28']['count'] = 0
        self.restart()
        self.step(10)
        self.assertEqual(len(self.orders()), 1)
        self.assertEqual(self.member['autoBetStatus']['canada28']['count'], 1)

    def test_next_round_resets_cap(self):
        self.configure()
        self.step()
        prior_issue = self.orders()[0]['issue']
        self.engine.settle('canada28', prior_issue, [0, 0, 1], 'manual')
        self.engine.tick()
        self.step(5)
        self.assertEqual(len(self.orders()), 2)
        self.assertNotEqual(self.orders()[1]['issue'], prior_issue)
        self.assertEqual(self.member['autoBetStatus']['canada28']['count'], 1)

    def test_room_settings_and_ball_are_isolated(self):
        self.configure()
        self.configure('australia8ball', amountMin='2', amountMax='2',
                       selections=['2番'], ball=2, betsPerRound=2)
        self.step()
        canada, = self.orders('canada28')
        australian, = self.orders('australia8ball')
        self.assertEqual((canada['amount'], canada['ball']), (1000, 8))
        self.assertEqual((australian['amount'], australian['ball']), (200, 0))
        self.assertEqual(self.orders('australia8'), [])
        self.assertEqual(self.member['balance'], 98800)
        self.assertEqual(set(self.member['wallets'].values()), {98800})
        self.step()
        self.assertEqual(len(self.orders('canada28')), 1)
        self.assertEqual(len(self.orders('australia8ball')), 2)
        self.engine.settle('australia8ball', australian['issue'],
                           [0, 0, 2], 'manual')
        self.assertEqual(australian['status'], '中奖')

    def test_changed_room_limits_block_now_invalid_autobet_amount(self):
        self.configure()
        self.engine.configure('canada28', dict(minBet='20'))
        self.step(20)
        self.assertEqual(self.orders(), [])
        self.assertEqual(self.member['wallets']['canada28'], 100000)

    def test_invalid_configuration_is_rejected_atomically(self):
        self.configure(enabled=False)
        invalid = [dict(enabled='true'), dict(amountMin='0'), dict(amountMin='0.001'),
            dict(amountMin='NaN'), dict(amountMax='Infinity'), dict(amountMin='20', amountMax='10'),
            dict(amountMax='1000001'), dict(amountMax='1001'), dict(selections=[]),
            dict(selections=['13角']), dict(selections=['1番10']), dict(selections='1番'),
            dict(selections=['1番'] * 31), dict(intervalSeconds=4), dict(intervalSeconds=3601),
            dict(intervalSeconds=5.5), dict(intervalSeconds=True), dict(betsPerRound=0),
            dict(betsPerRound=101), dict(betsPerRound=1.5), dict(ball=0), dict(ball=9),
            dict(ball=1.5), dict(username='missing'), dict(username='localadmin')]
        for invalid_fields in invalid:
            with self.subTest(invalid=invalid_fields):
                before = copy.deepcopy(self.engine.s)
                with self.assertRaises(ValueError):
                    self.configure(**invalid_fields)
                self.assertEqual(self.engine.s, before)


if __name__ == '__main__':
    unittest.main()
