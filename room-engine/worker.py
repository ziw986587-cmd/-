"""Private shared room service; only Node exposes authenticated HTTP routes."""
import copy
import hashlib
import hmac
import json
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from engine import Engine, Handler, GAMES, stamp
from unified import migrate, mutate_member, require_member
import workbench
import simulated_users

sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
fresh = not (Path(sys.argv[1]) / 'state.json').exists()
engine = Engine(sys.argv[1], defer_wallet_migration=True)
migrate(engine, fresh)
workbench.initialize(engine)
simulated_users.initialize(engine)
from retention import prune
prune(engine, force=True)
stop = threading.Event()
allowed = {'config','close','force-open','draw','import','refund','score','review','notice','member.create','member.edit','member.delete','member.rotate','member.autobet','member.autobet.batch','legacy.settle','legacy.refund'}
allowed.update(workbench.OPERATIONS)
portal_allowed = {'bet','chat','cancel','score-request','transfer','profile'}

class AccessError(ValueError):
    pass

def scheduler():
    while not stop.wait(1):
        try:
            engine.tick()
            prune(engine)
        except Exception as exc:
            print('Room scheduler: ' + type(exc).__name__, file=sys.stderr, flush=True)

def snapshot(game):
    public = engine.public('localadmin', game)
    admin = engine.admin_state()
    # Old unresolved records must stay actionable even after many newer records.
    for field, pending_status, limit in (('orders', '待开奖', 500), ('requests', '待审核', 200)):
        recent = engine.s[field][-limit:]
        ids = {r['id'] for r in recent}
        admin[field] = (recent + [r for r in engine.s[field][:-limit] if r['status'] == pending_status and r['id'] not in ids])[::-1]
    return {**admin, **workbench.view(engine, game), 'game': game, 'round': public['round'],
            'history': public['history'], 'chat': public['chat'], 'accepting': public['accepting'],
            'serverTime': public['serverTime'], 'ledger': engine.s['ledger'][-1000:][::-1],
            'audit': engine.s.get('adminLog', [])[-300:][::-1], 'migration': engine.s.get('migration'),
            'pendingCount': len(engine.pending(game)),
            'legacyPending': [o for o in engine.s['orders'] if o['status']=='待手动结算']}

