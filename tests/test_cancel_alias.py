import copy
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from engine import Engine, GAMES, new_user


class CancelAliasTests(unittest.TestCase):
    def test_all_aliases_refund_only_current_user_and_room_once(self):
        for room in GAMES:
            for command in ('退', '退单', '取消'):
                with self.subTest(room=room, command=command), patch.object(Engine, 'save'):
                    e = Engine(Path(__file__).parent)
                    e.s['users']['other'] = new_user('other', 'test-only', 'Other')
                    other_room = next(k for k in GAMES if k != room)
                    e.submit('localdemo', other_room, '1番10')
                    e.submit('other', room, '2番10')
                    before = e.s['users']['localdemo']['balance']
                    e.submit('localdemo', room, '1番10,2番10')
                    orders = list(e.pending(room, 'localdemo'))
                    e.message('localdemo', room, command, 8)
                    self.assertEqual(e.s['users']['localdemo']['balance'], before)
                    self.assertEqual([o['status'] for o in orders], ['已退单', '已退单'])
                    self.assertEqual(len(e.pending(room, 'other')), 1)
                    self.assertEqual(len(e.pending(other_room, 'localdemo')), 1)
                    snapshot = copy.deepcopy(e.s)
                    with self.assertRaisesRegex(ValueError, '没有可退注单'):
                        e.message('localdemo', room, command, 8)
                    self.assertEqual(e.s, snapshot)

    def test_cancel_keeps_closed_and_last_minute_restrictions(self):
        for room in GAMES:
            with self.subTest(room=room), patch.object(Engine, 'save'):
                e = Engine(Path(__file__).parent)
                e.submit('localdemo', room, '1番10')
                e.game(room)['closed'] = True
                snapshot = copy.deepcopy(e.s)
                with self.assertRaisesRegex(ValueError, '封盘后不能退单'):
                    e.message('localdemo', room, '取消', 8)
                self.assertEqual(e.s, snapshot)
        with patch.object(Engine, 'save'):
            e = Engine(Path(__file__).parent)
            e.submit('localdemo', 'australia8', '1番10')
            e.game('australia8')['endAt'] = time.time()+40
            snapshot = copy.deepcopy(e.s)
            with self.assertRaisesRegex(ValueError, '60秒以内禁止取消'):
                e.message('localdemo', 'australia8', '取消', 8)
            self.assertEqual(e.s, snapshot)


if __name__ == '__main__':
    unittest.main()
