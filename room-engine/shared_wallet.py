"""One authoritative member balance, with read-compatible room mirrors."""
import copy
import secrets
import time


VERSION = 1


def set_balance(user, amount, games):
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ValueError('共享积分余额无效')
    user['balance'] = amount
    user['walletVersion'] = VERSION
    user['wallets'] = {game: amount for game in games}


def initialize(engine, policy='sum', save=True):
    """Convert legacy room balances once. Preserve old ledger rows byte-for-byte."""
    if policy not in (None, 'sum'):
        raise ValueError('共享积分迁移仅支持已确认的三房间余额求和策略')
    with engine.lock:
        previous = copy.deepcopy(engine.s)
        state = engine.s
        games = tuple(state['games'])
        if not games:
            raise ValueError('房间配置缺失，不能迁移积分')
        changed = state.get('sharedWalletVersion') != VERSION
        converted = 0
        try:
            ledger_totals = dict(state.get('ledgerOpening', {}))
            if any(type(value) is not int for value in ledger_totals.values()):
                raise ValueError('账本期初汇总记录损坏，请从备份核对')
            for entry in state['ledger']:
                ledger_totals[entry['username']] = ledger_totals.get(entry['username'], 0) + entry['delta']
            for name, user in state['users'].items():
                already_shared = user.get('walletVersion') == VERSION
                if already_shared:
                    amount = user.get('balance')
                    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
                        raise ValueError('共享积分记录损坏，请从备份核对')
                    if user.get('wallets') != {game: amount for game in games}:
                        set_balance(user, amount, games)
                        changed = True
                    # Never reconcile old mirror edits or re-sum them after migration.
                    if state.get('sharedWalletVersion') == VERSION:
                        if ledger_totals.get(name, 0) != amount:
                            raise ValueError('共享积分与账本不一致，请保留数据并核对备份，不能重复迁移')
                        continue
                else:
                    original = {game: user.get('wallets', {}).get(game, 0) for game in games}
                    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in original.values()):
                        raise ValueError('旧房间积分记录无效，请先核对数据')
                    amount = sum(original.values())
                    user['walletMigration'] = dict(version=VERSION, policy='sum',
                        time=time.strftime('%Y-%m-%d %H:%M:%S'), originalWallets=original,
                        mergedBalance=amount, previousLedgerTotal=ledger_totals.get(name, 0))
                    set_balance(user, amount, games)
                    converted += 1
                    changed = True
                delta = amount - ledger_totals.get(name, 0)
                if delta:
                    state['ledger'].append(dict(id=secrets.token_hex(8), username=name, game=games[0],
                        delta=delta, balance=amount, walletScope='shared',
                        reason='共享积分迁移期初差额', ref='shared-wallet-v1-opening',
                        time=time.strftime('%Y-%m-%d %H:%M:%S'), source='migration',
                        simulated=bool(user.get('robot'))))
                    changed = True
                if not already_shared:
                    state['ledger'].append(dict(id=secrets.token_hex(8), username=name, game=games[0],
                        delta=0, balance=amount, walletScope='shared',
                        reason='三房间积分合并（原余额已留档）', ref='shared-wallet-v1',
                        time=time.strftime('%Y-%m-%d %H:%M:%S'), source='migration',
                        simulated=bool(user.get('robot'))))
            state['sharedWalletVersion'] = VERSION
            if 'sharedWalletMigration' not in state:
                state['sharedWalletMigration'] = dict(version=VERSION, policy='sum',
                    time=time.strftime('%Y-%m-%d %H:%M:%S'), convertedUsers=converted,
                    note='余额为单一共享值；wallets仅为兼容镜像，禁止再次累加。旧账本按原样保留。')
                changed = True
            if changed and save:
                engine.save()
        except Exception:
            engine.s = previous
            raise
        return changed
