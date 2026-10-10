"""Administrator-only rebates over settled orders; amounts are integer cents."""
import hashlib
import json
import secrets
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from engine import GAMES, stamp, display_money
from turnover import effective_turnover, RULE_VERSION
from unified import require_member


def eligible(engine, username):
    return [o for o in engine.s['orders'] if o['username'] == username
            and o['game'] in GAMES and not o.get('legacy')
            and o['status'] in ('中奖', '未中', '和局') and not o.get('rebateBatch')]


def preview(engine, username):
    user = require_member(engine, username)
    try:
        rate = Decimal(str(user.get('rebate', 0)))
        if not rate.is_finite() or not 0 <= rate <= 100:
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise ValueError('会员返水比例无效，请保存0至100之间的百分比')
    orders = eligible(engine, username)
    totals = {key: dict(count=0, turnover=0) for key in GAMES}
    for order in orders:
        if type(order['amount']) is not int or order['amount'] <= 0:
            raise ValueError('存在异常注单金额，请核对后回水')
        totals[order['game']]['count'] += 1
        totals[order['game']]['turnover'] += effective_turnover(order)
    turnover = sum(row['turnover'] for row in totals.values())
    amount = int((Decimal(turnover) * rate / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if max(turnover, amount, user['balance'] + amount) > 9007199254740991:
        raise ValueError('回水金额超过安全计算范围')
    # Bind the confirmation to this account, saved rate and exact settled orders.
    fingerprint = hashlib.sha256(json.dumps([RULE_VERSION, username, str(rate),
        sorted((o['id'], o['game'], o['amount'], o['status'], o.get('selection'), o.get('profit'), effective_turnover(o)) for o in orders)],
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return dict(username=username, nickname=user['nickname'], rate=str(rate),
                count=len(orders), turnover=turnover, amount=amount,
                rooms=totals, fingerprint=fingerprint, scope='all')


def pay(engine, game, data):
    # The worker serializes and atomically saves this together with request deduplication.
    engine.game(game)
    plan = preview(engine, data.get('username'))
    if data.get('confirmed') is not True:
        raise ValueError('请先核对本次回水明细并确认发放')
    if data.get('fingerprint') != plan['fingerprint']:
        raise ValueError('返水比例或未回水注单已变化，请重新打开一键回水核对')
    if Decimal(plan['rate']) <= 0:
        raise ValueError('请先设置该会员返水比例并点击“修改”保存')
    if not plan['count']:
        raise ValueError('该会员没有已结算且尚未回水的注单')
    if plan['amount'] <= 0:
        raise ValueError('本次回水不足0.01积分，保留流水待累计后发放')
    orders = eligible(engine, plan['username'])
    batch = secrets.token_hex(16)
    reason = f"三房间一键回水：流水{display_money(plan['turnover'])}，比例{plan['rate']}%"
    engine.credit(plan['username'], game, plan['amount'], reason, batch, source='rebate')
    engine.s['ledger'][-1].update(rebateScope='all', rebateRate=plan['rate'],
                                  rebateTurnover=plan['turnover'], rebateOrderCount=plan['count'])
    for order in orders:
        order['rebateBatch'] = batch
    engine.s.setdefault('rebateBatches', []).append(dict(id=batch, time=stamp(),
        username=plan['username'], scope='all', rate=plan['rate'], amount=plan['amount'],
        turnover=plan['turnover'], rooms=plan['rooms'], orderIds=[o['id'] for o in orders]))
    return dict(message=f"三房间回水已入账：{display_money(plan['amount'])}积分，共{plan['count']}笔注单",
                batchId=batch, amount=plan['amount'], count=plan['count'])
