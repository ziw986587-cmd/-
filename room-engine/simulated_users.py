"""Explicitly configured virtual-score users, driven by the room scheduler."""
import copy
import re
import secrets
import time

from engine import GAMES, bet_money, parse_bets, stamp


MESSAGES = {
    'unconfigured': '尚未设置自动下注',
    'disabled': '自动下注已关闭',
    'user-disabled': '账号已停用',
    'not-simulated': '仅模拟用户（托）可以自动下注',
    'room-paused': '房间已暂停，等待恢复',
    'closed': '已封盘或等待开奖源，暂不下注',
    'round-limit': '本期自动下注次数已达上限',
    'insufficient-balance': '积分不足，等待下次自动上分',
    'invalid-limits': '配置金额与房间限注不符，请重新设置',
    'waiting': '已启用，等待下次自动下注',
    'running': '自动下注成功，等待下次执行',
    'error': '自动下注失败',
}


def initialize(engine):
    """Legacy `auto` flags never authorize spending; only versioned configs do."""
    changed = engine.s.get('simulatedUsersVersion') != 1
    for user in engine.s['users'].values():
        for field in ('autoBet', 'autoBetStatus'):
            if not isinstance(user.get(field), dict):
                user[field] = {}
                changed = True
        for game, config in user['autoBet'].items():
            if game not in GAMES or not isinstance(config, dict) or config.get('version') != 1:
                continue
            status = _status(user, game)
            issue = engine.game(game)['issue']
            count = max(status.get('count', 0) if status.get('issue') == issue else 0,
                        _round_count(engine, user['username'], game, issue))
            if status.get('issue') != issue or status.get('count') != count:
                status.update(issue=issue, count=count,
                              nextAt=time.time() + config['intervalSeconds'] if config.get('enabled') else None)
                changed = True
        active = any(c.get('version') == 1 and c.get('enabled') is True
                     for c in user['autoBet'].values() if isinstance(c, dict))
        if user.get('auto') is not active:
            user['auto'] = active
            changed = True
    engine.s['simulatedUsersVersion'] = 1
    if changed:
        engine.save()


def _integer(value, name, low, high):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value)):
        raise ValueError(f'{name}须为整数')
    result = int(value)
    if not low <= result <= high:
        raise ValueError(f'{name}须为{low}至{high}')
    return result


def _status(user, game):
    return user.setdefault('autoBetStatus', {}).setdefault(game, {
        'issue': None, 'count': 0, 'nextAt': None, 'lastAt': None,
        'lastError': '', 'state': 'unconfigured', 'message': MESSAGES['unconfigured']})


def _set_state(status, state, error=''):
    message = (MESSAGES[state] + '：' + error) if error else MESSAGES[state]
    changed = status.get('state') != state or status.get('message') != message or status.get('lastError') != error
    status.update(state=state, message=message, lastError=error)
    return changed


def _round_count(engine, username, game, issue):
    # Cancelled and refunded auto orders still consume that round's quota.
    return sum(1 for order in engine.s['orders'] if order['username'] == username
               and order['game'] == game and order['issue'] == issue
               and order.get('source') == 'simulated-auto')


def disable(user, state='disabled'):
    """Turning off a user/robot flag requires explicit re-enabling later."""
    for game, config in user.get('autoBet', {}).items():
        config['enabled'] = False
        status = _status(user, game)
        status['nextAt'] = None
        _set_state(status, state)
    user['auto'] = False


def _member(engine, username):
    user = engine.s['users'].get(username)
    if not user or user['role'] != 'member' or user.get('deleted'):
        raise ValueError('会员不存在')
    return user


def configure(engine, game, data):
    """Legacy single-room API, still atomic and isolated from other rooms."""
    with engine.lock:
        user = _member(engine, data.get('username'))
        candidate = copy.deepcopy(user)
        result = _configure_user(engine, game, data, candidate)
        user.clear()
        user.update(candidate)
        return result


