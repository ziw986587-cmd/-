"""Adapter for the user's expect/opencode history response (no remote writes)."""
import copy
import math
import re


def details(payload, scheme_id=1, lottery_id=2):
    found = {}

    def visit(value, depth=0):
        if depth > 8:
            return
        if isinstance(value, dict):
            if 'expect' in value and 'opencode' in value:
                # The endpoint returns several schemes for the same period.
                # Canada 28 is scheme 1 of lottery 2; ignore other schemes
                # before checking for duplicate periods.
                # Some versions of the source list omit scheme_id because the
                # URL already identifies the Canada 28 scheme. Treat a missing
                # value as the configured default while still rejecting an
                # explicitly different scheme.
                if scheme_id is not None and value.get('scheme_id') is not None \
                        and str(value.get('scheme_id')) != str(scheme_id):
                    return
                if lottery_id is not None and str(value.get('lottery_id')) != str(lottery_id):
                    return
                issue = str(value['expect'])
                if not re.fullmatch(r'\d{1,20}', issue):
                    raise ValueError('历史接口期号格式无效')
                numbers = value['opencode']
                if isinstance(numbers, str):
                    numbers = re.split(r'[,，\s]+', numbers.strip())
                if not isinstance(numbers, list) or len(numbers) != 3 or any(
                        not re.fullmatch(r'[0-9]', str(n)) for n in numbers):
                    raise ValueError('历史接口号码须为三个0至9整数')
                numbers = list(map(int, numbers))
                if issue in found and found[issue]['numbers'] != numbers:
                    raise ValueError('历史接口同一期存在冲突号码')
                def timestamp(name):
                    try:
                        raw = value.get(name, 0)
                        t = float(raw) if not isinstance(raw, bool) else 0
                        if t > 1e12: t /= 1000
                        return t if math.isfinite(t) and t >= 946684800 else 0
                    except (TypeError, ValueError):
                        return 0
                row = dict(numbers=numbers, openTime=timestamp('opentime'),
                           publishedAt=timestamp('createtime'))
                if issue not in found or row['openTime']:
                    found[issue] = row
            else:
                for child in value.values():
                    visit(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                visit(child, depth + 1)

    visit(payload)
    if not found:
        raise ValueError(f'未找到scheme_id={scheme_id}, lottery_id={lottery_id}的expect/opencode开奖记录')
    return sorted(found.items(), key=lambda row: int(row[0]))


def records(payload, scheme_id=1, lottery_id=2):
    return [(issue, row['numbers']) for issue, row in details(payload, scheme_id, lottery_id)]


def merge_ranges(ranges):
    merged = []
    for lo, hi in sorted(ranges):
        if lo > hi: continue
        if merged and lo <= merged[-1][1]+1: merged[-1][1] = max(hi, merged[-1][1])
        else: merged.append([lo, hi])
    return merged


def remove_known(ranges, numbers):
    for n in sorted(set(numbers)):
        remaining = []
        for lo, hi in ranges:
            if not lo <= n <= hi: remaining.append([lo, hi])
            else:
                if lo < n: remaining.append([lo, n-1])
                if n < hi: remaining.append([n+1, hi])
        ranges = remaining
    return ranges


def apply(engine, key, payload, config, now):
    if key != 'canada28': raise ValueError('此历史接口适配仅用于加拿大28')
    metadata = dict(details(payload, config.get('schemeId', 1), config.get('lotteryId', 2)))
    issue = next(reversed(metadata))
    latest = int(issue)
    g = engine.game(key)
    previous = engine.feed_observed.get(key)
    existing = {h['issue']: h['numbers'] for h in g['history']}
    persisted = [int(n) for n in existing if n.isdigit()]
    high = max(persisted) if persisted else -1
    old_gaps = g.get('feedGaps', [])
    pending = engine.pending(key)
    pending_issues = {o['issue'] for o in pending}
    if any(not n.isdigit() for n in pending_issues):
        raise ValueError('待开奖注单期号无法与源站对应，需人工核对')
    if pending_issues.intersection(existing):
        raise ValueError('已有开奖结果仍存在待开奖注单，需人工核对')
    for n, row in metadata.items():
        if n in existing and existing[n] != row['numbers']:
            raise ValueError('开奖源修改已记录的号码，需人工核对')
        if row['openTime'] > now+5:
            raise ValueError('开奖源开奖时间在未来，等待有效结果')
    wanted = [(n, row) for n, row in metadata.items() if n not in existing and
              (int(n) > high or n in pending_issues or any(lo <= int(n) <= hi for lo, hi in old_gaps))]
    if ((previous and latest < int(previous[0])) or latest < high) and not wanted:
        raise ValueError('开奖源返回较旧期号，等待最新结果')
    gaps = copy.deepcopy(old_gaps)
    if high >= 0 and latest > high+1: gaps.append([high+1, latest])
    elif high < 0 and g['issue'].isdigit() and int(g['issue']) < latest:
        gaps.append([int(g['issue']), latest])
    gaps = remove_known(merge_ranges(gaps), persisted + [int(n) for n in metadata])
    synced = bool(previous and latest == int(previous[0])+1 and 0 <= now-previous[1] <= max(10,config['interval']*3))
    opened = metadata[issue]['openTime']
    next_time = opened+g['period'] if opened else now+g['period'] if synced else 0
    next_issue = str(latest+1)
    advance = latest >= high and (not g['issue'].isdigit() or int(next_issue) >= int(g['issue']))
    new_round = advance and g['issue'] != next_issue
    # Timestamp-free duplicate responses must retain an already calibrated clock.
    clock_change = advance and (new_round or bool(opened) and g['endAt'] != next_time)
    target_issue = next_issue if advance else g['issue']
    target_time = next_time if clock_change else g['endAt']
    changed = bool(wanted or gaps != old_gaps or clock_change)
    # No full-state copies for unchanged polling responses.
    before = copy.deepcopy(engine.s) if changed else None
    saved_round = {k:g[k] for k in ('issue','endAt','closed','warned')}
    try:
        for n, row in wanted:
            # Only orders whose issue equals n can be settled by Engine.settle.
            # Late history must not close or rewind the current live round.
            g.update(issue=n, closed=True)
            engine.settle(key,n,row['numbers'],'external',target_issue,target_time)
            g['history'][0].update(sourceOpenTime=row['openTime'],sourcePublishedAt=row['publishedAt'],receivedAt=now)
        if wanted:
            g['history'].sort(key=lambda h:int(h['issue']) if h['issue'].isdigit() else -1,reverse=True)
            g.update(saved_round)
        if clock_change:
            g.update(issue=target_issue,endAt=target_time)
            if new_round: g.update(closed=False,warned=False)
            if target_time <= now+g['closeSeconds']: engine.close_round(key)
            elif new_round or not saved_round['endAt']: g['closed']=False
        if gaps: g['feedGaps']=gaps
        else: g.pop('feedGaps',None)
        if changed: engine.save()
    except Exception:
        if before is not None: engine.s=before
        raise
    if advance: engine.feed_observed[key]=(issue,now)
    status=f'读取成功 · 按序处理{len(wanted)}期 · '+('已按源站开奖时间对时' if opened and advance else '等待新一期更新对时（封盘）' if not g['endAt'] else '当前期号保持')
    missing = [o for o in engine.pending(key) if int(o['issue']) <= max(high,latest)]
    if gaps:
        count=sum(hi-lo+1 for lo,hi in gaps)
        status+=f' · 历史缺{count}期（最早{gaps[0][0]}），最新开奖继续同步'
    if missing: status+=f' · {len(missing)}笔旧单等待对应期真实结果'
    return status
