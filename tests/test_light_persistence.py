import json
import sys
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'room-engine'
sys.path.insert(0, str(ROOT))
from engine import Engine  # noqa: E402


class LightPersistenceTest(unittest.TestCase):
    def test_chat_overlay_preserves_financial_arrays_across_restart(self):
        directory = Path(__file__).resolve().parents[2] / 'test-tmp' / 'light-persistence-fixture'
        if directory.exists():
            for child in directory.iterdir():
                if child.is_file(): child.unlink()
                elif child.is_dir(): shutil.rmtree(child)
        directory.mkdir(parents=True, exist_ok=True)
        engine = Engine(str(directory), defer_wallet_migration=True)
        engine.s['orders'].append({'id': 'order-1', 'status': '待开奖'})
        engine.s['ledger'].append({'id': 'ledger-1', 'delta': -100})
        engine.save()
        engine.chat('canada28', '测试消息', 'localdemo')
        engine.save_light()

        base = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(base['orders'][0]['id'], 'order-1')
        self.assertTrue((directory / 'state.overlay.json').exists())

        restarted = Engine(str(directory), defer_wallet_migration=True)
        self.assertEqual(restarted.s['orders'][0]['id'], 'order-1')
        self.assertEqual(restarted.s['ledger'][0]['id'], 'ledger-1')
        self.assertEqual(restarted.s['games']['canada28']['chat'][-1]['content'], '测试消息')

        restarted.save()
        self.assertFalse((directory / 'state.overlay.json').exists())


if __name__ == '__main__':
    unittest.main()
