"""Byw lottery 114 adapter. Activation requires an authorized API token."""
import copy
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BEIJING = timezone(timedelta(hours=8))


class FeedAccessError(ValueError):
    pass


class FeedRateLimit(ValueError):
    pass


def fields(value):
    if not isinstance(value, dict): raise ValueError('澳洲8开奖接口须返回JSON对象')
    result = {}
    for key, item in value.items():
        key = key.lower()
        if key in result and result[key] != item: raise ValueError('澳洲8接口字段存在大小写冲突')
        result[key] = item
    return result


def data(payload):
    obj = fields(payload)
    message = str(obj.get('message', ''))
    if '试用接口' in message or '对接测试' in message:
        raise FeedAccessError('源站明确标识为试用随机号码，仅供对接测试，禁止用于正式结算')
    source_type = str(obj.get('type', obj.get('t', '')))
    if source_type.isdigit() and source_type != '114':
        raise ValueError('博易网返回的彩种不是114澳洲幸运8')
    if obj.get('error') or ('code' in obj and str(obj['code']) not in ('0','200')):
        code = str(obj.get('code',''))
        if code in ('1001','1002','1003','1004','1005','3004'):
            raise FeedAccessError('博易网密钥、IP授权或彩种权限无效，请核对账户配置')
        if code in ('3003','429'):
            raise FeedRateLimit('博易网调用频率或每日额度已超限')
        raise ValueError('博易网暂未提供有效开奖数据')
    rows = obj.get('data')
    if not isinstance(rows, list) or not rows: raise ValueError('澳洲8接口没有开奖记录')
    return rows


def issue(value):
    value = str(value)
    if not re.fullmatch(r'[1-9][0-9]{0,19}', value):
        raise ValueError('澳洲8源站期号无效')
    return value


