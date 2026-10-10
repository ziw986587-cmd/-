"""Loopback-only local reconstruction. No third-party dependencies."""
import argparse
import copy
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import socket
import threading
import time
import urllib.request
import history_feed
import shared_wallet
import robot_messages
import avatar_library
from functools import wraps
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
GAMES = {'canada28': '加拿大28番摊后2', 'australia8': '澳洲8番摊', 'australia8ball': '澳洲3'}
RULES = {'番': 2.91, '角': .97, '念': 1.94, '无': .97, '双无': .485, '通': .485, '正': .97, '车': .3233, '大小单双': .97, '特': 18}
SUM_ROOMS = ('canada28', 'australia8ball')
SUM_GROUPS = {'大': '大/小', '小': '大/小', '单': '单/双', '双': '单/双',
              '小单': '小单', '小双': '小双', '大单': '大单', '大双': '大双'}
SUM_ODDS = tuple(dict.fromkeys(SUM_GROUPS.values()))
A8_COMBOS = ('小单', '小双', '大单', '大双')

def total_limit_groups(key):
    """Return the playable odds groups that can have a per-round cap."""
    if key in SUM_ROOMS:
        base = tuple(k for k in RULES if k not in ('大小单双', '特'))
        return base + SUM_ODDS
    if key == 'australia8':
        return tuple(RULES) + A8_COMBOS
    return tuple(RULES)

def a8_number_outcome(selection, number):
    size, parity = ('大' if number >= 11 else '小'), ('单' if number % 2 else '双')
    return 'win' if selection in (size, parity, size + parity) else 'lose'

def sum_outcome(selection, total):
    """Settle new sum plays from the three-digit total (0..27)."""
    size, parity = ('大' if total >= 14 else '小'), ('单' if total % 2 else '双')
    return 'win' if selection in (size, parity, size + parity) else 'lose'


def legacy_sum_outcome(selection, fan):
    size, parity = ('大' if fan in (3, 4) else '小'), ('单' if fan % 2 else '双')
    return 'win' if selection in (size, parity, size + parity) else 'lose'

def natural_number(numbers):
    return int(''.join(str(n) for n in numbers))

def sum_rule_values(numbers):
    value = natural_number(numbers)
    return value, value % 20 or 20, sum(numbers) % 4 or 4

def stamp():
    return time.strftime('%Y-%m-%d %H:%M:%S')

def money(value):
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d <= 0 or d > 1000000 or d.as_tuple().exponent < -2:
            raise ValueError()
        return int(d * 100)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('积分须大于 0、不超过 1000000，最多两位小数')

def bet_money(value):
    if not re.fullmatch(r'[0-9]+', str(value)):
        raise ValueError('下注金额必须为正整数，不能包含小数点')
    return money(value)

def display_money(cents, signed=False):
    """Format integer cents without changing stored amounts or rounding."""
    whole, fraction = divmod(abs(cents), 100)
    sign = '-' if cents < 0 else '+' if signed else ''
    return sign + str(whole) + (f'.{fraction:02d}' if fraction else '')

def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 150000).hex()

def new_user(name, password, nickname, role='member'):
    salt = secrets.token_hex(16)
    return {'username': name, 'nickname': nickname, 'role': role, 'salt': salt,
            'hash': password_hash(password, salt), 'avatar': '👤', 'enabled': True,
            'balance': 1000000, 'walletVersion': 1, 'wallets': {g: 1000000 for g in GAMES}}


