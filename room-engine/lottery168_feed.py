"""Read the public 168kj168.com Australia Lucky 8 feed (lotCode 10006)."""
import copy
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BEIJING = timezone(timedelta(hours=8))
URL = 'https://168kj168.com/GetOpenTime.ashx?action=getTime&issue=&lotCode=10006'


def validate_url(url):
    p = urlsplit(url)
    pairs = parse_qsl(p.query, keep_blank_values=True)
    q = dict(pairs)
    if (p.scheme != 'https' or p.hostname != '168kj168.com' or p.path != '/GetOpenTime.ashx'
            or p.username or p.password or p.fragment or p.port not in (None, 443)
            or len(q) != len(pairs) or q.get('action') != 'getTime' or q.get('lotCode') != '10006'
            or q.get('issue', '') != '' or set(q)-{'action','issue','lotCode'}):
        raise ValueError('168澳洲幸运8实时接口须使用本站getTime、lotCode=10006，issue留空')
    return p


def body(payload):
    if (not isinstance(payload, dict) or payload.get('errorCode') != 0
            or not isinstance(payload.get('result'), dict) or payload['result'].get('businessCode') != 0):
        raise ValueError('168开奖源未返回成功数据')
    return payload['result'].get('data')


def issue(value):
    value = str(value)
    if not re.fullmatch(r'[1-9][0-9]{0,19}', value): raise ValueError('168源站期号无效')
    return value


