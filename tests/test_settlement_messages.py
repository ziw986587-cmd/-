"""Per-round member settlement messages, with only isolated local balances."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES, money
from unified import mutate_member


class SettlementMessageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='settlement-message-test-')
        self.addCleanup(self.directory.cleanup)
        self.clock = patch('engine.time.time', return_value=1800000000.0)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.engine = Engine(self.directory.name)
        for game in GAMES:
            self.engine.configure(game, dict(mode='manual', period=3600,
                closeSeconds=10, minBet='0.01', maxBet='1000', paused=False))
        user = self.engine.s['users']['localdemo']
        self.engine.credit('localdemo', 'canada28', 10000 - user['balance'],
                           'test opening adjustment', 'opening')

    def member(self, username, nickname=None, amount='100', **flags):
        mutate_member(self.engine, 'member.create', 'canada28', dict(
            username=username, nickname=nickname or username, amount=amount))
        user = self.engine.s['users'][username]
        user.update(flags)
        return user

    def settlement(self, game='canada28'):
        messages = [m for m in self.engine.game(game)['chat']
                    if m['kind'] == 'SETTLEMENT']
        self.assertTrue(messages, 'Every completed round needs its own settlement message')
        return messages[-1]

    def settle(self, game='canada28', numbers=None):
        issue = self.engine.game(game)['issue']
        numbers = numbers or ([0, 0, 1] if game != 'australia8' else list(range(1, 9)))
        self.assertTrue(self.engine.settle(game, issue, numbers, 'manual'))
        return self.settlement(game)

    def assert_balances_reconcile(self):
        for username, user in self.engine.s['users'].items():
            with self.subTest(username=username):
                self.assertEqual(user['wallets'], {key: user['balance'] for key in GAMES})
                self.assertEqual(user['balance'], sum(row['delta'] for row in
                    self.engine.s['ledger'] if row['username'] == username))

    def test_result_then_settlement_then_ranking_and_history(self):
        self.engine.submit('localdemo', 'canada28', '1番1')
        issue = self.engine.game('canada28')['issue']
        message = self.settle()
        messages = self.engine.game('canada28')['chat']
        index = next(i for i, row in enumerate(messages) if row['kind'] == 'JIEGUO')
        self.assertEqual([row['kind'] for row in messages[index:index + 4]],
                         ['JIEGUO', 'SETTLEMENT', 'YINGLI', 'LUZI'])
        result = messages[index]['content']
        self.assertEqual(len(result.splitlines()), 2)
        self.assertNotIn('获胜名单', result)
        self.assertNotIn('盈：', result)
        self.assertEqual(message['details']['issue'], issue)
        self.assertEqual(message['details']['game'], 'canada28')
        self.assertIsNone(message['username'])
        self.assertEqual(message['details']['totalProfit'], 291)
        self.assert_balances_reconcile()

    def test_net_profit_includes_wins_losses_pushes_and_cent_rounding(self):
        user = self.engine.s['users']['localdemo']
        user.update(robot=True)
        self.member('loser')
        self.member('pushonly')
        self.member('inactive', enabled=False)
        # Seed pre-integer-rule pending orders; historical cents still settle exactly.
        with patch('engine.bet_money', side_effect=money):
            self.engine.submit('localdemo', 'canada28',
                               '1番10,2番4,2念1/3,1番0.01,2番0.01')
        self.engine.submit('loser', 'canada28', '2番5')
        self.engine.submit('pushonly', 'canada28', '2念1/2')
        message = self.settle()
        rows = {row['username']: row for row in message['details']['rows']}
        self.assertEqual(set(rows), {'localdemo', 'loser', 'pushonly', 'inactive'})
        self.assertEqual(rows['localdemo'], dict(username='localdemo',
            nickname=user['nickname'], simulated=True, balance=12512,
            profit=2512, betCount=5))
        self.assertEqual((rows['loser']['balance'], rows['loser']['profit'],
                          rows['loser']['betCount']), (9500, -500, 1))
        self.assertEqual((rows['pushonly']['balance'], rows['pushonly']['profit'],
                          rows['pushonly']['betCount']), (10000, 0, 1))
        self.assertEqual((rows['inactive']['balance'], rows['inactive']['profit'],
                          rows['inactive']['betCount']), (10000, 0, 0))
        self.assertIs(rows['loser']['simulated'], False)
        self.assertEqual(message['details']['totalProfit'], 2012)
        profits = [order['profit'] for order in self.engine.s['orders']
                   if order['username'] == 'localdemo']
        self.assertEqual(profits, [2910, -400, 0, 3, -1])
        self.assert_balances_reconcile()

    def test_same_nickname_keeps_separate_accounts_and_sorts_by_final_balance(self):
        self.engine.s['users']['localdemo']['nickname'] = '同名会员'
        self.member('twin', nickname='同名会员', amount='150')
        self.member('highest', amount='200')
        self.engine.submit('localdemo', 'canada28', '1番1')
        self.engine.submit('twin', 'canada28', '2番3')
        rows = self.settle()['details']['rows']
        self.assertEqual([row['username'] for row in rows], ['highest', 'twin', 'localdemo'])
        self.assertEqual([row['balance'] for row in rows], [20000, 14700, 10291])
        self.assertEqual([row['profit'] for row in rows], [0, -300, 291])
        self.assertEqual(sum(row['nickname'] == '同名会员' for row in rows), 2)
        self.assert_balances_reconcile()

    def test_other_rounds_rooms_and_refunds_are_excluded_from_round_profit(self):
        self.engine.submit('localdemo', 'canada28', '3番1')
        self.settle()
        game = self.engine.game('canada28')
        current_issue = game['issue']
        self.engine.submit('localdemo', 'canada28', '1番1')
        self.engine.submit('localdemo', 'canada28', '1番10')
        refunded = self.engine.s['orders'][-1]
        self.engine.cancel('localdemo', 'canada28', refunded['id'])
        self.engine.submit('localdemo', 'australia8', '1番2')
        game['issue'] = 'FUTURE-ISSUE'
        self.engine.submit('localdemo', 'canada28', '1番2')
        game['issue'] = current_issue
        message = self.settle()
        row, = message['details']['rows']
        self.assertEqual((row['profit'], row['betCount'], row['balance']), (291, 1, 9791))
        self.assertEqual(message['details']['totalProfit'], 291)
        self.assertEqual(refunded['status'], '已退单')
        self.assertEqual(len(self.engine.pending('canada28')), 1)
        self.assertEqual(len(self.engine.pending('australia8')), 1)
        self.assert_balances_reconcile()

    def test_australia3_uses_sum_for_all_orders_regardless_of_legacy_ball_input(self):
        game = 'australia8ball'
        self.engine.submit('localdemo', game, '1番2', ball=1)
        self.engine.submit('localdemo', game, '3番1', ball=8)
        self.engine.submit('localdemo', game, '3念1/1', ball=4)
        message = self.settle(game)
        row, = message['details']['rows']
        self.assertEqual((row['profit'], row['betCount'], row['balance']), (482, 3, 10482))
        self.assertEqual(message['details']['totalProfit'], 482)
        self.assertEqual([order['status'] for order in self.engine.s['orders']],
                         ['中奖', '未中', '和局'])
        self.assert_balances_reconcile()

    def test_round_with_no_bets_still_lists_all_members_with_zero_profit(self):
        self.member('other', amount='0', robot=True, enabled=False)
        for game in GAMES:
            with self.subTest(game=game):
                message = self.settle(game)
                rows = message['details']['rows']
                self.assertEqual({row['username'] for row in rows}, {'localdemo', 'other'})
                self.assertTrue(all(row['profit'] == 0 and row['betCount'] == 0 for row in rows))
                self.assertEqual(message['details']['totalProfit'], 0)
        self.assert_balances_reconcile()

    def test_historical_snapshot_survives_later_balance_and_identity_changes_and_restart(self):
        self.engine.submit('localdemo', 'canada28', '1番1')
        message = self.settle()
        original = copy.deepcopy(message)
        self.engine.credit('localdemo', 'australia8', 12345, 'test later credit', 'later')
        self.engine.s['users']['localdemo'].update(nickname='改名后', robot=True)
        self.engine.submit('localdemo', 'australia8', '4番1')
        self.settle('australia8')
        self.assertEqual(message, original)
        self.engine.save()
        restarted = Engine(self.directory.name)
        stored = next(row for row in restarted.game('canada28')['chat']
                      if row['id'] == original['id'])
        self.assertEqual(stored, original)
        self.assert_balances_reconcile()

    def test_repeated_settlement_changes_neither_messages_nor_ledger(self):
        self.engine.submit('localdemo', 'canada28', '1番1')
        issue = self.engine.game('canada28')['issue']
        self.settle()
        before = copy.deepcopy(self.engine.s)
        self.assertFalse(self.engine.settle('canada28', issue, [0, 0, 1], 'manual'))
        self.assertEqual(self.engine.s, before)

    def test_bot_disabled_settles_money_without_emitting_any_bot_messages(self):
        game = self.engine.game('canada28')
        self.engine.submit('localdemo', 'canada28', '1番1')
        game['bot'] = False
        messages = copy.deepcopy(game['chat'])
        self.assertTrue(self.engine.settle('canada28', game['issue'], [0, 0, 1], 'manual'))
        self.assertEqual(game['chat'], messages)
        self.assertEqual(self.engine.s['users']['localdemo']['balance'], 10291)
        self.assert_balances_reconcile()

    def test_chat_details_are_independent_from_callers_mutable_objects(self):
        details = dict(issue='TEST-1', rows=[dict(username='localdemo', balance=10000)])
        original = copy.deepcopy(details)
        self.engine.chat('canada28', 'details snapshot', details=details)
        self.engine.bot('canada28', 'bot details snapshot', details=details)
        details['rows'][0]['balance'] = 0
        details['rows'].append(dict(username='extra', balance=1))
        for message in self.engine.game('canada28')['chat'][-2:]:
            self.assertEqual(message['details'], original)


if __name__ == '__main__':
    unittest.main()
