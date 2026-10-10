"""Compact workbench operations over the same room users, orders and ledger."""
import json
import shutil
import secrets
from datetime import datetime, timezone
import robot_messages
import shared_wallet
from engine import GAMES, money, stamp
from turnover import effective_turnover
from unified import require_member
from qrencoder import QRCode, QRErrorCorrectLevel

DEFAULTS = dict(reportConnected=False, autoReport=False, failCancel=False, errorCancel=False,
                hideSuccess=True, showBegin=True, audio=1, delay=120, noExt=30, rebate=50, statFrom=0)
OPERATIONS = {'workbench.save', 'workbench.order', 'workbench.request', 'workbench.cancel',
              'workbench.report', 'workbench.stats.reset', 'workbench.rebate',
              'workbench.data.clear', 'workbench.balances.clear', 'robot.messages.save'}


def _backup_before_clear(engine, label):
    """Keep a recoverable state snapshot before a destructive admin action."""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = engine.path.parent.parent / 'backups' / f'{label}-{stamp}-{secrets.token_hex(3)}'
    target.mkdir(parents=True, exist_ok=False)
    shutil.copy2(engine.path, target / 'state.json')
    if engine.overlay_path.exists():
        shutil.copy2(engine.overlay_path, target / 'state.overlay.json')
    return str(target)


def initialize(engine):
    if 'workbench' in engine.s:
        return
    legacy_path = engine.path.parent.parent / 'database.json'
    legacy = json.loads(legacy_path.read_text(encoding='utf-8-sig')) if legacy_path.exists() else {}
    engine.s['workbench'] = {g: {**DEFAULTS} for g in GAMES}
    for u in engine.s['users'].values():
        old = next((m for m in legacy.get('members', []) if m['id'] == u.get('legacyId')), {})
        u.update(robot=bool(old.get('robot')), auto=bool(old.get('auto')), rebate=old.get('rebate', 0))
    engine.save()


def view(engine, game):
    prefs = engine.s['workbench'][game]
    by_room = {key: {name: dict(turnover=0, effectiveTurnover=0, profit=0) for name in engine.s['users']} for key in GAMES}
    for index, o in enumerate(engine.s['orders']):
        key = o['game']
        if key in by_room and index >= engine.s['workbench'][key]['statFrom'] and o['status'] != '已退单':
            by_room[key][o['username']]['turnover'] += o['amount']
            by_room[key][o['username']]['effectiveTurnover'] += effective_turnover(o)
            by_room[key][o['username']]['profit'] += o['profit'] or 0
    return dict(robotConfig=robot_messages.config(engine, game), workbench=dict(prefs), memberStats=by_room[game], memberStatsByRoom=by_room)


def qr_svg(value):
    qr = QRCode(None, QRErrorCorrectLevel.M)
    qr.addData(value)
    qr.make()
    n = qr.getModuleCount()
    path = ' '.join(f'M{x+4},{y+4}h1v1h-1z' for y in range(n) for x in range(n) if qr.isDark(y, x))
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n+8} {n+8}" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="white"/><path d="{path}" fill="black"/></svg>'


def mutate(engine, method, game, data):
    prefs = engine.s['workbench'][game]
    if method == 'robot.messages.save':
        return robot_messages.save(engine, game, data)
    if method == 'workbench.rebate':
        from member_rebate import pay
        return pay(engine, game, data)
    if method == 'workbench.save':
        for key in ('reportConnected','autoReport','failCancel','errorCancel','hideSuccess','showBegin'):
            if key in data:
                if not isinstance(data[key], bool):
                    raise ValueError('开关值无效')
                prefs[key] = data[key]
        for key, low, high in (('audio',1,3),('delay',0,3600),('noExt',0,3600),('rebate',0,100)):
            if key in data:
                value = float(data[key])
                if not low <= value <= high:
                    raise ValueError('设置超出范围')
                prefs[key] = value
        return {'message': '工作台设置已保存'}
    if method == 'workbench.stats.reset':
        if engine.pending(game):
            raise ValueError('请先处理本房间待开奖订单')
        prefs['statFrom'] = len(engine.s['orders'])
        return {'message': '本页流水和盈亏统计已归零，账本及历史订单保留'}
    if method == 'workbench.data.clear':
        if any(engine.pending(key) for key in GAMES):
            raise ValueError('请先处理三个房间的待开奖订单，再清除数据')
        if any(r.get('status') == '待审核' for r in engine.s['requests']):
            raise ValueError('请先处理待审核的上下分申请，再清除数据')
        backup = _backup_before_clear(engine, 'before-data-clear')
        engine.s['orders'] = []
        engine.s['requests'] = []
        engine.s['rebateBatches'] = []
        engine.s['dedup'] = {}
        engine.s['unifiedDedup'] = {}
        for key in GAMES:
            room = engine.game(key)
            room['history'] = []
            room['chat'] = []
            engine.s['workbench'][key]['statFrom'] = 0
        return {'message': '三间房历史业务数据已清除，会员余分和账本保留，执行前已自动备份'}
    if method == 'workbench.balances.clear':
        if any(engine.pending(key) for key in GAMES):
            raise ValueError('请先处理三个房间的待开奖订单，再清除余分')
        if any(r.get('status') == '待审核' for r in engine.s['requests']):
            raise ValueError('请先处理待审核的上下分申请，再清除余分')
        backup = _backup_before_clear(engine, 'before-balances-clear')
        cleared = 0
        for username, user in engine.s['users'].items():
            if user.get('role') != 'member' or user.get('deleted'):
                continue
            old = user.get('balance', 0)
            if old == 0:
                continue
            shared_wallet.set_balance(user, 0, GAMES)
            engine.s['ledger'].append({'id': secrets.token_hex(8), 'username': username,
                'game': 'all', 'delta': -old, 'balance': 0, 'walletScope': 'shared',
                'reason': '管理员一键清除余分', 'ref': data.get('requestId'), 'time': stamp(),
                'source': 'management', 'simulated': bool(user.get('robot'))})
            cleared += 1
        return {'message': f'已清除 {cleared} 位会员余分，账本审计记录已保留，执行前已自动备份'}
    if method in ('workbench.order', 'workbench.request'):
        u = require_member(engine, data.get('username'))
        if not u['enabled']:
            raise ValueError('用户已停用')
        if method == 'workbench.order':
            result = engine.submit(u['username'], game, str(data.get('text', '')), data.get('ball', 8), source='admin')
        else:
            result = engine.request_score(u['username'], game, data.get('action'), data.get('amount'))
        return {'message': result}
    if method in ('workbench.cancel', 'workbench.report'):
        o = next((o for o in engine.s['orders'] if o['id'] == data.get('id') and o['game'] == game), None)
        if not o or o['status'] != '待开奖':
            raise ValueError('订单不存在或已经处理')
        if method == 'workbench.cancel':
            return {'message': engine.cancel(o['username'], game, o['id'])}
        if not prefs['reportConnected']:
            raise ValueError('请先连接本地模拟通道')
        if not isinstance(data.get('fail'), bool):
            raise ValueError('模拟结果无效')
        if data['fail'] and prefs['failCancel'] and engine.closing_window(game):
            raise ValueError('澳洲8离封盘60秒以内禁止取消注单')
        o['report'] = '模拟失败' if data['fail'] else '模拟成功'
        if data['fail'] and prefs['failCancel']:
            engine.credit(o['username'], game, o['amount'], '模拟失败撤单', o['id'], source=o.get('source'), simulated=o.get('simulated'))
            o.update(status='已退单', profit=0, payout=o['amount'], completedAt=stamp())
        return {'message': '本地模拟状态已更新'}
    return None