def serialized(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return run

def parse_bets(text, game=None):
    """Strict grammar; malformed batch never partially accepted."""
    # Normalize accepted homophones before punctuation and shorthand parsing.
    text = re.sub(r'堂(?!头)', '正', text)
    text = text.translate(str.maketrans({'翻':'番', '粘':'念', '娘':'念', '糖':'正', '唐':'正'}))
    # “严” is the room's shorthand for the same two-way win/push play as
    # “念”. Canonicalize it before parsing so settlement and receipts use one
    # selection name in every room.
    # Keep whitespace as a multi-bet separator.  Older versions removed it,
    # which made inputs such as ``12、100 23-100`` merge into one invalid item.
    text = ','.join(line.strip() for line in text.splitlines() if line.strip())
    # Accept punctuation between a selection and its stake.  The trailing
    # boundary deliberately excludes ``-`` so special batches such as
    # ``01-02-03特100`` keep their number-list meaning.
    stake_separator = re.compile(
        r'(?<![\d/])((?:特)?(?:[大小][单双]|[大小单双]|[1-4]{1,3}'
        r'(?:番|翻|花|番头|正|堂|唐|堂头|车|推车|埃车|三门|角|架杆|'
        r'念[1-4]{1,2}|无[1-4]|通[1-4]{2}|特)?))'
        r'[、，.\-](\d+(?:\.\d{1,2})?)(?![\d/.-])')
    text = stake_separator.sub(r'\1/\2', text)
    text = re.sub(r'\s+', ',', text).replace('、', ',').replace('，', ',')
    text = text.replace('；', ',').replace(';', ',').replace('=', '/').replace('／', '/').replace('＋', '+').replace('加', '+').replace('严', '念')
    bets = []
    for item in text.split(','):
        if game == 'australia8':
            # Explicit prefix and slash lists are unambiguous. Preserve existing
            # one/two/three-digit fan shorthand when no special prefix is given.
            special_each = re.fullmatch(r'特((?:\d{1,2}/)*\d{1,2})各(\d+(?:\.\d{1,2})?)', item)
            if special_each:
                numbers = list(map(int, special_each[1].split('/')))
                if any(n < 1 or n > 20 for n in numbers):
                    raise ValueError('特号范围为 01 至 20')
                if len(numbers) != len(set(numbers)):
                    raise ValueError('同组特码号码不能重复')
                amount = bet_money(special_each[2])
                bets.extend({'selection': f'{n:02d}特', 'amount': amount} for n in numbers)
                continue
            special_match = re.fullmatch(r'特((?:\d{1,2}/)*\d{1,2})/(\d+(?:\.\d{1,2})?)', item)
            if special_match is None:
                bare = re.fullmatch(r'((?:\d{1,2}/)*\d{1,2})/(\d+(?:\.\d{1,2})?)', item)
                if bare and ('/' in bare[1] or not re.fullmatch(r'[1-4]{1,3}', bare[1])):
                    special_match = bare
            if special_match:
                numbers = list(map(int, special_match[1].split('/')))
                if any(n < 1 or n > 20 for n in numbers):
                    raise ValueError('特号范围为 01 至 20')
                if len(numbers) != len(set(numbers)):
                    raise ValueError('同组特码号码不能重复')
                amount = bet_money(special_match[2])
                bets.extend({'selection': f'{n:02d}特', 'amount': amount} for n in numbers)
                continue
        # 12念100 means 1 wins, 2 pushes, stake 100. Keep the amount unambiguous.
        short_nian = re.fullmatch(r'([1-4])([1-4])念/?(\d+(?:\.\d{1,2})?)', item)
        if short_nian:
            item = f'{short_nian[1]}念{short_nian[2]}/{short_nian[3]}'
        m = re.fullmatch(r'((?:\d{1,2}[/-])*\d{1,2})特/?(\d+(?:\.\d{1,2})?)', item)
        if m:
            for number in re.split(r'[/-]', m[1]):
                n = int(number)
                if not 1 <= n <= 20: raise ValueError('特号范围为 01 至 20')
                bets.append({'selection': f'{n:02d}特', 'amount': bet_money(m[2])})
            continue
        m = re.fullmatch(r'((?:[1-4]{3}|[1-4])(?:番|翻|花|番头|正|堂|唐|堂头|车|推车|埃车|三门)|[1-4]{2}(?:角|架杆)|[1-4]念[1-4]{1,2}|[1-4]{1,2}无[1-4]|[1-4]通[1-4]{2}|[大小][单双]|[大小单双])/?(\d+(?:\.\d{1,2})?)', item)
        if not m:
            m = re.fullmatch(r'([1-4]{1,3})/(\d+(?:\.\d{1,2})?)', item)
            if m:
                digits, amount = m[1], m[2]
                if len(digits) == 1: selection = digits + '正'
                elif len(digits) == 2: selection = digits + '角'
                elif len(digits) == 3: selection = digits + '车'
                else: raise ValueError('斜杠简写仅支持一位正、两位角或三位车')
                bets.append({'selection': selection, 'amount': bet_money(amount)})
                continue
        if not m:
            m = re.fullmatch(r'([1-4])\+([1-4]{1,2})/(\d+(?:\.\d{1,2})?)', item)
            if m:
                bets.append({'selection': m[1] + '念' + m[2], 'amount': bet_money(m[3])})
                continue
        if not m: raise ValueError('格式无法识别。示例：1番100、12角50、1念2/30、12无3/20、查、退')
        selection = m[1]
        selection = re.sub(r'(翻|花|番头|堂头)$', '番', selection)
        selection = re.sub(r'架杆$', '角', selection)
        selection = re.sub(r'(推车|埃车|三门)$', '车', selection)
        if selection.endswith('车') and len(re.findall('[1-4]', selection)) == 1:
            if selection[0] in ('1', '2'):
                selection = ('123' if selection[0] == '1' else '234') + '车'
            else: raise ValueError('车玩法请使用1车或2车，或直接填写三位号码')
        digits = re.findall('[1-4]', selection)
        if len(digits) != len(set(digits)): raise ValueError('同一玩法的号码不能重复')
        if '角' in selection and set(digits) in ({'1', '3'}, {'2', '4'}): raise ValueError('角仅支持 12、23、34、14')
        if '念' in selection and len(digits) == 3 and len(set(digits[1:])) != 2: raise ValueError('加念的和号码不能重复')
        bets.append({'selection': selection, 'amount': bet_money(m[2])})
    if not bets or len(bets) > 30: raise ValueError('每次提交 1 至 30 条')
    return bets

def category(selection):
    if selection in '大小单双': return '大小单双'
    if '无' in selection and selection.index('无') == 2: return '双无'
    return next(k for k in ['番', '角', '念', '无', '通', '正', '车', '特'] if k in selection)

def outcome(selection, special):
    fan = special % 4 or 4
    if selection == '大': return 'win' if fan in (3, 4) else 'lose'
    if selection == '小': return 'win' if fan in (1, 2) else 'lose'
    if selection == '单': return 'win' if fan % 2 else 'lose'
    if selection == '双': return 'win' if not fan % 2 else 'lose'
    if selection.endswith('特'): return 'win' if int(selection[:-1]) == special else 'lose'
    digits = list(map(int, re.findall('[1-4]', selection)))
    if '番' in selection: return 'win' if fan == digits[0] else 'lose'
    if '角' in selection: return 'win' if fan in digits else 'lose'
    if '念' in selection:
        return 'win' if fan == digits[0] else 'push' if fan in digits[1:] else 'lose'
    if '无' in selection: return 'lose' if fan == digits[-1] else 'win' if fan in digits[:-1] else 'push'
    if '通' in selection: return 'win' if fan in digits[1:] else 'lose' if fan == digits[0] else 'push'
    if '正' in selection: return 'win' if fan == digits[0] else 'lose' if (fan-digits[0]) % 4 == 2 else 'push'
    if '车' in selection: return 'win' if fan in digits else 'lose'
    raise ValueError('未知玩法')

class Engine:
    def __init__(self, data_dir, defer_wallet_migration=False):
        self.lock = threading.RLock()
        self.path = Path(data_dir) / 'state.json'
        self.overlay_path = Path(data_dir) / 'state.overlay.json'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sessions = {}
        self.feed_status = {}
        self.feed_metrics = {}
        self.feed_observed = {}
        if self.path.exists():
            self.s = json.loads(self.path.read_text(encoding='utf-8'))
            # Chat and ordinary score requests use a small atomic overlay so
            # they do not rewrite the growing orders/ledger arrays.  The
            # overlay is merged over the base state during startup; business
            # operations that touch orders or ledger still write a full state.
            if self.overlay_path.exists():
                overlay = json.loads(self.overlay_path.read_text(encoding='utf-8'))
                if isinstance(overlay, dict):
                    for key, value in overlay.items():
                        if key not in ('orders', 'ledger'):
                            self.s[key] = value
            # Room keys stay stable so existing wallets, orders, and links remain
            # attached to the same room while its display name is updated.
            for key, name in GAMES.items():
                if key in self.s.get('games', {}):
                    self.s['games'][key]['name'] = name
        else:
            self.s = {'schema': 2, 'users': {u['username']: u for u in [
                new_user('localdemo', 'LocalDemo2026!', '本地会员'),
                new_user('localadmin', 'LocalDemo2026!', '本地管理员', 'admin')]},
                'games': {}, 'orders': [], 'ledger': [], 'requests': [], 'dedup': {}}
            for key, name in GAMES.items():
                self.s['games'][key] = {'name': name, 'mode': 'manual' if key == 'australia8ball' else 'simulation', 'period': 120, 'closeSeconds': 10,
                    'sequence': 1, 'issue': 'L000001', 'endAt': time.time()+120, 'closed': False, 'warned': False,
                    'bot': True, 'paused': False, 'history': [], 'chat': [], 'odds': dict(RULES),
                    'totalLimits': {group: None for group in total_limit_groups(key)},
                    'userLimit': None,
                    'notice': '澳洲3：每期120秒，后台手动录入三个0至9号码；和值0至13为小，14至27为大，奇数为单，偶数为双。' if key == 'australia8ball' else '欢迎来到本地房间。输入“帮助”查看指令；当前为本地模拟开奖。',
                    'feed': {'url': '', 'headers': {}, 'issuePath': 'issueNumber', 'numbersPath': 'numbers',
                             'nextIssuePath': 'nextIssueNumber', 'nextTimePath': 'nextOpenTime',
                             'rootPath': 'data', 'interval': 15}}
                self.bot(key, '本地房间已就绪。\nL000001期开始攻击\n' + ('澳洲3：三个0至9号码开奖；和值0至13为小、14至27为大，奇数为单、偶数为双，等待后台手动开奖。' if key == 'australia8ball' else '当前为模拟开奖，积分仅在本地使用。'), template='ready', variables={'房间说明': '澳洲3：三个0至9号码开奖；和值0至13为小、14至27为大，奇数为单、偶数为双，等待后台手动开奖。' if key=='australia8ball' else '当前为模拟开奖，积分仅在本地使用。'})
            self.save()
        for key in SUM_ROOMS:
            odds = self.game(key)['odds']
            for old, selections in (('小单/小双', ('小单', '小双')), ('大单/大双', ('大单', '大双'))):
                for selection in selections: odds.setdefault(selection, odds.get(old))
                odds.pop(old, None)
            for group in SUM_ODDS:
                odds.setdefault(group, odds['大小单双'] if group in ('大/小', '单/双') else None)
        for selection in A8_COMBOS:
            self.game('australia8')['odds'].setdefault(selection, None)
        for key in GAMES:
            limits = self.game(key).setdefault('totalLimits', {})
            for group in total_limit_groups(key):
                limits.setdefault(group, None)
            self.game(key).setdefault('userLimit', None)
        if not defer_wallet_migration:
            shared_wallet.initialize(self)

    def save(self):
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.s, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        os.replace(temp, self.path)
        self.overlay_path.unlink(missing_ok=True)

    def save_light(self):
        """Persist non-financial updates without rewriting historical records."""
        overlay = {key: value for key, value in self.s.items()
                   if key not in ('orders', 'ledger')}
        temp = self.overlay_path.with_suffix('.tmp')
        temp.write_text(json.dumps(overlay, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        os.replace(temp, self.overlay_path)

    def game(self, key):
        if key not in self.s['games']: raise ValueError('游戏不存在')
        return self.s['games'][key]

    def member_label(self, username, simulated=None):
        user = self.s['users'][username]
        simulated = bool(user.get('robot')) if simulated is None else simulated
        return user['nickname'] + ('（模拟）' if simulated else '')

    def chat(self, key, text, username=None, kind='MESSAGE', source=None, simulated=None, details=None):
        g = self.game(key)
        g['chat'].append({'id': secrets.token_hex(8), 'username': username,
            'who': self.s['users'][username]['nickname'] if username else g.get('robotName', '机器人'),
            'avatar': self.s['users'][username]['avatar'] if username else '🤖',
            'content': text, 'kind': kind, 'time': stamp(),
            'source': source or ('member' if username else 'system'),
            'simulated': bool(self.s['users'][username].get('robot')) if simulated is None and username else bool(simulated)})
        if details is not None:
            g['chat'][-1]['details'] = copy.deepcopy(details)
        g['chat'] = g['chat'][-1000:]

    def bot(self, key, text, kind='SYSTEM', details=None, template=None, variables=None, private=False):
        if not self.game(key)['bot']: return
        template = template or {'JIEGUO':'draw', 'SETTLEMENT':'winners', 'YINGLI':'ranking',
            'LUZI':'open', 'RECEIPT':'receipt', 'HEDUI':'close', 'A8_CLOSE_RULES':'a8_warning'}.get(kind)
        if kind in ('SCORE_REVIEW', 'SCORE_ADJUSTMENT') and details:
            template = 'up_success' if details['action']=='上分' else 'down_success'
            variables = {'昵称':self.s['users'][details['username']]['nickname'],
                         '金额':display_money(details['amount']), '余额':display_money(details['balance'])}
        if template:
            result = robot_messages.render(self, key, template, text, details, variables)
            if result is None: return
            text, details = result
        if private: return text
        self.chat(key, text, kind=kind, details=details)

    @serialized
    def credit(self, username, key, cents, reason, ref, source=None, simulated=None):
        u = self.s['users'][username]
        self.game(key)
        if isinstance(cents, bool) or not isinstance(cents, int): raise ValueError('积分变动无效')
        if u['balance'] + cents < 0: raise ValueError('共享积分不足')
        shared_wallet.set_balance(u, u['balance'] + cents, GAMES)
        self.s['ledger'].append({'id': secrets.token_hex(8), 'username': username, 'game': key,
            'delta': cents, 'balance': u['balance'], 'walletScope': 'shared', 'reason': reason, 'ref': ref, 'time': stamp(),
            'source': source or 'management', 'simulated': bool(u.get('robot')) if simulated is None else bool(simulated)})

    def accepting(self, key):
        g = self.game(key)
        return not g['paused'] and not g['closed'] and g['endAt']-time.time() > g['closeSeconds'] and bool(g['issue'])

    def pending(self, key, username=None):
        return [o for o in self.s['orders'] if o['game'] == key and o['status'] == '待开奖'
                and (username is None or o['username'] == username)]

    def closing_window(self, key, now=None):
        g = self.game(key)
        remaining = g['endAt'] - g['closeSeconds'] - (time.time() if now is None else now)
        return key == 'australia8' and 0 < remaining <= 60

    def a8_thresholds(self):
        g = self.game('australia8')
        raw = copy.deepcopy(g.get('a8Thresholds', {}))
        # Migrate the former two-stage configuration in memory. The old
        # second stage remains the middle stage; the new final stage starts at
        # the close boundary unless the administrator fills it in.
        middle = int(raw.get('middleSwitchSeconds', raw.get('switchSeconds', max(0, g['period'] - g['closeSeconds'] - 60))))
        final = int(raw.get('finalSwitchSeconds', g['period'] - g['closeSeconds']))
        first = raw.get('firstMax', 3000000)
        middle_max = raw.get('middleMax', raw.get('secondMax', 1000))
        final_total = raw.get('finalTotal', raw.get('thirdTotal'))
        return {'switchSeconds': middle, 'middleSwitchSeconds': middle,
                'finalSwitchSeconds': final, 'firstMax': first,
                'secondMax': middle_max, 'middleMax': middle_max,
                'finalTotal': final_total}

    def a8_phase(self, now=None):
        g = self.game('australia8')
        rules = self.a8_thresholds()
        elapsed = (time.time() if now is None else now) - (g['endAt'] - g['period'])
        if elapsed >= rules['finalSwitchSeconds']:
            return 'final'
        if elapsed >= rules['middleSwitchSeconds']:
            return 'middle'
        return 'first'

    def a8_stage_usage(self, issue, username, stage):
        """Return one user's pending bets inside one Australia 8 stage.

        Middle and final thresholds are independent windows.  Bets from an
        earlier stage do not consume a later stage's allowance.
        """
        g = self.game('australia8')
        rules = self.a8_thresholds()
        round_start = float(g['endAt']) - float(g['period'])
        if stage == 'middle':
            start = round_start + int(rules['middleSwitchSeconds'])
            end = round_start + int(rules['finalSwitchSeconds'])
        elif stage == 'final':
            start = round_start + int(rules['finalSwitchSeconds'])
            end = round_start + int(g['period'] - g['closeSeconds'])
        else:
            raise ValueError('无效的澳洲8限额阶段')
        return sum(
            int(order.get('amount', 0))
            for order in self.s['orders']
            if order.get('game') == 'australia8'
            and order.get('issue') == issue
            and order.get('username') == username
            and start <= float(order.get('placedAt', 0) or 0) < end
            and order.get('status') == '待开奖'
        )

    def a8_final_usage(self, issue, username):
        return self.a8_stage_usage(issue, username, 'final')

    def a8_middle_usage(self, issue, username):
        return self.a8_stage_usage(issue, username, 'middle')

    def bet_limits(self, key, now=None, username=None):
        g = self.game(key)
        maximum = g.get('maxBet', 100000000)
        if key == 'australia8':
            rules = self.a8_thresholds()
            phase = self.a8_phase(now)
            if phase == 'first':
                maximum = min(maximum, int(rules['firstMax']))
            elif phase == 'middle':
                # Middle stage uses its own per-user cumulative threshold;
                # the room-wide single-bet max does not reduce it.
                maximum = int(rules['middleMax'])
            elif rules['finalTotal'] is not None:
                # Final stage is governed by the configured cumulative cap;
                # the room-wide single-bet max is deliberately ignored.
                maximum = int(rules['finalTotal'])
        return {'minBet': g.get('minBet', 1), 'maxBet': maximum}

    def bet_rate(self, key, selection):
        if key in SUM_ROOMS and selection.endswith('特'):
            raise ValueError('加拿大28和澳洲3已取消特码下注，请选择其他玩法')
        group = self.bet_group(key, selection)
        rate = self.game(key)['odds'].get(group)
        if rate is None:
            raise ValueError(f'{group}倍率尚未设置，请联系管理员')
        return rate

    def bet_group(self, key, selection):
        """Map a parsed selection to the same odds group used for settlement."""
        if selection in SUM_GROUPS and key in SUM_ROOMS:
            return SUM_GROUPS[selection]
        if key == 'australia8' and selection in A8_COMBOS:
            return selection
        if selection in SUM_GROUPS and len(selection) == 2:
            raise ValueError('组合和值玩法仅适用于加拿大28和澳洲3')
        return category(selection)

    def total_limits(self, key):
        configured = self.game(key).get('totalLimits', {})
        return {group: configured.get(group) for group in total_limit_groups(key)}

    def user_limit(self, key):
        value = self.game(key).get('userLimit')
        return value if value else None

    def user_limit_usage(self, key, issue, username):
        return sum(int(order.get('amount', 0)) for order in self.s['orders']
                   if order.get('game') == key and order.get('issue') == issue
                   and order.get('username') == username and order.get('status') == '待开奖')

    def total_limit_usage(self, key, issue, group):
        total = 0
        for order in self.s['orders']:
            if order.get('game') != key or order.get('issue') != issue or order.get('status') != '待开奖':
                continue
            try:
                same_group = self.bet_group(key, order.get('selection', '')) == group
            except (ValueError, StopIteration):
                same_group = False
            if same_group:
                total += int(order.get('amount', 0))
        return total

    @serialized
    def submit(self, username, key, text, ball=8, source='member'):
        g = self.game(key)
        user = self.s['users'][username]
        if not user.get('enabled'):
            raise ValueError('用户已停用')
        if source == 'simulated-auto' and not user.get('robot'):
            raise ValueError('仅模拟用户可以自动下注')
        simulated = bool(user.get('robot'))
        if not self.accepting(key): raise ValueError('当前已封盘、暂停或等待开奖源，不接受注单')
        if key == 'australia8' and (isinstance(ball, bool) or not re.fullmatch(r'[1-8]', str(ball))):
            raise ValueError('球位须为 1 至 8 的整数')
        try: ball = int(ball)
        except (ValueError, TypeError): raise ValueError('球位无效')
        if key == 'australia8ball': ball = 0
        elif ball not in range(1, 9): raise ValueError('球位须为 1 至 8')
        bets = parse_bets(text, key)
        phase = self.a8_phase() if key == 'australia8' else None
        limits = self.bet_limits(key, username=username)
        a8_rules = self.a8_thresholds() if key == 'australia8' else None
        middle_a8 = key == 'australia8' and phase == 'middle' and a8_rules['middleMax'] is not None
        final_a8 = key == 'australia8' and phase == 'final' and a8_rules['finalTotal'] is not None
        if any(not limits['minBet'] <= b['amount'] <= limits['maxBet'] for b in bets):
            if key == 'australia8' and not (middle_a8 or final_a8):
                raise ValueError(f"澳洲8当前时段每条注单限额{limits['minBet']/100:g}至{limits['maxBet']/100:g}积分")
            if middle_a8:
                raise ValueError(f"澳洲8第二阶段个人累计最多还可下注{limits['maxBet']/100:g}积分")
            if final_a8:
                raise ValueError(f"澳洲8第三阶段个人累计最多还可下注{limits['maxBet']/100:g}积分")
            raise ValueError(f"每条注单积分超出房间限额（当前每条限额{limits['minBet']/100:g}至{limits['maxBet']/100:g}积分）")
        total = sum(b['amount'] for b in bets)
        batch_groups = {}
        for b in bets:
            group = self.bet_group(key, b['selection'])
            batch_groups[group] = batch_groups.get(group, 0) + b['amount']
        if middle_a8:
            middle_limit = int(a8_rules['middleMax'])
            used = self.a8_middle_usage(g['issue'], username)
            if used + total > middle_limit:
                available = max(0, middle_limit - used)
                raise ValueError(
                    f'澳洲8第二阶段个人累计限额为{display_money(middle_limit)}积分，'
                    f'您本期第二阶段已下注{display_money(used)}，'
                    f'本次最多还可下注{display_money(available)}'
                )
        if final_a8:
            final_limit = int(a8_rules['finalTotal'])
            used = self.a8_final_usage(g['issue'], username)
            if used + total > final_limit:
                available = max(0, final_limit - used)
                raise ValueError(
                    f'澳洲8最后阶段个人累计限额为{display_money(final_limit)}积分，'
                    f'您本期第三段已下注{display_money(used)}，'
                    f'本次最多还可下注{display_money(available)}'
                )
        for group, batch_amount in batch_groups.items():
            limit = self.total_limits(key).get(group)
            if limit is not None:
                used = self.total_limit_usage(key, g['issue'], group)
                if used + batch_amount > limit:
                    available = max(0, limit - used)
                    raise ValueError(f'{group}玩法本期总限额为{display_money(limit)}积分，已下注{display_money(used)}，本次最多还可下注{display_money(available)}')
        user_limit = self.user_limit(key)
        if user_limit is not None:
            used = self.user_limit_usage(key, g['issue'], username)
            if used + total > user_limit:
                available = max(0, user_limit - used)
                raise ValueError(f'本房间用户限额为{display_money(user_limit)}积分，您本期已下注{display_money(used)}，本次最多还可下注{display_money(available)}')
        if total > user['balance']: raise ValueError('共享积分不足')
        batch = secrets.token_hex(10)
        for b in bets:
            prefs = self.s.get('workbench', {}).get(key, {})
            b.update({'id': secrets.token_hex(8), 'batch': batch, 'username': username, 'game': key,
                'report': '模拟成功' if prefs.get('reportConnected') and prefs.get('autoReport') else '未上报',
                'issue': g['issue'], 'ball': ball if key in ('australia8', 'australia8ball') else 8,
                'status': '待开奖', 'profit': None, 'payout': None, 'time': stamp(),
                'placedAt': time.time(),
                'rate': self.bet_rate(key, b['selection']), 'source': source, 'simulated': simulated})
            if key in SUM_ROOMS: b['settlementRule'] = 'sum-v4'
            elif key == 'australia8': b['settlementRule'] = 'a8-number-v1'
        # Validate and construct every order before the shared debit, keeping failures atomic.
        self.credit(username, key, -total, '模拟用户自动下注' if source == 'simulated-auto' else '提交注单', batch,
                    source=source, simulated=simulated)
        self.s['orders'].extend(bets)
        ball_label = f'第{ball}球 ' if key == 'australia8' else ''
        # Keep the receipt unambiguous: every parsed selection is separated
        # from its stake with '/', including compact inputs such as 34无2500.
        receipt_text = ','.join(
            (ball_label if i == 0 else (f'第{ball}球 ' if key == 'australia8' else ''))
            + b['selection'] + '/' + display_money(b['amount']).replace('.00', '')
            for i, b in enumerate(bets)
        )
        self.chat(key, ball_label + text, username, source=source, simulated=simulated)
        self.bot(key, f"@{self.member_label(username)}，攻击[{receipt_text}]成功\n共享积分：{display_money(user['balance'])}", 'RECEIPT', variables={'昵称':user['nickname'], '球位':ball_label, '下注内容':receipt_text, '余额':display_money(user['balance'])})
        return '攻击成功'

    @serialized
    def cancel(self, username, key, order_id=None):
        if not self.accepting(key): raise ValueError('封盘后不能退单')
        if self.closing_window(key): raise ValueError('澳洲8离封盘60秒以内禁止取消注单')
        orders = [o for o in self.pending(key, username) if o['issue'] == self.game(key)['issue'] and (not order_id or o['id'] == order_id)]
        if not orders: raise ValueError('没有可退注单')
        for o in orders:
            self.credit(username, key, o['amount'], '退单返还', o['id'], source=o.get('source'), simulated=o.get('simulated'))
            o.update(status='已退单', profit=0, payout=o['amount'], completedAt=stamp())
        self.bot(key, f"@{self.s['users'][username]['nickname']} 已退 {len(orders)} 条，返还 {display_money(sum(o['amount'] for o in orders))} 积分", 'REFUND', template='cancel', variables={'昵称':self.s['users'][username]['nickname'], '笔数':str(len(orders)), '金额':display_money(sum(o['amount'] for o in orders))})
        return '退单成功'

    def close_round(self, key):
        g = self.game(key)
        if g['closed']: return
        g['closed'] = True
        rows = [o for o in self.pending(key) if o['issue'] == g['issue']]
        close_orders = [dict(username=o['username'], nickname=self.s['users'][o['username']]['nickname'],
                            selection=o['selection'], amount=o['amount'], ball=o.get('ball', 8)) for o in rows]
        groups = {}
        for o in close_orders:
            groups.setdefault(o['username'], []).append(o)
        lines = []
        for username, orders in groups.items():
            bets = [(f"第{o['ball']}球 " if key == 'australia8' else '') + o['selection']
                    + '/' + display_money(o['amount']).replace('.00', '') for o in orders]
            lines.append(f"({self.member_label(username)}) “" + ', '.join(bets) + '”')
        footer = g.get('closeFooter', '')
        self.bot(key, f"{g['issue']}期已封盘\n---------------\n{g['issue']}期核对列表\n" + ('\n'.join(lines) or '本期暂无注单') + '\n---------------\n以系统注单记录和退单状态为准。' + ('\n' + footer if footer else ''), 'HEDUI', details={'issue':g['issue'], 'game':key, 'closeOrders':close_orders, 'closeFooter':footer, 'closeList':'\n'.join(lines) or '本期暂无注单'}, variables={'核对列表':'\n'.join(lines) or '本期暂无注单', '封盘附加信息':('\n'+footer) if footer else ''})

    @serialized
    def settle(self, key, issue, numbers, source, next_issue=None, next_time=None):
        g = self.game(key)
        if any(h['issue'] == issue for h in g['history']): return False
        numbers = self.validate_numbers(key, numbers)
        if key == 'australia8' and any(type(o.get('ball', 8)) is not int or o.get('ball', 8) not in range(1, 9) for o in self.pending(key)):
            raise ValueError('存在球位无效的待开奖注单，请先核对')
        natural = special = fan = None
        if key == 'australia8ball':
            if any(o.get('ball') != 0 for o in self.pending(key)):
                raise ValueError('存在旧版按球位结算的待开奖注单，请先处理，不能套用三号码新规则')
            natural, special, fan = sum_rule_values(numbers)
        elif key == 'canada28':
            natural, special, fan = sum_rule_values(numbers)
        else: special = numbers[-1]; fan = special % 4 or 4
        self.close_round(key)
        result = {'issue': issue, 'numbers': numbers, 'special': special, 'fan': fan,
                  'time': stamp(), 'source': source}
        if key in SUM_ROOMS: result.update(natural=natural, total=sum(numbers), drawRule='sum3', settlementRule='sum-v4')
        elif key == 'australia8': result['settlementRule'] = 'a8-number-v1'
        g['history'].insert(0, result)
        profits, counts = {}, {}
        for o in self.pending(key):
            if o['issue'] != issue: continue
            val = numbers[o.get('ball', 8)-1] if key == 'australia8' else special
            total_sum = key in SUM_ROOMS and o.get('settlementRule') == 'sum-v4'
            digit_sum = key in SUM_ROOMS and o.get('settlementRule') == 'sum-v3'
            new_sum = key in SUM_ROOMS and o.get('settlementRule') == 'sum-v2'
            old_sum = key in SUM_ROOMS and o.get('settlementRule') == 'sum-v1'
            if total_sum:
                # New sum rooms settle 大/小/单/双 from the actual three-digit
                # total (0..27), while the stored special value remains the
                # legacy natural-number display value.
                val = sum(numbers)
            elif digit_sum:
                val = special if o['selection'].endswith('特') else sum(numbers)
            elif new_sum:
                val = special if o['selection'].endswith('特') else natural
            elif old_sum:
                val = sum(numbers) if key == 'australia8ball' else ((numbers[-2] * 10 + numbers[-1]) % 20 or 20)
            elif key == 'canada28':
                val = ((numbers[-2] * 10 + numbers[-1]) % 20) or 20
            if key == 'australia8' and o.get('settlementRule') == 'a8-number-v1' and o['selection'] in SUM_GROUPS:
                out = a8_number_outcome(o['selection'], val)
            elif total_sum and o['selection'] in SUM_GROUPS:
                out = sum_outcome(o['selection'], val)
            elif (digit_sum or new_sum) and o['selection'] in SUM_GROUPS:
                out = legacy_sum_outcome(o['selection'], (val % 4 or 4))
            else:
                out = outcome(o['selection'], val)
            profit = int((Decimal(o['amount']) * Decimal(str(o['rate']))).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if out == 'win' else 0
            payout = o['amount'] + profit if out == 'win' else o['amount'] if out == 'push' else 0
            o.update(status={'win': '中奖', 'push': '和局', 'lose': '未中'}[out], payout=payout, profit=payout-o['amount'], completedAt=stamp())
            if payout: self.credit(o['username'], key, payout, '开奖结算', o['id'], source=o.get('source'), simulated=o.get('simulated'))
            profits[o['username']] = profits.get(o['username'], 0) + o['profit']
            counts[o['username']] = counts.get(o['username'], 0) + 1
        label = '本地模拟' if source == 'simulation' else '手动录入' if source == 'manual' else '外部开奖源'
        self.bot(key, f"{issue}期结果 [{label}]\n{','.join(map(str,numbers))} => {result['fan']}番，{sum(numbers) if key in SUM_ROOMS else special}{'和值' if key in SUM_ROOMS else '特'}", 'JIEGUO', variables={**robot_messages.settlement_values({'draw':result,'issue':issue,'winningOrders':[]},key,display_money), '开奖来源':label})
        members = sorted((u for u in self.s['users'].values() if u['role'] == 'member' and (not u.get('deleted') or counts.get(u['username'], 0))),
                         key=lambda u: (-u['balance'], u['username']))
        rows = [dict(username=u['username'], nickname=u['nickname'], simulated=bool(u.get('robot')),
                     balance=u['balance'], profit=profits.get(u['username'], 0),
                     betCount=counts.get(u['username'], 0)) for u in members]
        scope = '本房间本期净输赢' + ('（新注单按三号码和值；旧注单按提交时规则）' if key in SUM_ROOMS else '')
        lines = [f"{self.member_label(r['username'])}  [{display_money(r['balance'])}] ({display_money(r['profit'], signed=True)})" for r in rows]
        details = dict(issue=issue, game=key, rows=rows, totalProfit=sum(profits.values()))
        details.update(draw=copy.deepcopy(result), winningOrders=self.winning_orders(
            [o for o in self.s['orders'] if o['game'] == key and o['issue'] == issue], rows))
        self.bot(key, f"{issue}期用户输赢结果\n{scope}；余额为结算后共用积分\n" + ('\n'.join(lines) or '暂无会员'),
                 'SETTLEMENT', details, variables=robot_messages.settlement_values(details,key,display_money))
        self.bot(key, '共享积分总榜\n' + '\n'.join(lines), 'YINGLI',
                 dict(issue=issue, game=key, rows=rows), variables={'期号':issue, '积分榜':'\n'.join(f"{r['nickname']} [{display_money(r['balance'])}] ({display_money(r['profit'],signed=True)})" for r in rows)})
        g['sequence'] += 1
        deadline = time.time()+g['period'] if next_time is None else next_time
        g.update(issue=next_issue or f"L{g['sequence']:06d}", endAt=deadline, closed=deadline<=time.time(), warned=False)
        phase = '等待开奖源对时，暂时封盘' if not deadline else '期开始攻击'
        fans = [str(h['fan']) for h in reversed(g['history'][:48])]
        history_lines = [' - '.join(fans[start:start+12]) for start in range(0, len(fans), 12)]
        self.bot(key, '历史参考：\n'+'\n'.join(history_lines)+f"\n---------------\n{g['issue']}{phase}", 'LUZI', variables={'历史参考':'\n'.join(history_lines), '开盘状态':phase})
        return True

    def validate_numbers(self, key, numbers):
        if isinstance(numbers, str): numbers = re.split('[,， +]+', numbers.strip())
        expected = 3 if key in ('canada28', 'australia8ball') else 8
        if not isinstance(numbers, list) or len(numbers) != expected: raise ValueError(f'开奖号码必须为 {expected} 个整数')
        if any(not re.fullmatch(r'\d{1,2}', str(n)) for n in numbers): raise ValueError('开奖号码格式错误')
        numbers = list(map(int, numbers))
        low, high = (0, 9) if key in ('canada28', 'australia8ball') else (1, 20)
        if any(n < low or n > high for n in numbers): raise ValueError(f'号码范围 {low} 至 {high}')
        if key == 'australia8' and len(set(numbers)) != 8: raise ValueError('澳洲8号码不可重复')
        return numbers

    def tick(self):
        with self.lock:
            changed = False
            for key, g in self.s['games'].items():
                if g['paused']: continue
                remain = g['endAt']-time.time()
                if key == 'australia8':
                    before_close = remain - g['closeSeconds']
                    if (not g['closed'] and 0 < before_close <= 60 and
                            g.get('closingNoticeIssue') != g['issue'] and g['bot']):
                        rules = self.a8_thresholds()
                        early = min(g.get('maxBet', 100000000), rules['firstMax']) / 100
                        middle = rules['middleMax'] / 100
                        middle_seconds = rules['middleSwitchSeconds']
                        final_seconds = rules['finalSwitchSeconds']
                        final = '不限' if rules['finalTotal'] is None else f"{rules['finalTotal']/100:g}"
                        self.bot(key, f'离封盘还剩{math.ceil(before_close)}秒！\n60秒以内禁止取消\n开奖后0至{middle_seconds}秒单注最高：{early:g}\n开奖后{middle_seconds}至{final_seconds}秒个人累计最高：{middle:g}\n开奖后{final_seconds}秒起至封盘个人累计最高：{final}', 'A8_CLOSE_RULES', variables={'剩余秒数':str(math.ceil(before_close)), '切换秒数':str(middle_seconds), '前段限额':f'{early:g}', '后段限额':f'{middle:g}', '第三段起始秒数':str(final_seconds), '第三段累计限额':final})
                        g['closingNoticeIssue'] = g['issue']
                        changed = True
                elif 0 < remain <= 60 and not g['warned']:
                    g['warned'] = True; self.bot(key, f'还有 {max(0,math.ceil(remain))} 秒开奖', template='warning', variables={'剩余秒数':str(max(0,math.ceil(remain)))}); changed = True
                if remain <= g['closeSeconds'] and not g['closed']:
                    self.close_round(key); changed = True
                if remain <= 0 and g['mode'] == 'simulation':
                    numbers = [secrets.randbelow(10) for _ in range(3)] if key in ('canada28', 'australia8ball') else secrets.SystemRandom().sample(range(1,21), 8)
                    self.settle(key, g['issue'], numbers, 'simulation'); changed = True
            if self.game('australia8').get('pending168Feed'):
                from lottery168_feed import activate_pending
                changed = activate_pending(self) or changed
            from simulated_users import tick as tick_simulated_users
            changed = tick_simulated_users(self) or changed
            if changed: self.save()

    @serialized
    def request_score(self, username, key, action, amount):
        self.game(key)
        user = self.s['users'][username]
        if user.get('role') != 'member' or not user.get('enabled'):
            raise ValueError('会员不存在或已停用')
        cents = money(amount)
        if action not in ('上分', '下分'): raise ValueError('类型无效')
        if action == '下分' and cents > self.s['users'][username]['balance']: raise ValueError('共享积分不足')
        r = {'id': secrets.token_hex(8), 'username': username, 'game': key, 'action': action, 'amount': cents, 'status': '待审核', 'time': stamp()}
        self.s['requests'].append(r)
        if action == '上分' and user.get('robot') is True:
            self.credit(username, key, cents, '模拟用户上分自动审核', r['id'], source='simulated-auto-topup', simulated=True)
            r.update(status='已通过', autoApproved=True, reviewedBy='system', reviewedAt=stamp(), simulated=True)
            self.chat(key, '上分'+display_money(cents), username, source='member', simulated=True)
            balance = user['balance']
            self.bot(key, f"@{user['nickname']} 上{display_money(cents)}成功，剩余共享积分{display_money(balance)}", 'SCORE_REVIEW',
                     dict(requestId=r['id'], username=username, action=action, amount=cents, balance=balance, status=r['status']))
            return f'上{display_money(cents)}成功，剩余共享积分{display_money(balance)}'
        self.bot(key, f"@{self.s['users'][username]['nickname']}{action}{display_money(cents)}，待管理员审核请稍后", 'SCORE_REQUEST', template='up_request' if action=='上分' else 'down_request', variables={'昵称':self.s['users'][username]['nickname'], '金额':display_money(cents)})
        return f'{action}{display_money(cents)} 积分申请已提交，等待管理员审核'

    def message(self, username, key, text, ball):
        text = str(text).strip()
        if not text or len(text) > 500: raise ValueError('消息须为 1 至 500 个字符')
        score_command = re.fullmatch(r'(上|下)(?:分)?\s*([0-9]+(?:\.[0-9]{1,2})?)', text)
        if text in ('查', '查流水', '流水', '查余额', '余额'):
            from member_rebate import effective_turnover
            self.chat(key, text, username)
            rows = [o for o in self.s['orders'] if o['game'] == key and o['username'] == username]
            turnover = display_money(sum(effective_turnover(o) for o in rows))
            profit = sum(o['profit'] or 0 for o in rows)
            current_issue = self.game(key)['issue']
            current_orders = [o for o in rows if o['issue'] == current_issue and o['status'] == '待开奖']
            current_amount = sum(o['amount'] for o in current_orders)
            current_details = '\n'.join(
                (f"第{o.get('ball', 8)}球 " if key == 'australia8' else '')
                + f"{o['selection']}：{display_money(o['amount'])}" for o in current_orders) or '暂无下注'
            self.bot(key, f"共享积分：{display_money(self.s['users'][username]['balance'])}\n"
                           f"当局下注明细（{current_issue}期）：\n{current_details}\n"
                           f"合计：{display_money(current_amount)}（{len(current_orders)}笔）\n"
                           f"累计盈亏：{display_money(profit)}\n"
                           f"有效流水：{turnover}", template='balance', variables={'昵称':self.s['users'][username]['nickname'], '余额':display_money(self.s['users'][username]['balance']), '当局下注明细':current_details, '当局下注金额':display_money(current_amount), '笔数':str(len(current_orders)), '累计盈亏':display_money(profit), '有效流水':turnover, '累计流水':turnover})
        elif text in ('退', '退单', '取消'): return self.cancel(username, key)
        elif text == '帮助':
            return self.bot(key, '指令：查、退（或退单、取消）、帮助、上500（或上分500）、下500（或下分500）\n上下分提交申请后须等待管理员审核，金额最多两位小数。\n注单示例：1番100、12角50、1念2/30、12无3/20、1通23/20' + ('；三个号码相加取和值，0至13为小、14至27为大，奇数为单、偶数为双，不支持特码。' if key in SUM_ROOMS else '、01/09特10') + '\n本地规则与赔率见“规则与赔率”。', template='help', private=True, variables={'房间规则': '；三个号码相加取和值，0至13为小、14至27为大，奇数为单、偶数为双，不支持特码。' if key in SUM_ROOMS else '、01/09特10'})
        elif score_command:
            return self.request_score(username, key, score_command[1]+'分', score_command[2])
        elif re.match(r'^(?:上分|下分|上|下)\s*[0-9.+-]', text):
            raise ValueError('上下分指令格式错误。示例：上500、下100、上分500.50；金额须大于0，最多两位小数')
        elif re.search(r'\d', text) and (
            re.search('[番翻正糖唐堂车角念粘娘严无通特大小单双]', text)
                or re.search(r'(?:^|[,，;；\r\n])\s*[1-4]{1,3}\s*[/／=]\s*\d', text)
                or (key == 'australia8' and re.search(r'(?:^|[,，;；\r\n])\s*\d+\s*[/／=]\s*\d', text))):
            return self.submit(username, key, text, ball)
        else: raise ValueError('只支持有效下注指令，请检查玩法和金额；普通文字不能发送到房间')
        return '已发送'

    def winning_orders(self, orders, rows):
        members = {r['username']: r for r in rows}
        return [dict(id=o['id'], username=o['username'], nickname=members[o['username']]['nickname'],
                     simulated=bool(o.get('simulated', members[o['username']].get('simulated', False))),
                     ball=o.get('ball', 8), selection=o['selection'], amount=o['amount'], profit=o['profit'])
                for o in orders if o['username'] in members and o.get('status') == '中奖' and (o.get('profit') or 0) > 0]

    def settlement_chat(self, chat, game, key):
        # Enrich old messages only when the persisted orders match the original counts.
        # Build an index once per response; never change saved history or balances.
        missing = {m['details']['issue'] for m in chat if m.get('kind') == 'SETTLEMENT'
                   and m.get('username') is None and m.get('source') in (None, 'system')
                   and m.get('details', {}).get('game') == key
                   and 'winningOrders' not in m.get('details', {})}
        index = {issue: [] for issue in missing}
        for o in (self.s['orders'] if missing else ()):
            if o.get('game') == key and o.get('issue') in index and o.get('status') in ('中奖','未中','和局'):
                index[o['issue']].append(o)
        draws = {h['issue']: h for h in game['history'] if h['issue'] in missing}
        result = []
        for m in chat:
            d = m.get('details', {})
            issue = d.get('issue')
            if m.get('kind') == 'SETTLEMENT' and m.get('username') is None and m.get('source') in (None, 'system') and d.get('game') == key and issue in draws and 'winningOrders' not in d and isinstance(d.get('rows'), list):
                counts = {}
                for o in index[issue]: counts[o['username']] = counts.get(o['username'], 0) + 1
                expected = {r['username']: r['betCount'] for r in d['rows'] if r.get('betCount', 0) > 0}
                if counts == expected:
                    m = {**m, 'details': {**d, 'draw': copy.deepcopy(draws[issue]),
                         'winningOrders': self.winning_orders(index[issue], d['rows'])}}
            # Old rankings immediately follow their settlement. Reuse that
            # immutable snapshot, never today's wallet or a different room.
            if m.get('kind') == 'YINGLI' and m.get('username') is None and m.get('source') in (None, 'system') and not d and result:
                previous = result[-1]
                snapshot = previous.get('details', {})
                if previous.get('kind') == 'SETTLEMENT' and previous.get('username') is None and previous.get('source') in (None, 'system') and snapshot.get('game') == key and isinstance(snapshot.get('rows'), list):
                    m = {**m, 'details': copy.deepcopy({k: snapshot[k] for k in ('issue', 'game', 'rows')})}
            result.append(m)
        return result

    def public(self, username, key):
        g, u = self.game(key), self.s['users'][username]
        orders = [o for o in self.s['orders'] if o['game'] == key and o['username'] == username]
        chat = [{**m, 'content': re.sub(r'^([A-Za-z0-9_-]+期)停止(?=\r?\n|$)', r'\1已封盘', m['content'], count=1)}
                if m.get('kind') == 'HEDUI' and m.get('username') is None and m.get('source') in (None, 'system') else m
                for m in g['chat'][-250:]]
        chat = [{**m, 'avatar':self.s['users'][m['username']]['avatar']} if m.get('username') in self.s['users'] else m for m in chat]
        chat = self.settlement_chat(chat, g, key)
        return {'user': {**{k: u[k] for k in ('username','nickname','avatar','role')}, 'robot': bool(u.get('robot')), 'balance': u['balance']}, 'wallets': dict(u['wallets']),
            'games': GAMES, 'game': key, 'score': u['balance'], 'balance': u['balance'], 'walletScope': 'shared',
            'round': {k:g[k] for k in ('issue','endAt','closed','period','closeSeconds','mode','paused')},
            'serverTime': time.time(), 'accepting': self.accepting(key), 'notice': g['notice'], 'bot': g['bot'],
            'limits': self.bet_limits(key),
            **({'a8Thresholds': self.a8_thresholds()} if key == 'australia8' else {}),
            'history': g['history'][:150], 'chat': chat, 'orders': orders[-300:][::-1], 'odds': {k:v for k,v in g['odds'].items() if key not in SUM_ROOMS or k not in ('大小单双', '特')},
            'ledger': [l for l in self.s['ledger'] if l['username'] == username][-200:][::-1],
            'requests': [r for r in self.s['requests'] if r['username'] == username][-100:][::-1],
            'profit': sum(o['profit'] or 0 for o in orders),
            'feedStatus': self.feed_status.get(key, '未连接开奖源' if g['mode']=='external' else '本地运行'),
            'ranking': [{'nickname': p['nickname'], 'balance': p['balance'], 'robot': bool(p.get('robot')), 'simulated': bool(p.get('robot'))} for p in sorted(self.s['users'].values(), key=lambda p:p['balance'],reverse=True) if p['role'] != 'admin' and p['enabled']]}

    def admin_state(self):
        return {'games': {key:{**{k:copy.deepcopy(g[k]) for k in ('name','mode','period','closeSeconds','bot','paused','notice','odds','feed','minBet','maxBet')}, 'totalLimits': self.total_limits(key), 'userLimit': self.user_limit(key), 'closeFooter': g.get('closeFooter', ''), **({'a8Thresholds': self.a8_thresholds()} if key == 'australia8' else {})} for key,g in self.s['games'].items()},
            'users': [{k:u.get(k) for k in ('username','nickname','role','enabled','balance','wallets','walletVersion','avatar','remark','createdAt','legacyId','robot','auto','rebate','autoBet','autoBetStatus','deleted','deletedAt')} for u in self.s['users'].values()],
            'walletScope': 'shared', 'sharedWalletVersion': self.s.get('sharedWalletVersion'),
            'requests': self.s['requests'][-200:][::-1], 'orders': self.s['orders'][-500:][::-1],
            'feedStatus': dict(self.feed_status), 'feedMetrics': copy.deepcopy(self.feed_metrics), 'dataFile': str(self.path)}

    def configure(self, key, data):
        g = self.game(key)
        footer = data.get('closeFooter', g.get('closeFooter', ''))
        if not isinstance(footer, str) or len(footer) > 500:
            raise ValueError('封盘附加信息须为文字，最多500字')
        footer = footer.replace('\r\n', '\n').replace('\r', '\n').strip()
        mode = data.get('mode', g['mode'])
        if mode not in ('simulation', 'manual', 'external'): raise ValueError('开奖模式无效')
        period, close = int(data.get('period',g['period'])), int(data.get('closeSeconds',g['closeSeconds']))
        if not 30 <= period <= 3600 or not 0 <= close < period: raise ValueError('周期须为30至3600秒，封盘提前量小于周期')
        if (mode != g['mode'] or period != g['period']) and self.pending(key): raise ValueError('请先结算或退还待开奖注单，再切换模式/周期')
        odds = data.get('odds', g['odds'])
        if not isinstance(odds, dict): raise ValueError('赔率格式无效')
        odds = dict(odds)
        if key in SUM_ROOMS:
            if any(k in odds for k in ('小单/小双', '大单/大双')):
                raise ValueError('组合倍率已拆为四项，请刷新后台后分别填写')
            # Accept legacy clients without dropping the newly configured groups.
            for group in SUM_ODDS: odds.setdefault(group, g['odds'][group])
        if key == 'australia8':
            for group in A8_COMBOS: odds.setdefault(group, g['odds'][group])
        min_bet = money(data['minBet']) if 'minBet' in data else g.get('minBet', 1)
        max_bet = money(data['maxBet']) if 'maxBet' in data else g.get('maxBet', 100000000)
        if min_bet > max_bet: raise ValueError('最小限额不能高于最大限额')
        raw_user_limit = data.get('userLimit', g.get('userLimit'))
        if raw_user_limit in (None, '', 0, 0.0, '0', '0.0', '0.00'):
            user_limit = None
        elif isinstance(raw_user_limit, bool):
            raise ValueError('本房间用户限额须为正数，留空或0表示不限')
        else:
            user_limit = money(raw_user_limit)
        thresholds = None
        if 'a8Thresholds' in data:
            if key != 'australia8': raise ValueError('分时限额仅适用于澳洲8')
            raw = data['a8Thresholds']
            if not isinstance(raw, dict): raise ValueError('分时限额格式无效')
            # Accept the legacy two-stage payload from older admin tabs.
            legacy = set(raw) == {'switchSeconds', 'firstMax', 'secondMax'}
            expected = {'middleSwitchSeconds','finalSwitchSeconds','firstMax','middleMax','finalTotal'}
            if not legacy and set(raw) != expected:
                raise ValueError('请完整填写三段限额')
            middle_seconds = raw.get('middleSwitchSeconds', raw.get('switchSeconds'))
            final_seconds = raw.get('finalSwitchSeconds', period - close)
            if any(isinstance(v, bool) or not isinstance(v, int) for v in (middle_seconds, final_seconds)):
                raise ValueError('分段秒数须为整数')
            first_value = money(raw['firstMax'])
            middle_value = money(raw.get('middleMax', raw.get('secondMax')))
            final_raw = raw.get('finalTotal')
            final_value = None if final_raw in (None, '', 0, 0.0, '0', '0.0', '0.00') else money(final_raw)
            thresholds = {'switchSeconds': middle_seconds, 'middleSwitchSeconds': middle_seconds,
                          'finalSwitchSeconds': final_seconds, 'firstMax': first_value,
                          'secondMax': middle_value, 'middleMax': middle_value,
                          'finalTotal': final_value}
        checked_thresholds = thresholds if thresholds is not None else g.get('a8Thresholds')
        if key == 'australia8' and checked_thresholds is not None:
            middle_seconds = int(checked_thresholds.get('middleSwitchSeconds', checked_thresholds['switchSeconds']))
            final_seconds = int(checked_thresholds.get('finalSwitchSeconds', period - close))
            close_at = period - close
            # A legacy two-stage configuration is represented with the final
            # boundary equal to close_at. Preserve that valid shape; new
            # three-stage configurations must end strictly before封盘.
            if final_seconds == close_at:
                if not 0 < middle_seconds < close_at:
                    raise ValueError('分段秒数须按先后填写，并小于等于封盘前总秒数')
            elif not 0 < middle_seconds < final_seconds < close_at:
                raise ValueError('两处分段秒数须按先后填写，并小于封盘前总秒数')
            if min(checked_thresholds['firstMax'], checked_thresholds.get('middleMax', checked_thresholds['secondMax'])) < min_bet:
                raise ValueError('前两段单注限额不能低于房间最小限额')
            if checked_thresholds.get('finalTotal') is not None and checked_thresholds['finalTotal'] < min_bet:
                raise ValueError('第三段累计限额不能低于房间最小限额')
        raw_total_limits = data.get('totalLimits', g.get('totalLimits', {}))
        if not isinstance(raw_total_limits, dict):
            raise ValueError('玩法总限额格式无效')
        total_limits = {}
        for group in total_limit_groups(key):
            value = raw_total_limits.get(group)
            if value in (None, '', 0, 0.0, '0', '0.0', '0.00'):
                total_limits[group] = None
                continue
            if isinstance(value, bool):
                raise ValueError('玩法总限额须为正数，留空或0表示不限')
            total_limits[group] = money(value)
        optional = set(SUM_ODDS) if key in SUM_ROOMS else set(A8_COMBOS)
        expected = set(RULES) | optional
        if set(odds) != expected or any(
                not (k in optional and x is None) and
                (isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) or not 0<x<=100)
                for k,x in odds.items()): raise ValueError('赔率须大于0且不超过100；和值玩法留空表示未启用')
        feed = dict(g['feed']); feed.update(data.get('feed', {}))
        feed['interval'] = max(2, min(300, int(feed['interval'])))
        if feed.get('format', 'json') not in ('json', 'pc28-history', 'byw-a8', '168-a8'):
            raise ValueError('开奖接口格式无效')
        if feed.get('format') == 'byw-a8':
            if key != 'australia8' or period != 300:
                raise ValueError('澳洲幸运8接口仅用于澳洲8房间，周期须为300秒')
            from australia8_feed import validate_url
            validate_url(feed['url'])
        if (feed.get('format'),feed.get('url')) != (g['feed'].get('format'),g['feed'].get('url')) and self.pending(key) and (feed.get('format') == 'byw-a8' or g['feed'].get('format') == 'byw-a8'):
            raise ValueError('请先结算或退还待开奖注单，再更换澳洲8开奖接口')
        if feed.get('format') == '168-a8':
            if key != 'australia8' or period != 300:
                raise ValueError('168澳洲幸运8仅支持澳洲8房间，周期须为300秒')
            from lottery168_feed import validate_url
            validate_url(feed['url'])
        if self.pending(key) and (feed.get('format') == '168-a8' or g['feed'].get('format') == '168-a8') and (feed != g['feed'] or mode != g['mode']):
            raise ValueError('请先结算待开奖注单，再切换澳洲8开奖源')
        if feed.get('format') == 'pc28-history' and (key != 'canada28' or period != 210):
            raise ValueError('加拿大28历史接口周期须为210秒')
        if feed['url']:
            p = urlparse(feed['url'])
            if p.scheme not in ('https','http') or not p.hostname or p.username or p.password: raise ValueError('开奖地址须为 HTTP/HTTPS URL')
        if not isinstance(feed['headers'],dict) or any(not isinstance(v,str) or '\n' in v or '\r' in v for v in feed['headers'].values()): raise ValueError('请求头须为 JSON 字符串对象')
        if mode == 'external' and not feed['url']: raise ValueError('请填写开奖接口地址')
        if feed != g['feed'] or mode != g['mode'] or period != g['period']:
            self.feed_observed.pop(key, None)
        if mode != g['mode'] or period != g['period']:
            g.update(endAt=time.time()+period if mode!='external' else 0, closed=mode=='external', warned=False)
        g.update(mode=mode,period=period,closeSeconds=close,odds=odds,feed=feed,minBet=min_bet,maxBet=max_bet,
                 totalLimits=total_limits,userLimit=user_limit,
                 bot=bool(data.get('bot',g['bot'])),paused=bool(data.get('paused',g['paused'])),notice=str(data.get('notice',g['notice']))[:500],closeFooter=footer)
        if thresholds is not None: g['a8Thresholds'] = thresholds
        return '设置已保存'

    def external_result(self, key, obj, config):
        import australia3_feed
        if australia3_feed.supports(key, config):
            with self.lock:
                g = self.game(key)
                if g['mode'] != 'external' or g['paused'] or g['feed'] != config: return
                return australia3_feed.apply(self, key, obj, config, time.time())
        if config.get('format') == '168-a8':
            import lottery168_feed
            with self.lock:
                g = self.game(key)
                if g['mode'] != 'external' or g['paused'] or g['feed'] != config: return
                return lottery168_feed.apply(self, key, obj, config, time.time())
        if config.get('format') == 'byw-a8':
            import australia8_feed
            with self.lock:
                g = self.game(key)
                if g['mode'] != 'external' or g['paused'] or g['feed'] != config:
                    return
                return australia8_feed.apply(self, key, obj, config, time.time())
        if config.get('format') == 'pc28-history':
            with self.lock:
                g = self.game(key)
                if g['mode'] != 'external' or g['paused'] or g['feed'] != config:
                    return
                return history_feed.apply(self, key, obj, config, time.time())
        def at(path, default=None):
            cur=obj
            try:
                for bit in path.split('.') if path else []:
                    cur = cur[int(bit)] if isinstance(cur,list) else cur[bit]
                return cur
            except (KeyError, IndexError, TypeError, ValueError): return default
        root=at(config['rootPath'])
        if not isinstance(root,dict): raise ValueError('开奖响应根节点不是对象')
        obj=root
        issue=str(at(config['issuePath'],'')); nxt=str(at(config['nextIssuePath'],''))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',issue) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',nxt) or issue==nxt:
            raise ValueError('开奖响应须包含有效本期、下一期期号')
        nt=at(config['nextTimePath'])
        if isinstance(nt,(int,float)): nt=float(nt)/(1000 if nt>1e12 else 1)
        else:
            from datetime import datetime
            nt=datetime.fromisoformat(str(nt).replace('Z','+00:00')).timestamp()
        if not math.isfinite(nt) or not time.time()<nt<time.time()+86400: raise ValueError('下一期开奖时间过期或无效')
        nums=self.validate_numbers(key,at(config['numbersPath']))
        with self.lock:
            g=self.game(key)
            if g['mode']!='external' or g['feed'] != config: return
            if any(h['issue']==issue for h in g['history']): return
            pending=self.pending(key)
            if pending and g['issue']!=issue: raise ValueError('接口跳期，待开奖注单保留，需补录正确期号')
            self.settle(key,issue,nums,'external',nxt,nt); self.save()

    def collector(self):
        from draw_collector import run
        run(self)

class Handler:
    """Shared room operations; authentication belongs to the unified Node server."""
    def mutate(self,path,username,key,d):
        e=self.engine; g=e.game(key)
        if path=='/api/bet': return e.submit(username,key,str(d.get('text','')),d.get('ball',8))
        if path=='/api/chat': return e.message(username,key,d.get('message',''),d.get('ball',8))
        if path=='/api/cancel': return e.cancel(username,key,d.get('id'))
        if path=='/api/score-request': return e.request_score(username,key,d['action'],d['amount'])
        if path=='/api/transfer':
            raise ValueError('三个房间已共用同一积分余额，无需跨房间转分')
        if path=='/api/profile':
            name=str(d.get('nickname','')).strip()
            if not 1<=len(name)<=20: raise ValueError('昵称须为1至20字')
            avatar=d.get('avatar','👤')
            avatar = avatar_library.validate(avatar)
            e.s['users'][username].update(nickname=name,avatar=avatar); return '资料已保存'
        if path=='/api/admin/config': return e.configure(key,d)
        if path=='/api/admin/force-open':
            from force_open import run
            return run(e, key, d)
        if path=='/api/admin/close': e.close_round(key); return '已封盘并生成核对列表'
        if path=='/api/admin/draw':
            if g['mode']=='external': raise ValueError('外部模式不生成随机结果，请使用补录')
            nums=d.get('numbers')
            if not nums:
                if g['mode']=='manual': raise ValueError('手动模式须填写号码')
                nums=[secrets.randbelow(10) for _ in range(3)] if key in ('canada28', 'australia8ball') else secrets.SystemRandom().sample(range(1,21),8)
            e.settle(key,g['issue'],nums,'manual' if d.get('numbers') else 'simulation'); return '本地开奖及结算完成'
        if path=='/api/admin/import':
            e.external_result(key,d['response'],g['feed']); return '补录已处理'
        if path=='/api/admin/refund':
            for o in e.pending(key):
                e.credit(o['username'],key,o['amount'],'管理员退单',o['id'],source=o.get('source'),simulated=o.get('simulated')); o.update(status='已退单',profit=0,payout=o['amount'],completedAt=stamp())
            e.bot(key,'管理员已退还本房间全部待开奖注单。', template='admin_refund'); return '待开奖注单已退还'
        if path=='/api/admin/score':
            target=d['username']
            if target not in e.s['users']: raise ValueError('账号不存在')
            cents=money(d['amount'])*(1 if d['action']=='上分' else -1)
            ref = secrets.token_hex(8)
            e.credit(target,key,cents,'管理员'+d['action'],ref)
            balance = e.s['users'][target]['balance']
            e.bot(key, f"@{e.s['users'][target]['nickname']} {d['action'][0]}{display_money(abs(cents))}成功，剩余共享积分{display_money(balance)}", 'SCORE_ADJUSTMENT',
                  dict(ref=ref, username=target, action=d['action'], amount=abs(cents), balance=balance, status='已通过'))
            return '本地积分已调整'
        if path=='/api/admin/review':
            r=next((r for r in e.s['requests'] if r['id']==d['id']),None)
            if not r or r['status']!='待审核': raise ValueError('申请不存在或已处理')
            if d.get('approve'):
                e.credit(r['username'],r['game'],r['amount']*(1 if r['action']=='上分' else -1),'审核'+r['action'],r['id']); r['status']='已通过'
            else: r['status']='已拒绝'
            r['reviewedAt'] = stamp()
            if r['status'] == '已通过':
                balance = e.s['users'][r['username']]['balance']
                e.bot(r['game'], f"@{e.s['users'][r['username']]['nickname']} {r['action'][0]}{display_money(r['amount'])}成功，剩余共享积分{display_money(balance)}", 'SCORE_REVIEW',
                      dict(requestId=r['id'], username=r['username'], action=r['action'], amount=r['amount'], balance=balance, status=r['status']))
            else:
                e.bot(r['game'],f"@{e.s['users'][r['username']]['nickname']} {r['action']}申请{r['status']}", template='rejected', variables={'昵称':e.s['users'][r['username']]['nickname'], '操作':r['action'], '金额':display_money(r['amount'])})
            return '审核完成'
        if path=='/api/admin/notice':
            text=str(d['text']).strip()
            if not text or len(text)>1000: raise ValueError('公告须为1至1000字')
            e.chat(key,text,kind='NOTICE'); return '本地公告已发布'
        raise ValueError('功能不存在')
