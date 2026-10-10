"""Follow available Australia3 results; never substitute another issue's result."""
import copy
import math
import re
import time

URL = 'https://draw.210.56.49.251.sslip.io/api/australia3/latest'


def supports(key, config):
    return (key == 'australia8ball' and config.get('format', 'json') == 'json'
            and config.get('url') == URL and config.get('rootPath', '') == ''
            and all(config.get(k) == v for k, v in {
                'issuePath': 'latest.period', 'numbersPath': 'latest.numbers',
                'nextIssuePath': 'currentIssue', 'nextTimePath': 'nextAt'}.items()))


def issue(value):
    value = str(value)
    if not re.fullmatch(r'[1-9][0-9]{0,19}', value):
        raise ValueError('澳洲3期号无效')
    return value


def record(raw):
    if not isinstance(raw, dict): raise ValueError('澳洲3开奖记录无效')
    numbers = raw.get('numbers')
    if not isinstance(numbers, list) or len(numbers) != 3 or any(type(n) is not int or not 0 <= n <= 9 for n in numbers):
        raise ValueError('澳洲3号码须为三个0至9整数')
    opened = raw.get('openedAt')
    if type(opened) not in (int, float) or not math.isfinite(opened) or opened < 946684800:
        raise ValueError('澳洲3开奖时间无效')
    return dict(issue=issue(raw.get('period')), numbers=numbers, openTime=opened)


def current(raw):
    if not isinstance(raw, dict) or raw.get('ok') is not True or raw.get('game') != 'australia3':
        raise ValueError('澳洲3接口响应无效')
    row = record(raw.get('latest'))
    row['nextIssue'] = issue(raw.get('currentIssue'))
    if int(row['nextIssue']) <= int(row['issue']): raise ValueError('澳洲3下期期号无效')
    nt = raw.get('nextAt')
    # Manual/paused sources have no deadline, but their completed draws are valid.
    if nt is None: nt = 0
    if type(nt) not in (int, float) or not math.isfinite(nt) or nt < 0:
        raise ValueError('澳洲3下期开奖时间无效')
    row['nextTime'] = nt
    return row


def fetch_payload(engine, key, config, fetch):
    raw = fetch(config)
    row = current(raw)
    with engine.lock:
        g = engine.game(key)
        known = [int(h['issue']) for h in g['history'] if h['issue'].isdigit()]
        start = max(known)+1 if known else int(g['issue']) if g['issue'].isdigit() else int(row['issue'])
        if g.get('a3HistoryFrom'): start = min(start, int(g['a3HistoryFrom']))
        pending = [int(o['issue']) for o in engine.pending(key) if o['issue'].isdigit()]
        if pending: start = min(start, min(pending))
        # Bound historical requests for an absent old issue to once per 30 seconds.
        cache = getattr(engine, '_a3_history_poll', None)
        due = not cache or cache['config'] != config or time.monotonic() >= cache['due']
    history, error, complete = [], '', False
    needs_history = start < int(row['issue'])
    if needs_history and due:
        denied = False
        try:
            for page in range(1, 6):
                data = fetch({**config, 'url': URL.rsplit('/', 1)[0]+f'/history?page={page}&pageSize=100'})
                if not isinstance(data, dict) or data.get('ok') is not True or not isinstance(data.get('records'), list):
                    raise ValueError('澳洲3历史响应无效')
                batch = data['records']
                checked = [record(r) for r in batch]
                history.extend(batch)
                if not checked or min(int(r['issue']) for r in checked) <= start or page >= data.get('pages', 1):
                    complete = True
                    break
        except Exception as exc:
            # A temporarily unavailable historical endpoint must not block new draws.
            error = '历史补抓暂不可用，继续同步最新结果'
            denied = getattr(exc, 'code', None) in (401, 403)
        with engine.lock:
            engine._a3_history_poll = dict(config=copy.deepcopy(config), due=float('inf') if denied else time.monotonic()+30)
    return dict(latest=raw, history=history, historyError=error,
                historyStart=start if needs_history else None, historyComplete=complete)


