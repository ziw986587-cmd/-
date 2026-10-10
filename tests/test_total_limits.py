import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine


class TotalLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp_path = Path(__file__).resolve().parents[1] / '.test-temp' / 'total-limits'
        self.temp_path.mkdir(parents=True, exist_ok=True)
        for path in self.temp_path.iterdir():
            if path.is_file():
                path.unlink()
        self.addCleanup(self.cleanup_temp)
        self.engine = Engine(self.temp_path)
        for key in self.engine.s['games']:
            self.engine.configure(key, {'mode': 'manual', 'period': 600})

    def cleanup_temp(self):
        for path in self.temp_path.glob('*'):
            if path.is_file():
                path.unlink()

    def test_same_play_is_capped_per_current_issue_and_cancel_releases_capacity(self):
        for key in ('canada28', 'australia8ball', 'australia8'):
            with self.subTest(key=key):
                self.engine.configure(key, {'totalLimits': {'番': '10'}})
                self.engine.submit('localdemo', key, '1番6', 1 if key == 'australia8' else 8)
                before = copy.deepcopy(self.engine.s)
                with self.assertRaisesRegex(ValueError, '总限额'):
                    self.engine.submit('localdemo', key, '2番5', 2 if key == 'australia8' else 8)
                self.assertEqual(self.engine.s, before)
                self.engine.cancel('localdemo', key)
                self.engine.submit('localdemo', key, '2番10', 2 if key == 'australia8' else 8)
                self.assertEqual(sum(o['amount'] for o in self.engine.pending(key)), 1000)

    def test_sum_aliases_share_the_same_limit_group(self):
        key = 'canada28'
        self.engine.configure(key, {'totalLimits': {'大/小': '10'}})
        self.engine.submit('localdemo', key, '大6')
        with self.assertRaisesRegex(ValueError, '大/小玩法本期总限额'):
            self.engine.submit('localdemo', key, '小5')

    def test_batch_limit_is_atomic_and_unconfigured_groups_are_unlimited(self):
        key = 'australia8ball'
        self.engine.configure(key, {'totalLimits': {'番': '10'}})
        before = copy.deepcopy(self.engine.s)
        with self.assertRaisesRegex(ValueError, '总限额'):
            self.engine.submit('localdemo', key, '1番6,2番5')
        self.assertEqual(self.engine.s, before)
        self.engine.submit('localdemo', key, '12角100')
        self.assertEqual(len(self.engine.pending(key)), 1)

    def test_user_room_limit_caps_one_member_current_round_and_cancel_releases_capacity(self):
        key = 'canada28'
        self.engine.configure(key, {'userLimit': '10'})
        self.engine.submit('localdemo', key, '1番6')
        with self.assertRaisesRegex(ValueError, '本房间用户限额'):
            self.engine.submit('localdemo', key, '2番5')
        self.engine.cancel('localdemo', key)
        self.engine.submit('localdemo', key, '2番10')
        self.assertEqual(sum(o['amount'] for o in self.engine.pending(key)), 1000)

    def test_user_room_limit_is_atomic_for_multi_bet_batch(self):
        key = 'australia8ball'
        self.engine.configure(key, {'userLimit': '10'})
        before = copy.deepcopy(self.engine.s)
        with self.assertRaisesRegex(ValueError, '本房间用户限额'):
            self.engine.submit('localdemo', key, '1番6,2番5')
        self.assertEqual(self.engine.s, before)


if __name__ == '__main__':
    unittest.main()
