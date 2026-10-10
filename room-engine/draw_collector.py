"""Independent, bounded read-only polling with safe operational diagnostics."""
import copy
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

import history_feed
import australia3_feed
from australia8_feed import FeedAccessError, FeedRateLimit


def fetch_json(config):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    headers = {'Accept': 'application/json,text/plain,*/*',
               'User-Agent': 'local-user-center/2.1 (authorized local feed client)',
               'Cache-Control': 'no-cache', 'Pragma': 'no-cache', **config['headers']}
    request = urllib.request.Request(config['url'], headers=headers, method='GET')
    with urllib.request.build_opener(NoRedirect).open(request, timeout=6) as response:
        limit, raw, deadline = 1024 * 1024, bytearray(), time.monotonic() + 8
        while len(raw) <= limit:
            part = response.read1(min(65536, limit + 1 - len(raw)))
            if not part: break
            raw.extend(part)
            if time.monotonic() > deadline: raise TimeoutError('draw read deadline')
        if len(raw) > limit: raise ValueError('开奖响应超过1MB')
        return json.loads(raw)


def retry_delay(error, failures, interval):
    if isinstance(error, FeedRateLimit): return max(60, interval)
    # A valid HTTP response with stale/missing data is polled at the normal pace.
    # Network/server failures back off; waiting for a missing result must not add lag.
    if isinstance(error, ValueError):
        return max(2, interval)
    delay = min(30, max(2, min(interval, 5)) * 2**min(failures-1, 4))
    if isinstance(error, urllib.error.HTTPError) and error.code in (429, 503):
        raw = error.headers.get('Retry-After') if error.headers else None
        try:
            wait = float(raw)
        except (ValueError, TypeError):
            try: wait = parsedate_to_datetime(raw).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError): wait = 0
        delay = max(delay, min(300, max(0, wait)))
    return delay


def sample(engine, key, config):
    started = time.monotonic()
    # Never hold the business lock during network I/O, including history backfill.
    if australia3_feed.supports(key, config):
        payload = australia3_feed.fetch_payload(engine, key, config, fetch_json)
    elif config.get('format') == '168-a8':
        import lottery168_feed
        payload = lottery168_feed.fetch_payload(engine, key, config, fetch_json)
    elif config.get('format') == 'byw-a8':
        import australia8_feed
        payload = australia8_feed.fetch_payload(engine, key, config, fetch_json)
    else:
        payload = fetch_json(config)
    fetch_ms = round((time.monotonic()-started)*1000)
    with engine.lock:
        g = engine.game(key)
        if g['mode'] != 'external' or g['paused'] or g['feed'] != config: return None
        previous_issue = g['history'][0]['issue'] if g['history'] else None
        status = engine.external_result(key, payload, config)
        now = time.time()
        metrics = dict(lastSuccessAt=now, fetchMs=fetch_ms, failures=0,
                       latestIssue=g['history'][0]['issue'] if g['history'] else None)
        if config.get('format') == 'byw-a8':
            row = australia8_feed.latest(payload['latest'])
            metrics.update(latestIssue=row['issue'], sourceOpenTime=row['openTime'],
                           sourceAgeSeconds=round(now-row['openTime'], 1),
                           overdueSeconds=round(max(0, now-row['nextTime']), 1))
        if config.get('format') == '168-a8':
            row = lottery168_feed.latest(payload['latest'])
            metrics.update(latestIssue=row['issue'], sourceOpenTime=row['openTime'],
                           sourceAgeSeconds=round(now-row['openTime'],1),
                           overdueSeconds=round(max(0,now-row['nextTime']),1))
        if config.get('format') == 'pc28-history':
            issue, row = history_feed.details(payload, config.get('schemeId', 1), config.get('lotteryId', 2))[-1]
            metrics.update(latestIssue=issue, sourceOpenTime=row['openTime'], sourcePublishedAt=row['publishedAt'])
            if row['openTime']:
                metrics['sourceAgeSeconds'] = round(now-row['openTime'], 1)
                metrics['overdueSeconds'] = round(max(0, now-row['openTime']-g['period']), 1)
            if row['publishedAt'] and row['openTime'] and row['openTime'] <= row['publishedAt'] <= now+5:
                metrics['publishDelaySeconds'] = round(row['publishedAt']-row['openTime'], 1)
                if issue != previous_issue:
                    metrics['receiptLagSeconds'] = round(max(0, now-row['publishedAt']), 1)
        if australia3_feed.supports(key, config):
            row = australia3_feed.current(payload['latest'])
            metrics.update(sourceOpenTime=row['openTime'], sourceAgeSeconds=round(now-row['openTime'], 1),
                           overdueSeconds=round(max(0, now-row['nextTime']), 1) if row['nextTime'] else 0)
        old = engine.feed_metrics.get(key, {})
        if old.get('latestIssue') == metrics['latestIssue'] and 'receiptLagSeconds' in old:
            metrics.setdefault('receiptLagSeconds', old['receiptLagSeconds'])
        engine.feed_metrics[key] = metrics
        suffix = f" · 请求{fetch_ms}毫秒 · 最新{metrics['latestIssue']}期"
        if 'publishDelaySeconds' in metrics: suffix += f" · 源站发布延迟{metrics['publishDelaySeconds']:g}秒"
        if metrics.get('overdueSeconds', 0) > 0: suffix += f" · 已到下期开奖时间，等待源站更新{metrics['overdueSeconds']:g}秒"
        engine.feed_status[key] = (status or '读取成功') + suffix + ' ' + time.strftime('%Y-%m-%d %H:%M:%S')
        # Log new draws/recovery only; no URLs, credentials, payloads or member data.
        overdue = metrics.get('overdueSeconds', 0) > 0
        if previous_issue != metrics['latestIssue'] or old.get('failures') or (overdue and not old.get('overdueSeconds')):
            print('Draw collector ' + json.dumps(dict(game=key, event='source_wait' if overdue else 'received', **metrics)), file=sys.stderr, flush=True)
        return metrics