def timestamp(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S').replace(tzinfo=BEIJING).timestamp()
    except (TypeError, ValueError):
        raise ValueError('澳洲8源站时间须为北京时间年月日时分秒') from None


def record(row):
    if not isinstance(row, dict): raise ValueError('澳洲8开奖记录须为对象')
    row = fields(row)
    numbers = row.get('opencode')
    if not isinstance(numbers, str): raise ValueError('澳洲8源站开奖号码无效')
    parts = numbers.split(',')
    if len(parts) != 8 or any(not re.fullmatch(r'\d{1,2}', n.strip()) for n in parts):
        raise ValueError('澳洲8源站须返回8个号码')
    numbers = [int(n) for n in parts]
    if len(set(numbers)) != 8 or any(n < 1 or n > 20 for n in numbers):
        raise ValueError('澳洲8源站号码须为1至20且不重复')
    return dict(issue=issue(row.get('expect')), numbers=numbers,
                openTime=timestamp(row.get('opentime')))


def latest(payload):
    rows = records(payload)
    result = dict(rows[-1])
    obj = fields(payload)
    # This feed's real period convention must be verified before activation.
    # Do not guess a date-prefixed period rollover using plain integer addition.
    nxt = obj.get('nextexpect', obj.get('nextissue'))
    if nxt is None:
        if len(result['issue']) > 10:
            raise ValueError('源站使用日期式期号，须核对下一期期号规则后接入')
        nxt = str(int(result['issue'])+1)
    result.update(nextIssue=issue(nxt), nextTime=timestamp(obj.get('nexttime')))
    if int(result['nextIssue']) != int(result['issue'])+1:
        raise ValueError('澳洲8源站下一期期号不连续')
    if not 0 < result['nextTime']-result['openTime'] <= 86400:
        raise ValueError('澳洲8源站下一期开奖时间无效')
    return result


def records(payload):
    found = {}
    for raw in data(payload):
        row = record(raw)
        if row['issue'] in found and row != found[row['issue']]:
            raise ValueError('澳洲8源站同一期数据冲突')
        found[row['issue']] = row
    return sorted(found.values(), key=lambda r:int(r['issue']))


def validate_url(url):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if (parts.scheme != 'https' or parts.hostname != 'api.byw.bet' or parts.path != '/api'
            or parts.username or parts.password or parts.fragment or parts.port not in (None,443)):
        raise ValueError('博易网接口地址须为https://api.byw.bet/api')
    if query.get('t') != '114' or query.get('p') != 'json' or query.get('nexttime') != '1':
        raise ValueError('博易网澳洲8地址须包含t=114、p=json及nexttime=1')
    if not query.get('token') or query['token'].upper().startswith(('YOUR_','TOKEN_')):
        raise ValueError('请填写自己的博易网API密钥')
    if 'date' in query or not query.get('limit','20').isdigit() or not 1 <= int(query.get('limit','20')) <= 20:
        raise ValueError('实时接口不可固定date，limit须为1至20')
    return parts, query


def history_url(url, day):
    parts, query = validate_url(url)
    query.update(date=day.replace('-',''), limit='20')
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


def first_needed(engine, current):
    g = engine.game('australia8')
    persisted = [int(h['issue']) for h in g['history'] if h['issue'].isdigit()]
    pending = engine.pending('australia8')
    if any(not o['issue'].isdigit() for o in pending):
        raise ValueError('存在本地期号待开奖注单，须先处理后再接入真实开奖源')
    start = max(persisted)+1 if persisted else int(current['issue'])
    if g['issue'].isdigit(): start = max(start, int(g['issue'])) if persisted else int(g['issue'])
    if pending: start = min(start, min(int(o['issue']) for o in pending))
    return start


def fetch_payload(engine, key, config, fetch):
    payload = fetch(config)
    current = latest(payload)
    known = records(payload)
    with engine.lock:
        start = first_needed(engine, current)
    histories = list(data(payload))
    if start < int(known[0]['issue']):
        # Five-minute rounds determine how far back to request the site's date API.
        end = datetime.fromtimestamp(current['openTime'], BEIJING).date()
        begin = datetime.fromtimestamp(current['openTime']-(int(current['issue'])-start)*300, BEIJING).date()
        days = (end-begin).days+1
        if days > 7: raise ValueError('澳洲8断线超过7天，需核对历史后补录')
        for offset in range(days):
            day = (begin+timedelta(days=offset)).isoformat()
            body = fetch({**config, 'url':history_url(config['url'], day)})
            histories.extend(data(body))
    return dict(latest=payload, history=histories)


def apply(engine, key, payload, config, now):
    if key != 'australia8': raise ValueError('澳洲幸运8接口仅用于澳洲8房间')
    wrapped = isinstance(payload, dict) and 'latest' in payload
    current = latest(payload['latest'] if wrapped else payload)
    if current['openTime'] > now+5: raise ValueError('澳洲8源站开奖时间在未来')
    rows = {current['issue']:current}
    for raw in payload.get('history', []) if wrapped else []:
        row = record(raw)
        if int(row['issue']) > int(current['issue']): continue
        if row['issue'] in rows and row['numbers'] != rows[row['issue']]['numbers']:
            raise ValueError('澳洲8源站同一期号码冲突')
        if row['issue'] != current['issue']: rows[row['issue']] = row
    g = engine.game(key)
    existing = {h['issue']:h['numbers'] for h in g['history']}
    numeric = [int(i) for i in existing if i.isdigit()]
    if numeric and int(current['issue']) < max(numeric): raise ValueError('澳洲8源站期号倒退')
    for number, row in rows.items():
        if number in existing and existing[number] != row['numbers']:
            raise ValueError('澳洲8源站修改已记录号码，需人工核对')
    if any(o['issue'] in existing for o in engine.pending(key)):
        raise ValueError('已有开奖结果仍存在待开奖注单，需人工核对')
    start = first_needed(engine, current)
    wanted = sorted((r for r in rows.values() if int(r['issue']) >= start and r['issue'] not in existing), key=lambda r:int(r['issue']))
    count = int(current['issue'])-start+1
    if count > 0 and (len(wanted) != count or int(wanted[0]['issue']) != start):
        raise ValueError(f'澳洲8历史缺期（需{start}至{current["issue"]}），保留注单等待补齐')
    if count <= 0 and current['issue'] not in existing: return '读取成功 · 等待当前期结果'
    before = copy.deepcopy(engine.s)
    try:
        for row in wanted:
            engine.settle(key, row['issue'], row['numbers'], 'external', str(int(row['issue'])+1),
                          current['nextTime'] if row['issue'] == current['issue'] else 0)
            g['history'][0].update(sourceOpenTime=row['openTime'], receivedAt=now)
        changed = bool(wanted)
        if not wanted and g['issue'] == current['nextIssue'] and g['endAt'] != current['nextTime']:
            unset = not g['endAt']
            g['endAt'] = current['nextTime']
            if g['endAt'] <= now+g['closeSeconds']: engine.close_round(key)
            elif unset: g['closed'] = False
            changed = True
        if changed: engine.save()
    except Exception:
        engine.s = before
        raise
    return f'读取成功 · 博易网澳洲幸运8（114） · 按序处理{len(wanted)}期 · 已按北京时间对时'