def configure_batch(engine, data):
    """The selected rooms are the complete enabled set, committed atomically."""
    with engine.lock:
        user = _member(engine, data.get('username'))
        enabled = data.get('enabled')
        if not isinstance(enabled, bool):
            raise ValueError('自动下注开关无效')
        rooms = data.get('rooms')
        if not isinstance(rooms, list) or len(rooms) > len(GAMES):
            raise ValueError('请选择有效的自动下注房间')
        if any(not isinstance(game, str) or game not in GAMES for game in rooms) or len(set(rooms)) != len(rooms):
            raise ValueError('自动下注房间无效或重复')
        if enabled and not rooms:
            raise ValueError('请至少选择一个自动下注房间')
        if 'activateMember' in data and not isinstance(data['activateMember'], bool):
            raise ValueError('启用账号的确认值无效')
        candidate = copy.deepcopy(user)
        activated = False
        if enabled and data.get('activateMember') is True:
            if not candidate.get('enabled'):
                candidate['accessVersion'] = secrets.token_hex(16)
            activated = not candidate.get('enabled') or not candidate.get('robot')
            candidate.update(enabled=True, robot=True)
        if enabled and not candidate.get('enabled'):
            raise ValueError('账号已停用，请明确勾选“同时启用账号并设为模拟用户（托）”')
        if enabled and not candidate.get('robot'):
            raise ValueError('请明确勾选“同时启用账号并设为模拟用户（托）”，或先设置为托')
        if enabled:
            for game in rooms:
                try:
                    _configure_user(engine, game, data, candidate)
                except ValueError as exc:
                    raise ValueError(GAMES[game] + '：' + str(exc)) from exc
            for game in list(candidate.get('autoBet', {})):
                if game not in rooms:
                    _configure_user(engine, game, {'enabled': False}, candidate)
        else:
            disable(candidate)
        # Every selected-room check above completed without mutating the live user.
        user.clear()
        user.update(candidate)
        return {'message': (f'已启用 {len(rooms)} 个房间自动下注；未选房间已关闭' if enabled else '所有房间自动下注已关闭')
                + ('，账号已启用并标记为模拟用户（托）' if activated else ''),
                'rooms': list(rooms) if enabled else [], 'activatedMember': activated}


def _configure_user(engine, game, data, user):
    engine.game(game)
    if not isinstance(data.get('enabled'), bool):
        raise ValueError('自动下注开关无效')
    enabled = data['enabled']
    configs = user.setdefault('autoBet', {})
    previous = configs.get(game)
    # A stop command remains usable even if limits or member flags have changed.
    if not enabled and not any(field in data for field in
                               ('amountMin', 'amountMax', 'selections', 'intervalSeconds', 'betsPerRound', 'ball')):
        if previous:
            previous['enabled'] = False
        status = _status(user, game)
        status['nextAt'] = None
        _set_state(status, 'disabled')
        user['auto'] = any(c.get('enabled') is True for c in configs.values())
        return {'message': '本房间自动下注已关闭'}
    if enabled and not user.get('robot'):
        raise ValueError('请先将会员设置为模拟用户（托）')
    if enabled and not user.get('enabled'):
        raise ValueError('账号已停用，请先启用账号')
    minimum, maximum = bet_money(data.get('amountMin')), bet_money(data.get('amountMax'))
    room = engine.game(game)
    if not room.get('minBet', 1) <= minimum <= maximum <= room.get('maxBet', 100000000):
        raise ValueError('自动下注金额范围须位于房间最小与最大限注之间')
    choices = data.get('selections')
    if not isinstance(choices, list) or not 1 <= len(choices) <= 30:
        raise ValueError('请选择1至30项投注选项')
    selections = []
    for choice in choices:
        if not isinstance(choice, str) or not choice or len(choice) > 10:
            raise ValueError('投注选项无效')
        parsed = parse_bets(choice + '/1')
        if len(parsed) != 1 or parsed[0]['selection'] != choice:
            raise ValueError('投注选项仅填写玩法，不包含金额')
        if enabled: engine.bet_rate(game, choice)
        if choice not in selections:
            selections.append(choice)
    interval = _integer(data.get('intervalSeconds'), '下注间隔（秒）', 5, 3600)
    limit = _integer(data.get('betsPerRound'), '每期次数', 1, 100)
    ball = 0 if game == 'australia8ball' else _integer(data.get('ball', 8), '球位', 1, 8)
    status = _status(user, game)
    same_issue = status.get('issue') == room['issue']
    status['count'] = max(status.get('count', 0) if same_issue else 0,
                          _round_count(engine, user['username'], game, room['issue']))
    status['issue'] = room['issue']
    if enabled:
        # Never shorten an already scheduled delay through repeated saves/toggles.
        status['nextAt'] = max(status.get('nextAt') or 0, time.time() + interval)
        _set_state(status, 'waiting')
    else:
        status['nextAt'] = None
        _set_state(status, 'disabled')
    configs[game] = dict(version=1, enabled=enabled, amountMin=minimum, amountMax=maximum,
                         selections=selections, intervalSeconds=interval,
                         betsPerRound=limit, ball=ball if game == 'australia8ball' else 8,
                         updatedAt=stamp())
    user['auto'] = any(c.get('enabled') is True for c in configs.values())
    return {'message': '本房间模拟用户自动下注设置已保存' if enabled else '本房间自动下注已关闭'}


