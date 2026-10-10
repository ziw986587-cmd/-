"""One-time migration and shared member operations. No alternate wallet store."""
import copy
import json
import re
import secrets
import shutil
from pathlib import Path
from engine import GAMES, money, stamp
import shared_wallet
import avatar_library


def member_record(username, nickname):
    return dict(username=username, nickname=nickname, role='member', avatar='👤',
                enabled=True, remark='', createdAt=stamp(), accessVersion=secrets.token_hex(16),
                robot=False, auto=False, autoBet={}, autoBetStatus={}, balance=0,
                walletVersion=1, wallets={g: 0 for g in GAMES})


def migrate(engine, fresh):
    s = engine.s
    if s.get('unificationVersion') == 1:
        shared_wallet.initialize(engine)
        return
    backup = engine.path.parent.parent / 'backups' / 'before-unified-portal'
    backup.mkdir(parents=True, exist_ok=True)
    for source in (engine.path, engine.path.parent.parent / 'database.json'):
        target = backup / source.name
        if source.exists() and not target.exists():
            shutil.copy2(source, target)
    if fresh:
        s['users'] = {k: v for k, v in s['users'].items() if v['role'] == 'admin'}
        for u in s['users'].values():
            shared_wallet.set_balance(u, 0, GAMES)
        # A freshly constructed standalone Engine may have sample opening entries.
        s['ledger'] = []
    for username, u in s['users'].items():
        u.setdefault('accessVersion', secrets.token_hex(16))
        u.setdefault('remark', '')
        u.setdefault('createdAt', stamp())
    # Initialize before importing legacy members; all subsequent credits are shared.
    shared_wallet.initialize(engine, save=False)
    legacy_file = engine.path.parent.parent / 'database.json'
    legacy = json.loads(legacy_file.read_text(encoding='utf-8-sig')) if legacy_file.exists() else {}
    mapping = {}
    for m in legacy.get('members', []):
        base = m.get('login') or ('legacy_' + re.sub(r'[^A-Za-z0-9_]', '', m['id']))
        name = base
        i = 1
        while name in s['users']:
            name = base + '_' + str(i)
            i += 1
        u = member_record(name, m['name'][:20])
        u.update(enabled=bool(m.get('approved', True)), remark=m.get('remark', ''), legacyId=m['id'])
        s['users'][name] = u
        mapping[m['id']] = name
        if m['balance']:
            engine.credit(name, 'canada28', m['balance'], '旧工作台余额迁入', m['id'])
    for o in legacy.get('orders', []):
        if o['member'] not in mapping:
            continue
        status = {'待结算': '待手动结算', '已撤销': '已退单', '已结算': '已结算'}.get(o['state'], o['state'])
        s['orders'].append(dict(id='legacy-' + o['id'], batch='legacy-' + o['id'],
            username=mapping[o['member']], game='canada28', issue='旧-' + str(o['term']),
            selection=o['content'], ball=8, amount=o['amount'], status=status,
            profit=(o['payout'] - o['amount']) if status == '已结算' else 0 if status == '已退单' else None,
            payout=o['payout'], rate=0, time=o['createdAt'], legacy=True))
    for r in legacy.get('requests', []):
        if r['member'] in mapping:
            s['requests'].append(dict(id='legacy-' + r['id'], username=mapping[r['member']], game='canada28',
                action=r['direction'], amount=r['amount'], status={'待处理':'待审核','已同意':'已通过','已取消':'已拒绝'}[r['state']], time=r['createdAt']))
    for g in s['games'].values():
        g.setdefault('minBet', 1)
        g.setdefault('maxBet', 100000000)
        g.setdefault('userLimit', None)
    s['migration'] = dict(time=stamp(), members=len(mapping), mapping=mapping,
                          note='旧工作台余额一次迁入共享积分；旧原始记录只读保留。')
    s['unificationVersion'] = 1
    engine.save()


def require_member(engine, username):
    u = engine.s['users'].get(username)
    if not u or u['role'] != 'member' or u.get('deleted'):
        raise ValueError('会员不存在')
    return u


