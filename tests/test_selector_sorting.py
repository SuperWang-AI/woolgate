# -*- coding: utf-8 -*-
"""A4-4 选号排序单测：cost-first（免费→比价→余额→id降序）+ free-first 兜底"""
import pytest
from app.models.database import ModelAccount
from app.pipeline.selector.cost_first import CostFirstSelector
from app.pipeline.selector.free_first import FreeFirstSelector


def mk(id_: int, model="deepseek-chat", inp=None, out=None, bal=None, priority=50, vendor="x"):
    """构造账号（默认 priority=50，与退场后的默认值一致）"""
    a = ModelAccount(id=id_, vendor=vendor, default_model_name=model, priority=priority)
    a._cost_input = inp
    a._cost_output = out
    a.balance_remaining = bal
    return a


def pick(accounts, model="deepseek-chat"):
    return CostFirstSelector().select(accounts, model_name=model)


class TestCostFirst:
    def test_free_first(self):
        """免费(0/0) 优先于 有价(1.0)"""
        accs = [mk(1, inp=1.0, out=2.0), mk(2, inp=0.0, out=0.0)]
        assert pick(accs).id == 2

    def test_unknown_price_last(self):
        """排序：免费 < 有价 < 未知"""
        accs = [mk(1, inp=None, out=None), mk(2, inp=0.5, out=1.0), mk(3, inp=0.0, out=0.0)]
        assert [a.id for a in sorted(accs, key=CostFirstSelector()._rank)] == [3, 2, 1]
        assert pick(accs).id == 3

    def test_cheaper_wins(self):
        """同模型比价：低价账号优先"""
        accs = [mk(1, inp=2.0, out=4.0), mk(2, inp=0.3, out=0.6)]
        assert pick(accs).id == 2

    def test_balance_tiebreak(self):
        """同价时余额多者优先"""
        accs = [mk(1, inp=0.0, out=0.0, bal=1.0), mk(2, inp=0.0, out=0.0, bal=88.0)]
        assert pick(accs).id == 2

    def test_id_desc_last(self):
        """全同分时 id 降序（新账号优先）"""
        accs = [mk(5, inp=0.0, out=0.0, bal=1.0), mk(9, inp=0.0, out=0.0, bal=1.0)]
        assert pick(accs).id == 9

    def test_filter_by_model(self):
        """指定模型时只从匹配账号中选；无匹配回退全部"""
        accs = [mk(1, model="deepseek-chat", inp=1.0, out=2.0), mk(2, model="qwen-plus", inp=0.0, out=0.0)]
        # 匹配 deepseek-chat 的只有 id=1
        assert pick(accs, model="deepseek-chat").id == 1
        # 无匹配 → 回退全部 → 免费 id=2 胜
        assert pick(accs, model="nonexistent").id == 2

    def test_empty(self):
        assert pick([]) is None


class TestFreeFirst:
    def test_priority_then_id_desc(self):
        """priority 全默认时退化为 id 降序（新账号优先）"""
        accs = [mk(3), mk(8)]
        sel = FreeFirstSelector().select(accs, model_name="deepseek-chat")
        assert sel.id == 8

    def test_priority_still_wins(self):
        """历史数据 priority 仍生效（高者优先）"""
        accs = [mk(3, priority=20), mk(8, priority=90)]
        sel = FreeFirstSelector().select(accs, model_name="deepseek-chat")
        assert sel.id == 8
