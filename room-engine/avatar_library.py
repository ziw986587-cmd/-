"""Only bundled image avatars and the existing emoji choices are accepted."""
import json
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[1] / 'avatars' / 'catalog.json').read_text(encoding='utf-8'))
IMAGES = {'/avatars/' + row['id'] + '.svg' for row in CATALOG}
DEFAULT = '/avatars/nature-01.svg'
LEGACY = {'👤', '🙂', '🐱', '🐼', '🦊'}


def validate(value):
    if not isinstance(value, str) or value not in IMAGES | LEGACY:
        raise ValueError('请选择头像库中的头像')
    return value