def apply(engine, key, payload, config, now):
    if not supports(key, config): raise ValueError('澳洲3接口配置不匹配')
    wrapped = isinstance(payload, dict) and 'history' in payload
    row = current(payload['latest'] if wrapped else payload)
    if row['openTime'] > now+5: raise ValueError('澳洲3开奖时间在未来')
    if row['nextTime'] > now+86400: raise ValueError('澳洲3下期开奖时间过远')
    rows = {row['issue']: row}
    for raw in payload.get('history', []) if wrapped else []:
        r = record(raw)
        if r['openTime'] > now+5: raise ValueError('澳洲3历史开奖时间在未来')
        if int(r['issue']) > int(row['issue']): continue
        if r['issue'] in rows and rows[r['issue']]['numbers'] != r['numbers']:
            raise ValueError('澳洲3同一期号码冲突')
        rows.setdefault(r['issue'], r)
    g = engine.game(key)
    existing = {h['issue']: h['numbers'] for h in g['history']}
    known = [int(n) for n in existing if n.isdigit()]
    high = max(known) if known else -1
    pending_issues = {o['issue'] for o in engine.pending(key)}
    for n, r in rows.items():
        if n in existing and existing[n] != r['numbers']: raise ValueError('澳洲3已记录号码冲突')
    if pending_issues.intersection(existing): raise ValueError('澳洲3已记录期仍有待结算注单，需核对')
    wanted = sorted((r for n, r in rows.items() if n not in existing), key=lambda r: int(r['issue']))
    saved_round = {k: copy.deepcopy(g[k]) for k in ('issue', 'endAt', 'closed', 'warned')}
    can_advance = int(row['issue']) >= high and (not g['issue'].isdigit() or int(row['nextIssue']) >= int(g['issue']))
    final_issue = row['nextIssue'] if can_advance else g['issue']
    final_time = row['nextTime'] if can_advance else g['endAt']
    history_change = (wrapped and payload.get('historyStart') is not None and
                      ((payload.get('historyComplete') and g.get('a3HistoryFrom') is not None) or
                       (not payload.get('historyComplete') and g.get('a3HistoryFrom') != payload['historyStart'])))
    round_change = can_advance and (g['issue'] != final_issue or g['endAt'] != final_time)
    # Unchanged polls are read-only; copy rollback state only for actual mutations.
    before = copy.deepcopy(engine.s) if wanted or history_change or round_change else None
    changed = False
    try:
        if wrapped and payload.get('historyStart') is not None:
            if payload.get('historyComplete'):
                if g.pop('a3HistoryFrom', None) is not None: changed = True
            elif g.get('a3HistoryFrom') != payload['historyStart']:
                g['a3HistoryFrom'] = payload['historyStart']
                changed = True
        for r in wanted:
            # Closing a historical issue must not close or label today's active issue.
            g.update(issue=r['issue'], closed=True)
            engine.settle(key, r['issue'], r['numbers'], 'external', final_issue, final_time)
            g['history'][0].update(sourceOpenTime=r['openTime'], receivedAt=now)
        if wanted:
            g['history'].sort(key=lambda h: int(h['issue']) if h['issue'].isdigit() else -1, reverse=True)
            g.update(saved_round)
            changed = True
        if can_advance and (g['issue'] != final_issue or g['endAt'] != final_time):
            new_round = g['issue'] != final_issue
            g.update(issue=final_issue, endAt=final_time)
            if new_round: g.update(closed=False, warned=False)
            # An expired/missing countdown never prevents accepting a completed draw.
            if final_time <= now+g['closeSeconds']: engine.close_round(key)
            elif new_round or not saved_round['endAt']: g['closed'] = False
            changed = True
        if changed: engine.save()
    except Exception:
        if before is not None: engine.s = before
        raise
    missing = [o for o in engine.pending(key) if o['issue'].isdigit() and int(o['issue']) <= int(row['issue'])]
    status = f'读取成功 · 澳洲3 · 同步{len(wanted)}期'
    if missing: status += f' · {len(missing)}笔旧注单等待对应期结果，最新开奖正常同步'
    if wrapped and payload.get('historyError'): status += ' · '+payload['historyError']
    elif g.get('a3HistoryFrom'): status += ' · 历史记录继续补抓'
    return status
