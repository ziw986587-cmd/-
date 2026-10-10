"""Per-room, plain-text robot templates. Templates never execute code."""
import copy
import re

TOKEN = re.compile(r'\{([^{}]+)\}')
COMMON = {'房间': '加拿大28', '期号': 'L002130', '原文': '系统原有回复内容'}


def catalog(game):
    rows = []
    def add(key, title, phase, text, **sample):
        rows.append(dict(key=key, title=title, phase=phase, default=text,
                         sample={**COMMON, '房间': {'canada28':'加拿大28','australia8':'澳洲8','australia8ball':'澳洲3'}[game], **sample}))
    add('draw', '开奖信息', '01 开奖与结算', '{期号}期开奖结果：{号码}', 号码='9,5,5', 番数='3', 形态='单,大', 开奖来源='外部开奖源')
    add('winners', '获胜名单', '01 开奖与结算', '------------\n{期号}结果：\n{号码}\n=> {番数},{形态}\n获胜名单：\n{获胜名单}\n（盈为该获胜注单净盈利，不含本金）',
        号码='9,5,5', 番数='3', 形态='单,大', 获胜名单='(小明)\n　“大/100” 盈：97')
    add('ranking', '共享积分总榜', '01 开奖与结算', '共享积分总榜\n{积分榜}', 积分榜='小明 [1097] (+97)\n小红 [900] (-100)')
    add('open', '历史参考与开盘', '02 开盘', '历史参考：\n{历史参考}\n---------------\n{期号}{开盘状态}', 历史参考='1 - 2 - 3 - 4', 开盘状态='期开始攻击')
    add('receipt', '下注成功', '03 下注与积分操作', '@{昵称}，{球位}攻击[{下注内容}]成功\n共享积分：{余额}', 昵称='小明', 球位='第8球 ' if game=='australia8' else '', 下注内容='大100', 余额='900')
    add('cancel', '退单成功', '03 下注与积分操作', '@{昵称} 已退 {笔数} 条，返还 {金额} 积分', 昵称='小明', 笔数='1', 金额='100')
    for action, prefix in [('上分','up'), ('下分','down')]:
        add(prefix+'_request', action+'申请', '03 下注与积分操作', '@{昵称}'+action+'{金额}，待管理员审核请稍后', 昵称='小明', 金额='100')
        add(prefix+'_success', action+'成功（审核或后台直接调整）', '03 下注与积分操作', '@{昵称} '+action[0]+'{金额}成功，剩余共享积分{余额}', 昵称='小明', 金额='100', 余额='600')
    add('rejected', '上下分审核拒绝', '03 下注与积分操作', '@{昵称} {操作}申请已拒绝', 昵称='小明', 操作='下分', 金额='100')
    add('balance', '查询余额与有效流水', '03 下注与积分操作', '共享积分：{余额}\n当局下注明细（{期号}期）：\n{当局下注明细}\n合计：{当局下注金额}（{笔数}笔）\n累计盈亏：{累计盈亏}\n有效流水：{有效流水}', 昵称='小明', 余额='900', 当局下注明细=('第8球 ' if game=='australia8' else '')+'1番：100', 当局下注金额='100', 笔数='1', 累计盈亏='97', 有效流水='97', 累计流水='97')
    add('help', '帮助指令', '03 下注与积分操作', '指令：查、退（或退单、取消）、帮助、上500（或上分500）、下500（或下分500）\n上下分提交申请后须等待管理员审核，金额最多两位小数。\n注单示例：1番100、12角50、1念2/30、12无3/20、1通23/20{房间规则}\n本地规则与赔率见“规则与赔率”。', 房间规则='；下注金额必须为正整数。')
    if game=='australia8':
        add('a8_warning', '封盘前提示及三段限额', '04 封盘', '离封盘还剩{剩余秒数}秒！\n60秒以内禁止取消\n开奖后0至{切换秒数}秒单注最高：{前段限额}\n开奖后{切换秒数}至{第三段起始秒数}秒，单个用户本期所有玩法累计最高：{后段限额}\n开奖后{第三段起始秒数}秒起至封盘，单个用户本期所有玩法累计最高：{第三段累计限额}', 剩余秒数='60', 切换秒数='60', 前段限额='1000', 后段限额='100', 第三段起始秒数='290', 第三段累计限额='500')
    else:
        add('warning', '开奖倒计时提醒', '04 封盘', '还有 {剩余秒数} 秒开奖', 剩余秒数='60')
    add('close', '封盘及核对列表', '04 封盘', '{期号}期已封盘\n---------------\n{期号}期核对列表\n{核对列表}\n---------------\n以系统注单记录和退单状态为准。{封盘附加信息}', 核对列表='(小明) “大100, 1番50”', 封盘附加信息='')
    add('admin_refund', '管理员全部退单', '05 管理员操作', '管理员已退还本房间全部待开奖注单。')
    add('force_refund', '强制开盘退单', '05 管理员操作', '管理员强制开盘：已退还待开奖注单{笔数}笔，本金{金额}积分。', 笔数='2', 金额='200')
    add('force_open', '管理员强制开盘', '05 管理员操作', '{期号}期开始攻击\n管理员强制开盘，倒计时为人工估算，以开奖源实际结果为准。')
    add('ready', '房间初始化', '05 管理员操作', '本地房间已就绪。\n{期号}期开始攻击\n{房间说明}', 房间说明='房间已就绪，等待开奖。')
    return rows