def mutate_member(engine, operation, game, data):
    if operation == 'member.autobet':
        from simulated_users import configure
        return configure(engine, game, data)
    if operation == 'member.autobet.batch':
        from simulated_users import configure_batch
        return configure_batch(engine, data)
    if operation == 'member.create':
        username = str(data.get('username', '')).strip()
        nickname = str(data.get('nickname', '')).strip()
        if not re.fullmatch('[A-Za-z0-9_]{3,32}', username):
            raise ValueError('账号须为3至32位字母、数字或下划线')
        if not 1 <= len(nickname) <= 20:
            raise ValueError('昵称须为1至20字')
        if username in engine.s['users']:
            raise ValueError('账号已存在，请使用其他账号')
        rate = float(data.get('rebate', 0.8))
        if not 0 <= rate <= 100:
            raise ValueError('返水参数须为0至100')
        u = member_record(username, nickname)
        u['rebate'] = rate
        u['avatar'] = avatar_library.validate(data.get('avatar', avatar_library.DEFAULT))
        u['remark'] = str(data.get('remark', ''))[:200]
        engine.s['users'][username] = u
        if str(data.get('amount', '0')) not in ('0', '0.0', '0.00', ''):
            engine.credit(username, game, money(data['amount']), '创建会员初始积分', username)
        return {'message': '会员已创建，可领取专属链接', 'username': username}
    if operation == 'member.delete':
        u = require_member(engine, data.get('username'))
        from simulated_users import disable
        disable(u, 'user-disabled')
        u.update(deleted=True, deletedAt=stamp(), enabled=False, accessVersion=secrets.token_hex(16))
        return {'message': '用户已删除，历史记录和余额保留供对账', 'username': u['username']}
    if operation in ('member.edit', 'member.rotate'):
        u = require_member(engine, data.get('username'))
        if operation == 'member.rotate':
            u['accessVersion'] = secrets.token_hex(16)
            return {'message': '专属链接已更新，旧链接已失效', 'username': u['username']}
        if 'avatar' in data:
            u['avatar'] = avatar_library.validate(data['avatar'])
        if 'nickname' in data:
            name = str(data['nickname']).strip()
            if not 1 <= len(name) <= 20:
                raise ValueError('昵称须为1至20字')
            u['nickname'] = name
        if 'remark' in data:
            u['remark'] = str(data['remark'])[:200]
        for key in ('robot', 'auto'):
            if key in data:
                if not isinstance(data[key], bool):
                    raise ValueError('会员标记无效')
                u[key] = data[key]
        if 'rebate' in data:
            value = float(data['rebate'])
            if not 0 <= value <= 100:
                raise ValueError('返水参数须为0至100')
            u['rebate'] = value
        if 'enabled' in data:
            if not isinstance(data['enabled'], bool):
                raise ValueError('账号状态无效')
            if u['enabled'] != data['enabled']:
                u['accessVersion'] = secrets.token_hex(16)
            u['enabled'] = data['enabled']
        if data.get('robot') is False or data.get('enabled') is False or data.get('auto') is False:
            from simulated_users import disable
            disable(u, 'user-disabled' if not u['enabled'] else 'not-simulated' if not u.get('robot') else 'disabled')
        # The legacy flag is a display summary, never permission to start a bot.
        u['auto'] = any(c.get('version') == 1 and c.get('enabled') is True
                        for c in u.get('autoBet', {}).values() if isinstance(c, dict))
        return {'message': '会员资料已保存'}
    if operation in ('legacy.settle', 'legacy.refund'):
        o = next((o for o in engine.s['orders'] if o['id'] == data.get('id')), None)
        if not o or not o.get('legacy') or o['status'] != '待手动结算':
            raise ValueError('只能处理迁入的待手动结算订单')
        payout = o['amount'] if operation == 'legacy.refund' else 0 if str(data.get('payout')) in ('0','0.00') else money(data.get('payout'))
        if payout:
            engine.credit(o['username'], o['game'], payout, '旧单退款' if operation == 'legacy.refund' else '旧单手动结算', o['id'])
        o.update(status='已退单' if operation == 'legacy.refund' else '已结算', payout=payout,
                 profit=0 if operation == 'legacy.refund' else payout-o['amount'], completedAt=stamp())
        return {'message': '旧订单已处理，积分已同步'}
    return None
