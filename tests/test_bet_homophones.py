import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES, parse_bets, outcome
from turnover import effective_turnover


class BetHomophoneTests(unittest.TestCase):
    def test_aliases_normalize_before_shorthand_and_punctuation(self):
        cases = [('1翻100', '1番100'), ('1糖100', '1正100'), ('1唐/100', '1正/100'),
                 ('1堂100', '1正100'), ('2堂/100', '2正/100'), ('1堂、100', '1正、100'), ('1堂头100', '1番100'),
                 ('12粘100', '12念100'), ('12娘/100', '12念/100'),
                 ('1粘2/100', '1念2/100'), ('1娘23/100', '1念23/100'),
                 ('1翻、100', '1番、100'), ('1糖-100', '1正-100'),
                 ('1娘2=100', '1念2=100'), ('1加23/100', '1+23/100')]
        for game in GAMES:
            for alias, canonical in cases:
                with self.subTest(game=game, alias=alias):
                    self.assertEqual(parse_bets(alias, game), parse_bets(canonical, game))

    def test_chat_alias_orders_keep_canonical_odds_outcomes_and_turnover(self):
        for game in GAMES:
            for fan in range(1, 5):
                with self.subTest(game=game, fan=fan), tempfile.TemporaryDirectory() as folder:
                    e = Engine(folder)
                    e.configure(game, dict(mode='manual', period=3600, minBet='1', maxBet='1000'))
                    balance = e.s['users']['localdemo']['balance']
                    # Mixed shorthand and explicit notation must pass the chat gate too.
                    e.message('localdemo', game, '1翻10,12粘10,1娘2/10,1糖10,1唐10', 8)
                    e.message('localdemo', game, '1堂10', 8)
                    alias_orders = e.pending(game, 'localdemo')[:]
                    e.message('localdemo', game, '1番10,1念2/10,1念2/10,1正10,1正10,1正10', 8)
                    canonical_orders = e.pending(game, 'localdemo')[6:]
                    self.assertEqual(e.s['users']['localdemo']['balance'], balance - 12000)
                    numbers = [n for n in range(1, 9) if n != fan] + [fan] if game=='australia8' else [0, 0, fan]
                    e.settle(game, e.game(game)['issue'], numbers, 'manual')
                    for alias, canonical in zip(alias_orders, canonical_orders):
                        for key in ['selection', 'amount', 'rate', 'status', 'profit', 'payout']:
                            self.assertEqual(alias[key], canonical[key])
                        self.assertEqual(effective_turnover(alias), effective_turnover(canonical))
                    self.assertEqual(alias_orders[4]['selection'], '1正')
                    self.assertEqual(alias_orders[4]['status'], {'win':'中奖','push':'和局','lose':'未中'}[outcome('1正',fan)])

    def test_aliases_do_not_allow_invalid_or_fractional_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            e = Engine(folder)
            for game in GAMES:
                e.configure(game, dict(mode='manual', period=3600, minBet='1', maxBet='1000'))
                for text in ['1翻10,1糖0.50', '1堂10.50', '1堂10,2堂0.01', '12粘10.00', '1娘1/10', '5糖100', '我吃糖100', '3在100']:
                    before = copy.deepcopy(e.s)
                    with self.subTest(game=game, text=text), self.assertRaises(ValueError):
                        e.message('localdemo', game, text, 8)
                    self.assertEqual(e.s, before)


if __name__ == '__main__': unittest.main()