def timestamp(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S').replace(tzinfo=BEIJING).timestamp()
    except (ValueError, TypeError):
        raise ValueError('168源站时间须为北京时间年月日时分秒') from None


def record(raw):
    if not isinstance(raw, dict): raise ValueError('168开奖记录须为对象')
    code = raw.get('preDrawCode')
    parts = code.split(',') if isinstance(code, str) else []
    if len(parts) != 8 or any(not re.fullmatch(r'\d{1,2}', x.strip()) for x in parts):
        raise ValueError('168澳洲幸运8须有8个号码')
    numbers = [int(n) for n in parts]
    if len(set(numbers)) != 8 or any(not 1 <= n <= 20 for n in numbers):
        raise ValueError('168澳洲幸运8号码须为1至20且不重复')
    if 'balls' in raw and (raw['balls'] != numbers or any(type(n) is not int for n in raw['balls'])):
        raise ValueError('168接口号码字段互相冲突')
    return dict(issue=issue(raw.get('preDrawIssue')), numbers=numbers, openTime=timestamp(raw.get('preDrawTime')))


def latest(payload):
    raw = body(payload)
    if not isinstance(raw, dict) or str(raw.get('lotCode')) != '10006':
        raise ValueError('168接口返回的不是澳洲幸运8（10006）')
    row = record(raw)
    row.update(nextIssue=issue(raw.get('drawIssue')), nextTime=timestamp(raw.get('drawTime')))
    if int(row['nextIssue']) != int(row['issue'])+1 or not 0 < row['nextTime']-row['openTime'] <= 86400:
        raise ValueError('168源站下一期期号或时间无效')
    return row


def first_needed(engine, current):
    g = engine.game('australia8')
    pending = engine.pending('australia8')
    if any(not o['issue'].isdigit() for o in pending):
        raise ValueError('仍有本地期号待开奖注单，禁止套用网站号码')
    known = [int(h['issue']) for h in g['history'] if h['issue'].isdigit()]
    start = max(known)+1 if known else int(current['issue'])
    if g['issue'].isdigit(): start = max(start, int(g['issue'])) if known else int(g['issue'])
    if pending: start = min(start, min(int(o['issue']) for o in pending))
    return start


def fetch_payload(engine, key, config, fetch):
    validate_url(config['url'])
    payload = fetch(config)
    current = latest(payload)
    with engine.lock:
        start = first_needed(engine, current)
    rows = []
    if start < int(current['issue']):
        end = datetime.fromtimestamp(current['openTime'], BEIJING).date()
        begin = datetime.fromtimestamp(current['openTime']-(int(current['issue'])-start)*300, BEIJING).date()
        days = (end-begin).days+1
        if days > 7: raise ValueError('168澳洲8补期超过7天，请先核对历史')
        for offset in range(days):
            day = (begin+timedelta(days=offset)).isoformat()
            p = validate_url(config['url'])
            url = urlunsplit((p.scheme,p.netloc,p.path,urlencode(dict(action='getHistory',date=day,lotCode='10006')),''))
            history = body(fetch({**config,'url':url}))
            if not isinstance(history, list): raise ValueError('168历史接口须返回记录列表')
            rows.extend(history)
    return dict(latest=payload, history=rows)


def apply(engine, key, payload, config, now):
    if key != 'australia8': raise ValueError('168澳洲幸运8仅支持澳洲8房间')
    wrapped = isinstance(payload, dict) and 'latest' in payload
    current = latest(payload['latest'] if wrapped else payload)
    if current['openTime'] > now+5: raise ValueError('168源站开奖时间在未来')
    rows = {current['issue']: current}
    for raw in payload.get('history', []) if wrapped else []:
        row = record(raw)
        if int(row['issue']) > int(current['issue']): continue
        if row['issue'] in rows and any(rows[row['issue']][k] != row[k] for k in ('numbers','openTime')):
            raise ValueError('168源站同一期数据冲突')
        if row['issue'] != current['issue']: rows[row['issue']] = row
    g = engine.game(key)
    existing = {h['issue']:h['numbers'] for h in g['history']}
    numeric = [int(i) for i in existing if i.isdigit()]
    if numeric and int(current['issue']) < max(numeric): raise ValueError('168源站期号倒退')
    for n,row in rows.items():
        if n in existing and existing[n] != row['numbers']:
            raise ValueError('168源站修改已记录号码，需人工核对')
    if any(o['issue'] in existing for o in engine.pending(key)):
        raise ValueError('已有开奖结果仍存在待开奖注单，需人工核对')
    start = first_needed(engine,current)
    wanted = sorted((r for r in rows.values() if int(r['issue'])>=start and r['issue'] not in existing),key=lambda r:int(r['issue']))
    count = int(current['issue'])-start+1
    if count > 0 and (len(wanted)!=count or int(wanted[0]['issue'])!=start):
        raise ValueError(f'168历史缺期（需{start}至{current["issue"]}），保留注单等待补齐')
    if count <= 0 and current['issue'] not in existing: return '读取成功 · 等待当前期结果'
    clock_change = not wanted and g['issue']==current['nextIssue'] and g['endAt']!=current['nextTime']
    # Polling the same draw must not copy the entire account and order history.
    before = copy.deepcopy(engine.s) if wanted or clock_change else None
    try:
        for row in wanted:
            engine.settle(key,row['issue'],row['numbers'],'external',str(int(row['issue'])+1),current['nextTime'] if row['issue']==current['issue'] else 0)
            g['history'][0].update(sourceOpenTime=row['openTime'],receivedAt=now,sourceSite='168kj168.com')
        changed = bool(wanted)
        if not wanted and g['issue']==current['nextIssue'] and g['endAt']!=current['nextTime']:
            unset = not g['endAt'];g['endAt']=current['nextTime']
            if g['endAt']<=now+g['closeSeconds']: engine.close_round(key)
            elif unset:g['closed']=False
            changed=True
        if changed:engine.save()
    except Exception:
        if before is not None: engine.s=before
        raise
    return f'读取成功 · 168澳洲幸运8 · 按序处理{len(wanted)}期 · 已按北京时间对时'


def activate_pending(engine):
    """One-time cutover under the scheduler's lock, after old orders settle."""
    g=engine.game('australia8')
    cfg=g.get('pending168Feed')
    if not cfg or engine.pending('australia8'): return False
    if g['mode']!='simulation': raise ValueError('澳洲8切换前模式已变化，请人工核对')
    validate_url(cfg['url'])
    g.update(mode='external',feed=copy.deepcopy(cfg),period=300,endAt=0,closed=True,warned=False)
    g.pop('pending168Feed')
    engine.feed_observed.pop('australia8',None)
    engine.s.setdefault('adminLog',[]).append(dict(action='feed.switch',game='australia8',
        time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),message='旧模拟期结算完毕，切换168澳洲幸运8，等待源站对时'))
    return True
