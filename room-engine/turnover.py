"""Effective turnover per settled order, rounded half up to integer cents."""
import re

RULE_VERSION = 'play-turnover-v3'


def effective_turnover(order):
    amount = order.get('amount', 0)
    amount = max(0, amount) if type(amount) is int else 0
    if order.get('status') == '未中':
        return amount
    if order.get('status') != '中奖':
        return 0
    profit = order.get('profit', 0)
    profit = max(0, profit) if type(profit) is int else 0
    selection = str(order.get('selection', ''))
    if selection in ('大', '小', '单', '双', '小单', '小双', '大单', '大双'):
        return amount
    if re.fullmatch(r'[1-4]{2}无[1-4]|[1-4]通[1-4]{2}', selection):
        return (amount + 1) // 2
    if re.fullmatch(r'[1-4]{1,3}车', selection):
        return (amount + 1) // 3
    if re.fullmatch(r'[1-4]{1,3}(?:番|正)|[1-4]{2}角|[1-4]念[1-4]{1,2}|[1-4]无[1-4]', selection):
        return min(amount, profit + (amount + 10) // 20)
    # Special numbers and unclassified legacy plays keep their prior rule.
    return profit