def balance_template(text):
    """Upgrade the old amount token without overwriting saved custom wording."""
    return text.replace('{当局下注}', '{当局下注明细}').replace('当局下注（', '当局下注明细（')


def config(engine, game):
    room = engine.game(game)
    saved = room.get('robotMessages', {})
    return dict(game=game, revision=room.get('robotRevision', 0), bot=room['bot'],
                name=room.get('robotName', '机器人'), entries=[{**row, **saved.get(row['key'], {}),
                'enabled': saved.get(row['key'], {}).get('enabled', True),
                'text': balance_template(saved.get(row['key'], {}).get('text', row['default'])) if row['key']=='balance' else saved.get(row['key'], {}).get('text', row['default'])} for row in catalog(game)])


def save(engine, game, data):
    room = engine.game(game)
    if type(data.get('revision')) is not int or data['revision'] != room.get('robotRevision', 0):
        raise ValueError('机器人设置已被修改，请重新打开后编辑')
    if type(data.get('bot')) is not bool:
        raise ValueError('机器人总开关无效')
    name = data.get('name')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 20 or '\n' in name or '\r' in name:
        raise ValueError('机器人名称须为1至20字')
    entries = data.get('entries')
    definitions = {r['key']: r for r in catalog(game)}
    if not isinstance(entries, dict) or set(entries) != set(definitions):
        raise ValueError('回复项目不完整，请重新打开设置')
    saved = {}
    for key, row in definitions.items():
        value = entries[key]
        if not isinstance(value, dict) or type(value.get('enabled')) is not bool:
            raise ValueError(row['title']+'：开关无效')
        text = value.get('text')
        if not isinstance(text, str) or not text.strip() or len(text)>2000:
            raise ValueError(row['title']+'：回复须为1至2000字，暂停回复请关闭开关')
        text = text.replace('\r\n','\n').replace('\r','\n')
        if key == 'balance': text = balance_template(text)
        if any(token not in row['sample'] for token in TOKEN.findall(text)) or re.search(r'[{}]', TOKEN.sub('',text)):
            raise ValueError(row['title']+'：包含未知或不完整占位符，请使用下方提供的占位符')
        if text != row['default'] or not value['enabled']:
            saved[key] = dict(text=text, enabled=value['enabled'])
    # Commit only after all templates have been validated.
    room.update(robotMessages=saved, robotName=name.strip(), bot=data['bot'], robotRevision=data['revision']+1)
    return dict(message='机器人设置已保存，将用于本房间之后的新回复')


def expand(text, values):
    # Single substitution pass: braces in a nickname cannot become another token.
    return TOKEN.sub(lambda match: str(values[match[1]]), text)


def render(engine, game, key, text, details, variables):
    row = engine.game(game).get('robotMessages', {}).get(key)
    if row and not row.get('enabled', True):
        return None
    if not row:
        return text, details
    default = next(r['default'] for r in catalog(game) if r['key']==key)
    template = balance_template(row['text']) if key == 'balance' else row['text']
    if template == default:
        return text, details
    values = {'原文':text, '期号':engine.game(game)['issue'], '房间':engine.game(game)['name'].replace('后2',''), **(variables or {})}
    result = expand(template, values)
    metadata = {**(copy.deepcopy(details) if details else {}), 'robotTemplate':key}
    # Preserve the exact nickname token positions for public display, even in
    # custom replies without @ or punctuation. Keep the saved/admin text intact.
    if '昵称' in values and '{昵称}' in template:
        parts, last = [], 0
        for match in TOKEN.finditer(template):
            parts.append(template[last:match.start()])
            parts.append({'nickname':str(values['昵称'])} if match[1]=='昵称' else str(values[match[1]]))
            last = match.end()
        parts.append(template[last:])
        metadata['publicNameParts'] = parts
    return result, metadata


def settlement_values(details, game, money):
    draw = details['draw']
    numbers = draw['numbers']
    value = numbers[-1] if game=='australia8' else sum(numbers)
    groups = {}
    for order in details['winningOrders']:
        groups.setdefault(order['username'], []).append(order)
    lines = []
    for orders in groups.values():
        lines.append('('+orders[0]['nickname']+')')
        for order in orders:
            prefix = '第'+str(order['ball'])+'球/' if game=='australia8' else ''
            lines.append('　“'+prefix+order['selection']+'/'+money(order['amount'])+'” 盈：'+money(order['profit']))
    return {'期号':details['issue'], '号码':','.join(str(n).zfill(2) if game=='australia8' else str(n) for n in numbers),
            '番数':str(draw['fan']), '形态':('单' if value%2 else '双')+','+('大' if value>=(11 if game=='australia8' else 14) else '小'),
            '获胜名单':'\n'.join(lines) or '本期暂无获胜注单'}
