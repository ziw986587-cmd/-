"""Rolling seven-day business history with compact wallet opening balances."""
import copy
import math
import time
from datetime import datetime, timedelta, timezone

DAYS = 7
INTERVAL = 300
BEIJING = timezone(timedelta(hours=8))
PENDING_ORDERS = {'待开奖', '待手动结算', '待结算'}


def record_time(row):
    """Read completion time first; legacy desktop timestamps are Beijing-local."""
    for field in ('completedAt', 'reviewedAt', 'time', 'placedAt'):
        value = row.get(field)
        try:
            if isinstance(value, (float, int)) and not isinstance(value, bool):
                result = float(value)
            elif isinstance(value, str) and value:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if parsed.tzinfo is None and (row.get('legacy') or
                        str(row.get('id', '')).startswith('legacy-')):
                    parsed = parsed.replace(tzinfo=BEIJING)
                result = parsed.timestamp()
            else:
                continue
            if math.isfinite(result):
                return result
        except (ValueError, OverflowError, OSError):
            continue
    return None


def prune(engine, now=None, force=False):
    """Atomically prune finished records; never derive a wallet from truncated history."""
    now = time.time() if now is None else now
    with engine.lock:
        previous_run = getattr(engine, '_retention_checked_at', None)
        if not force and previous_run is not None and 0 <= now - previous_run < INTERVAL:
            return False
        cutoff = now - DAYS * 86400
        state = engine.s
        updates, removed = {}, {}

        def keep(row):
            recorded = record_time(row)
            # Do not guess the age of malformed/undated historical records.
            return recorded is None or recorded >= cutoff

        old_orders = state.get('orders', [])
        order_mask = [o.get('status') in PENDING_ORDERS or keep(o) for o in old_orders]
        orders = [o for o, retain in zip(old_orders, order_mask) if retain]
        if len(orders) != len(old_orders):
            updates['orders'] = orders
            removed['orders'] = len(old_orders) - len(orders)
            # statFrom is an index into the order array; translate reset points.
            workbench = copy.deepcopy(state.get('workbench', {}))
            for prefs in workbench.values():
                offset = max(0, int(prefs.get('statFrom', 0)))
                prefs['statFrom'] = sum(order_mask[:offset])
            if 'workbench' in state:
                updates['workbench'] = workbench

        ledger = state.get('ledger', [])
        retained_ledger = [r for r in ledger if keep(r)]
        if len(retained_ledger) != len(ledger):
            opening = dict(state.get('ledgerOpening', {}))
            for row in ledger:
                if not keep(row):
                    name = row['username']
                    opening[name] = opening.get(name, 0) + row['delta']
            updates.update(ledger=retained_ledger, ledgerOpening=opening)
            removed['ledger'] = len(ledger) - len(retained_ledger)

        for field in ('requests', 'rebateBatches', 'adminLog'):
            rows = state.get(field, [])
            retained = [r for r in rows if keep(r) or
                        (field == 'requests' and r.get('status') == '待审核')]
            if len(rows) != len(retained):
                updates[field] = retained
                removed[field] = len(rows) - len(retained)

        games = None
        for key, room in state['games'].items():
            for field in ('chat', 'history'):
                rows = room.get(field, [])
                retained = [r for r in rows if keep(r)]
                if len(rows) != len(retained):
                    if games is None:
                        games = {k: dict(g) for k, g in state['games'].items()}
                    games[key][field] = retained
                    removed[key + '.' + field] = len(rows) - len(retained)
        if games is not None:
            updates['games'] = games

        for field in ('dedup', 'unifiedDedup'):
            entries = state.get(field, {})
            retained, changed = {}, False
            for key, entry in entries.items():
                recorded = record_time(entry)
                if recorded is None:
                    # Existing idempotency records had no timestamp. Grant a
                    # full retry window from first activation of retention.
                    retained[key] = {**entry, 'time': now}
                    changed = True
                elif recorded >= cutoff:
                    retained[key] = entry
                else:
                    changed = True
            if changed:
                updates[field] = retained
                removed[field] = len(entries) - len(retained)

        if state.get('retention', {}).get('days') != DAYS or removed:
            updates['retention'] = dict(days=DAYS, lastCleanupAt=now,
                                        cutoff=cutoff, removed=removed)
        if not updates:
            engine._retention_checked_at = now
            return False
        previous = dict(state)
        try:
            state.update(updates)
            engine.save()
        except Exception:
            engine.s = previous
            raise
        engine._retention_checked_at = now
        return True
