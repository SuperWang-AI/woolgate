"""
WindowManager 测试
"""
import pytest
from app.pipeline.context_manager.window import WindowManager
from app.pipeline.context import PipelineContext


def _make_ctx(messages):
    return PipelineContext(
        request_id="test", client_ip="127.0.0.1", stream=False,
        original_messages=messages, requested_model="chat",
        kwargs={}, estimated_tokens=10,
    )


def _make_messages(n_turns):
    msgs = []
    for i in range(n_turns):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    return msgs


class TestWindowManager:
    @pytest.mark.asyncio
    async def test_passthrough_when_under_limit(self):
        """低于窗口大小时直传"""
        mgr = WindowManager(window_turns=10)
        messages = _make_messages(3)
        ctx = _make_ctx(messages)
        result = await mgr.assemble(ctx)
        assert result == messages
        assert ctx.summary_used is False

    @pytest.mark.asyncio
    async def test_truncate_when_over_limit(self):
        """超过窗口大小时截断到最近 N 轮"""
        mgr = WindowManager(window_turns=2)
        messages = _make_messages(5)  # 10 条消息
        ctx = _make_ctx(messages)
        result = await mgr.assemble(ctx)
        assert len(result) == 4  # 2 轮 = 4 条
        assert result[0]["content"] == "q3"  # 倒数第 2 轮开始

    @pytest.mark.asyncio
    async def test_exact_limit(self):
        """恰好等于窗口大小时不截断"""
        mgr = WindowManager(window_turns=3)
        messages = _make_messages(3)
        ctx = _make_ctx(messages)
        result = await mgr.assemble(ctx)
        assert len(result) == 6

    @pytest.mark.asyncio
    async def test_empty_messages(self):
        """空消息不报错"""
        mgr = WindowManager(window_turns=10)
        ctx = _make_ctx([])
        result = await mgr.assemble(ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_domain_switch_warning(self):
        """跨语义切换时记录 warning（不改变行为）"""
        mgr = WindowManager(window_turns=10)
        messages = _make_messages(2)
        ctx = _make_ctx(messages)
        ctx.domain_switched = True
        result = await mgr.assemble(ctx)
        assert result == messages  # window 策略仍只做截断
