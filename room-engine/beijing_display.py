"""Format portal timestamps in Beijing time without rewriting stored records."""
import copy
import re
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))
STAMP = re.compile(r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$')
SUFFIX = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')


def format_time(value, source_zone=None):
    if not isinstance(value, str) or not STAMP.fullmatch(value):
        return value
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None and source_zone is not None:
            parsed = parsed.replace(tzinfo=source_zone)
        # Existing engine stamps are server-local. astimezone() resolves naive
        # values in that server's zone, so local Beijing installations stay correct.
        return parsed.astimezone(BEIJING).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, OverflowError, OSError):
        return value


def present(snapshot, source_zone=None):
    result = copy.deepcopy(snapshot)
    if result.get('displayTimeZone') == 'Asia/Shanghai':
        return result
    for field in ('chat', 'history', 'orders', 'ledger', 'requests'):
        for row in result.get(field, []):
            if 'time' in row:
                # Migrated desktop orders/requests originated in Beijing time.
                row['time'] = format_time(row['time'], BEIJING if row.get('legacy') or
                    str(row.get('id', '')).startswith('legacy-') else source_zone)
    status = result.get('feedStatus')
    if isinstance(status, str):
        result['feedStatus'] = SUFFIX.sub(lambda m: format_time(m.group(), source_zone), status)
    result['displayTimeZone'] = 'Asia/Shanghai'
    return result
