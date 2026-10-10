import copy
import unittest
from unittest.mock import patch
from tests import test_autobet
from engine import parse_bets, money


class IntegerBetTests(unittest.TestCase):
    setUp = test_autobet.SimulatedAutoBetTests.setUp
    configure = test_autobet.SimulatedAutoBetTests.configure
    step = test_autobet.SimulatedAutoBetTests.step
    orders = test_autobet.SimulatedAutoBetTests.orders
    member = test_autobet.SimulatedAutoBetTests.member
    def test_decimal_batches_fail_without_balance_or_order_changes(self):
        for game in self.engine.s['games']:
            for text in ['单/599.60', '2番/72.67', '4番/200.00', '1番10,2番0.01',
                         '12/10.00', '1+23/2.50', '12念3.00', '01-02特4.50']:
                with self.subTest(game=game, text=text):
                    before=copy.deepcopy(self.engine.s)
                    with self.assertRaises(ValueError):
                        self.engine.submit('localdemo', game, text, 8)
                    self.assertEqual(self.engine.s, before)
            self.assertEqual(parse_bets('单/599,2番/72', game)[0]['amount'],59900)
        self.assertEqual(money('12.34'),1234)

    def test_old_fractional_auto_range_generates_only_in_range_integers(self):
        self.configure(amountMin='2',amountMax='4',betsPerRound=10)
        config=self.member['autoBet']['canada28']
        config.update(amountMin=201,amountMax=499)
        for pick in (0,1):
            with patch('simulated_users.secrets.randbelow',return_value=pick):
                self.step()
        self.assertEqual([o['amount'] for o in self.orders()],[300,400])
        config.update(amountMin=201,amountMax=299)
        self.step()
        self.assertEqual(len(self.orders()),2)
        self.assertEqual(self.member['autoBetStatus']['canada28']['state'],'invalid-limits')

    def test_auto_balance_fraction_is_not_spent(self):
        self.configure(amountMin='1',amountMax='2')
        self.member['balance']=199
        self.step()
        self.assertEqual(self.orders()[0]['amount'],100)
        self.assertEqual(self.member['balance'],99)

    def test_new_auto_config_rejects_decimal_amounts(self):
        for value in ('2.50','2.00'):
            with self.assertRaisesRegex(ValueError,'正整数'):
                self.configure(amountMin=value,amountMax=value)
