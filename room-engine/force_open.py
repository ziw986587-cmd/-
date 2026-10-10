"""Explicit administrator recovery for the Canada 28 history feed."""
import json
import time
import urllib.request
import history_feed
from engine import display_money, stamp


def read_latest(config):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    request = urllib.request.Request(config['url'], headers={**config['headers'],
        'Accept': 'application/json,text/plain,*/*',
        'User-Agent': 'local-user-center/2.1 (authorized local feed client)'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=6) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('开奖响应超过1MB')
        return history_feed.records(json.loads(raw), config.get('schemeId', 1),
                                    config.get('lotteryId', 2))
    except Exception as exc:
        raise ValueError('无法核实开奖源，未开盘、未退单，请稍后重试或补录结果') from exc


def preview(engine, key):
    g = engine.game(key)
    if key != 'canada28' or g['mode'] != 'external' or g['feed'].get('format') != 'pc28-history':
        raise ValueError('强制开盘仅支持加拿大28历史开奖接口模式')
    latest, _ = read_latest(g['feed'])[-1]
    pending = engine.pending(key)
    return dict(issue=g['issue'], latestIssue=latest, nextIssue=str(int(latest)+1),
                pendingIds=sorted(o['id'] for o in pending), count=len(pending),
                amount=sum(o['amount'] for o in pending), period=g['period'])


def run(engine, key, data):
    # Worker holds engine.lock and rolls back all persistent changes on failure.
    g = engine.game(key)
    if key != 'canada28' or g['mode'] != 'external' or g['feed'].get('format') != 'pc28-history':
        raise ValueError('强制开盘仅支持加拿大28历史开奖接口模式')
    if engine.accepting(key):
        raise ValueError('当前已经开盘，无需强制开盘')
    pending = engine.pending(key)
    if (data.get('issue') != g['issue'] or
            data.get('pendingIds') != sorted(o['id'] for o in pending)):
        raise ValueError('期号或待开奖注单已变化，请刷新后重新确认')
    if data.get('confirmed') is not True or (pending and data.get('refundConfirmed') is not True):
        raise ValueError('请确认强制开盘及待开奖注单退还明细')
    rows = read_latest(g['feed'])
    latest, numbers = rows[-1]
    if data.get('latestIssue') != latest:
        raise ValueError('开奖源期号已变化，请重新点击强制开盘并确认新期号')
    existing = {h['issue']: h['numbers'] for h in g['history']}
    for issue, result in rows:
        if issue in existing and existing[issue] != result:
            raise ValueError('开奖源与已有号码冲突，未开盘、未退单')
    numeric_history = [int(i) for i in existing if i.isdigit()]
    if ((numeric_history and int(latest) < max(numeric_history)) or
            (g['issue'].isdigit() and int(latest) + 1 < int(g['issue']))):
        raise ValueError('开奖源期号落后，未开盘、未退单')
    next_issue = str(int(latest) + 1)
    now = time.time()
    amount = sum(o['amount'] for o in pending)
    old_issue = g['issue']
    for order in pending:
        engine.credit(order['username'], key, order['amount'], '强制开盘退还本金',
                      order['id'], source=order.get('source'), simulated=order.get('simulated'))
        order.update(status='已退单', profit=0, payout=order['amount'], completedAt=stamp())
    if pending:
        engine.bot(key, f'管理员强制开盘：已退还待开奖注单{len(pending)}笔，本金{display_money(amount)}积分。', 'REFUND', template='force_refund', variables={'笔数':str(len(pending)), '金额':display_money(amount)})
    # Only real source numbers may enter history. Existing results are not settled twice.
    engine.settle(key, latest, numbers, 'external', next_issue, now + g['period'])
    g.update(issue=next_issue, endAt=now + g['period'], closed=False, paused=False, warned=False)
    engine.feed_observed[key] = (latest, now)
    engine.feed_status[key] = '管理员强制开盘：倒计时为人工估算，等待开奖源下一期更新校准'
    engine.bot(key, f'{next_issue}期开始攻击\n管理员强制开盘，倒计时为人工估算，以开奖源实际结果为准。', template='force_open')
    return (f'已从{old_issue}期恢复至{next_issue}期，强制开盘{g["period"]}秒；'
            f'退还{len(pending)}笔待开奖注单，本金{display_money(amount)}积分。倒计时为人工估算。')
