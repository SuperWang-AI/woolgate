"""
SummaryManager 纯逻辑测试（不依赖数据库和 LLM 调用）
"""
import pytest
from app.pipeline.context_manager.summary import SummaryManager
from app.pipeline.config import ContextConfig


class TestCountTurns:
    def setup_method(self):
        self.mgr = SummaryManager(ContextConfig())

    def test_single_turn(self):
        messages = [{"role": "user", "content": "hi"}]
        assert self.mgr._count_turns(messages) == 1

    def test_multi_turn(self):
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        assert self.mgr._count_turns(messages) == 2

    def test_no_user(self):
        messages = [{"role": "assistant", "content": "a1"}]
        assert self.mgr._count_turns(messages) == 0

    def test_empty(self):
        assert self.mgr._count_turns([]) == 0


class TestEstimateTokens:
    def setup_method(self):
        self.mgr = SummaryManager(ContextConfig())

    def test_simple(self):
        messages = [{"role": "user", "content": "hello"}]
        assert self.mgr._estimate_tokens(messages) == 2  # 5 chars * 0.5

    def test_empty(self):
        assert self.mgr._estimate_tokens([]) == 0


class TestTakeRecentTurns:
    def setup_method(self):
        self.mgr = SummaryManager(ContextConfig())

    def _make_messages(self, n_turns):
        msgs = []
        for i in range(n_turns):
            msgs.append({"role": "user", "content": f"q{i}"})
            msgs.append({"role": "assistant", "content": f"a{i}"})
        return msgs

    def test_take_1_turn(self):
        msgs = self._make_messages(3)
        result = self.mgr._take_recent_turns(msgs, 1)
        assert len(result) == 2  # 最后一轮 user+assistant
        assert result[0]["content"] == "q2"

    def test_take_2_turns(self):
        msgs = self._make_messages(3)
        result = self.mgr._take_recent_turns(msgs, 2)
        assert len(result) == 4
        assert result[0]["content"] == "q1"

    def test_take_more_than_available(self):
        msgs = self._make_messages(2)
        result = self.mgr._take_recent_turns(msgs, 10)
        assert len(result) == 4  # 全部返回

    def test_zero_turns(self):
        msgs = self._make_messages(3)
        result = self.mgr._take_recent_turns(msgs, 0)
        assert result == []


class TestSummaryTrigger:
    """测试摘要触发阈值判断（通过 assemble 的间接逻辑）"""

    @pytest.mark.asyncio
    async def test_below_threshold_passthrough(self):
        """低于阈值时直传，不触发摘要"""
        config = ContextConfig(summary_trigger_turns=20, summary_trigger_tokens=4000)
        mgr = SummaryManager(config)
        from app.pipeline.context import PipelineContext
        ctx = PipelineContext(
            request_id="test", client_ip="127.0.0.1", stream=False,
            original_messages=[{"role": "user", "content": "hi"}],
            requested_model="chat", kwargs={}, estimated_tokens=10,
        )
        result = await mgr.assemble(ctx)
        assert result == ctx.original_messages
        assert ctx.summary_used is False