def run_room(engine, key, stop):
    config, due, failures, denied, last_log = None, 0, 0, False, 0
    while not stop.is_set():
        with engine.lock:
            g = engine.game(key)
            current = copy.deepcopy(g['feed'])
            enabled = g['mode'] == 'external' and not g['paused']
        if current != config:
            config, due, failures, denied = current, 0, 0, False
        if not enabled:
            due = 0
            stop.wait(.25)
            continue
        if denied or time.monotonic() < due:
            stop.wait(.25)
            continue
        started = time.monotonic()
        try:
            sample(engine, key, config)
            failures = 0
            due = max(started + config['interval'], time.monotonic() + .25)
        except Exception as error:
            failures += 1
            denied = (isinstance(error, urllib.error.HTTPError) and error.code in (401, 403)) or isinstance(error, FeedAccessError)
            delay = retry_delay(error, failures, config['interval'])
            due = time.monotonic() + delay
            if denied:
                message = ('博易网密钥、IP授权或彩种权限无效，已停止重试；请核对后修改接口配置' if isinstance(error, FeedAccessError)
                           else f'开奖源拒绝访问（HTTP {error.code}），已停止重试；请取得源站授权或更换接口')
            else:
                kind = ('HTTP '+str(error.code)) if isinstance(error, urllib.error.HTTPError) else str(error) if type(error) is ValueError or isinstance(error, FeedRateLimit) else type(error).__name__
                message = f'开奖源异常：{kind} · 连续失败{failures}次 · {delay:g}秒后重试'
            with engine.lock:
                g = engine.game(key)
                if g['mode'] != 'external' or g['paused'] or g['feed'] != config: continue
                metrics = engine.feed_metrics.setdefault(key, {})
                metrics.update(lastErrorAt=time.time(), failures=failures, errorType=type(error).__name__, retrySeconds=delay)
                engine.feed_status[key] = message
            if failures == 1 or time.monotonic()-last_log >= 30:
                print('Draw collector ' + json.dumps(dict(game=key, event='error', errorType=type(error).__name__,
                    httpStatus=error.code if isinstance(error, urllib.error.HTTPError) else None,
                    reason=str(error)[:300] if type(error) is ValueError else type(error).__name__,
                    failures=failures, retrySeconds=delay)), file=sys.stderr, flush=True)
                last_log = time.monotonic()


def run(engine, stop=None):
    stop = stop or threading.Event()
    threads = [threading.Thread(target=run_room, args=(engine, key, stop), daemon=True,
                                name='draw-'+key) for key in engine.s['games']]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