def tick(engine, now=None):
    """Run once under the Engine lock. No catch-up bursts after downtime."""
    now = time.time() if now is None else now
    changed = False
    for user in engine.s['users'].values():
        if user.get('role') != 'member':
            continue
        for game, config in user.get('autoBet', {}).items():
            if game not in GAMES or config.get('version') != 1:
                continue
            status = _status(user, game)
            state = ('user-disabled' if not user.get('enabled') else
                     'not-simulated' if not user.get('robot') else
                     'disabled' if not config.get('enabled') else None)
            if state:
                changed = _set_state(status, state) or changed
                continue
            room = engine.game(game)
            if status.get('issue') != room['issue']:
                status.update(issue=room['issue'], count=_round_count(engine, user['username'], game, room['issue']),
                              nextAt=now + config['intervalSeconds'])
                changed = True
            # The persistent count is the normal fast path. It never resets on save.
            if room['paused']:
                state = 'room-paused'
            elif not engine.accepting(game):
                state = 'closed'
            elif status['count'] >= config['betsPerRound']:
                state = 'round-limit'
            else:
                limits = engine.bet_limits(game, now)
                # Round inward so old fractional ranges remain within configured limits.
                minimum = max(1, (max(config['amountMin'], limits['minBet']) + 99) // 100)
                maximum = min(config['amountMax'], limits['maxBet']) // 100
                if minimum > maximum:
                    state = 'invalid-limits'
                elif now < (status.get('nextAt') or 0):
                    # Retain success feedback until the next execution or interruption.
                    state = 'running' if status.get('state') == 'running' else 'waiting'
            if state:
                changed = _set_state(status, state) or changed
                continue
            selection = secrets.choice(config['selections'])
            # submit is the same validation, wallet, order and chat path as members.
            try:
                # Do not fund a disabled/invalid play. Top-ups share one cooldown
                # across all rooms and are persisted with the scheduler state.
                engine.bet_rate(game, selection)
                if user['balance'] // 100 < minimum:
                    if now < user.get('autoTopupNextAt', 0):
                        changed = _set_state(status, 'insufficient-balance') or changed
                        continue
                    engine.request_score(user['username'], game, '上分', 1000 + secrets.randbelow(4001))
                    user['autoTopupNextAt'] = now + max(5, config['intervalSeconds'])
                    status['nextAt'] = now + config['intervalSeconds']
                    changed = True
                    if user['balance'] // 100 < minimum:
                        _set_state(status, 'insufficient-balance')
                        continue
                amount = minimum + secrets.randbelow(min(maximum, user['balance'] // 100) - minimum + 1)
                text = f'{selection}/{amount}'
                engine.submit(user['username'], game, text, config['ball'], source='simulated-auto')
            except ValueError as exc:
                _set_state(status, 'error', str(exc))
            else:
                status['count'] += 1
                status['lastAt'] = now
                _set_state(status, 'running')
            status['nextAt'] = now + config['intervalSeconds']
            changed = True
    return changed