def dispatch(message):
    game, method = message.get('game', 'canada28'), message['method']
    data = message.get('data', {})
    if not isinstance(data, dict):
        raise ValueError('请求内容必须为对象')
    with engine.lock:
        engine.game(game)
        username = 'localadmin'
        portal = method.startswith('portal.')
        if portal:
            ident = data.get('_identity', {})
            u = engine.s['users'].get(ident.get('username'))
            if not u or u['role'] != 'member' or not u['enabled'] or not hmac.compare_digest(u['accessVersion'], str(ident.get('version', ''))):
                raise AccessError('专属链接已失效或账号已停用，请联系管理员')
            username = u['username']
            operation = method[7:]
            device = ident.get('deviceHash', '')
            if not isinstance(device, str) or not re.fullmatch('[a-f0-9]{64}', device):
                raise AccessError('前台已更新，请刷新网页后重新进入')
            active_device = u.get('memberDevice', {})
            matches = (active_device.get('version') == ident['version'] and
                       hmac.compare_digest(str(active_device.get('digest', '')), device))
            if operation == 'login':
                if not matches:
                    previous = copy.deepcopy(u.get('memberDevice'))
                    u['memberDevice'] = dict(digest=device, version=ident['version'], time=stamp())
                    try:
                        engine.save()
                    except Exception:
                        if previous is None: u.pop('memberDevice', None)
                        else: u['memberDevice'] = previous
                        raise
                return {'authenticated': True}
            if not matches:
                raise AccessError('账号已在其他设备登录，或登录已退出。请重新登录后使用。')
            if operation == 'logout':
                previous = u.pop('memberDevice')
                try:
                    engine.save()
                except Exception:
                    u['memberDevice'] = previous
                    raise
                return {'message': '已退出登录'}
            if operation == 'state':
                from beijing_display import present
                return present(engine.public(username, game))
            if operation not in portal_allowed:
                raise AccessError('无权执行该操作')
        else:
            if method == 'qr':
                return {'svg': workbench.qr_svg(str(data['url']))}
            if method == 'member-rebate.preview':
                from member_rebate import preview
                return preview(engine, data.get('username'))
            if method == 'force-open.preview':
                from force_open import preview
                return preview(engine, game)
            if method == 'state':
                return snapshot(game)
            if method == 'member.access':
                u = require_member(engine, data.get('username'))
                if not u['enabled']:
                    raise ValueError('账号已停用，请先启用再领取链接')
                return dict(username=u['username'], version=u['accessVersion'])
            if method == 'export':
                result = snapshot(game)
                # Exports contain every business record; no auth material or feed credentials.
                result.update(orders=copy.deepcopy(engine.s['orders']), ledger=copy.deepcopy(engine.s['ledger']),
                              requests=copy.deepcopy(engine.s['requests']),
                              ledgerOpening=copy.deepcopy(engine.s.get('ledgerOpening', {})),
                              retention=copy.deepcopy(engine.s.get('retention', {})))
                for g in result['games'].values():
                    g['feed']['url'], g['feed']['headers'] = '', {}
                result['backupNote'] = '完整恢复请在关闭软件后备份整个 data 目录。'
                return result
            if method not in allowed:
                raise ValueError('不支持的管理操作')
        request_id = data.get('requestId')
        if not isinstance(request_id, str) or not re.fullmatch('[a-fA-F0-9-]{16,64}', request_id):
            raise ValueError('缺少有效操作编号')
        dedup_key = ('member:' + username if portal else 'admin') + ':' + request_id
        fingerprint = hashlib.sha256(json.dumps([method, game, data], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        prior = engine.s.setdefault('unifiedDedup', {}).get(dedup_key)
        if prior:
            if prior['fingerprint'] != fingerprint:
                raise ValueError('操作编号已用于另一项请求，请刷新')
            return {**prior['result'], 'duplicate': True}
        # Frequent chat/score operations do not need a full snapshot of the
        # growing order history. Keep a targeted rollback while avoiding a
        # tens-of-MB deepcopy under the business lock.
        robot_score = (portal and operation == 'score-request' and
                       bool(engine.s['users'].get(username, {}).get('robot')))
        lightweight = portal and operation in ('chat', 'score-request') and not robot_score
        before = None if lightweight else copy.deepcopy(engine.s)
        light_before = None
        if lightweight:
            g = engine.game(game)
            need_ledger = operation == 'score-request' and bool(engine.s['users'].get(username, {}).get('robot'))
            light_before = dict(chat=copy.deepcopy(g['chat']),
                                requests=copy.deepcopy(engine.s['requests']),
                                ledger=copy.deepcopy(engine.s['ledger']) if need_ledger else None,
                                users=copy.deepcopy(engine.s['users']),
                                dedup=copy.deepcopy(engine.s.get('unifiedDedup', {})))
        try:
            if portal:
                if operation == 'score-request' and data.get('action') not in ('上分','下分'):
                    raise ValueError('积分操作类型无效')
                result = {'message': Handler.mutate(SimpleNamespace(engine=engine), '/api/' + operation, username, game, data)}
            else:
                if method == 'score':
                    require_member(engine, data.get('username'))
                    if data.get('action') not in ('上分', '下分'):
                        raise ValueError('积分操作类型无效')
                if method == 'review' and not isinstance(data.get('approve'), bool):
                    raise ValueError('审核结果无效')
                if method == 'import' and engine.game(game)['mode'] != 'external':
                    raise ValueError('补录仅用于外部开奖模式')
                if method == 'draw' and data.get('issue') != engine.game(game)['issue']:
                    raise ValueError('当前期号已变化，请刷新后核对再开奖')
                result = workbench.mutate(engine, method, game, data) if method in workbench.OPERATIONS else mutate_member(engine, method, game, data)
                if result is None:
                    result = {'message': Handler.mutate(SimpleNamespace(engine=engine), '/api/admin/' + method, username, game, data)}
                engine.s.setdefault('adminLog', []).append(dict(time=stamp(), game=game, action=method,
                    message=result['message'], username=data.get('username'), requestId=request_id))
            engine.s['unifiedDedup'][dedup_key] = dict(fingerprint=fingerprint, result=result, time=stamp())
            engine.save_light() if lightweight else engine.save()
            return result
        except Exception:
            if before is not None:
                engine.s = before
            elif light_before is not None:
                engine.game(game)['chat'] = light_before['chat']
                engine.s['requests'] = light_before['requests']
                if light_before['ledger'] is not None:
                    engine.s['ledger'] = light_before['ledger']
                engine.s['users'] = light_before['users']
                engine.s['unifiedDedup'] = light_before['dedup']
            raise

threading.Thread(target=scheduler, daemon=True).start()
threading.Thread(target=engine.collector, daemon=True).start()
print(json.dumps({'ready': True}), flush=True)
try:
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            result = dispatch(request)
            response = {'id': request['id'], 'ok': True, 'result': result}
        except Exception as exc:
            response = {'id': request.get('id') if isinstance(request, dict) else None,
                        'ok': False, 'status': 403 if isinstance(exc, AccessError) else 400,
                        'message': str(exc) if isinstance(exc, (ValueError, KeyError, TypeError)) else '房间服务内部错误'}
        print(json.dumps(response, ensure_ascii=False, allow_nan=False), flush=True)
finally:
    stop.set()
