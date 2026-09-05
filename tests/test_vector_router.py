"""
VectorRouter 纯逻辑测试（不依赖数据库和 embedding 服务）
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from app.pipeline.router.vector import VectorRouter
from app.pipeline.config import RouterConfig


class TestExtractLatestUserMessage:
    def setup_method(self):
        self.router = VectorRouter(RouterConfig())

    def test_simple_user_message(self):
        messages = [{"role": "user", "content": "你好"}]
        assert self.router._extract_latest_user_message(messages) == "你好"

    def test_latest_user_message(self):
        messages = [
            {"role": "user", "content": "第一个问题"},
            {"role": "assistant", "content": "回答"},
            {"role": "user", "content": "第二个问题"},
        ]
        assert self.router._extract_latest_user_message(messages) == "第二个问题"

    def test_no_user_message(self):
        messages = [{"role": "assistant", "content": "回答"}]
        assert self.router._extract_latest_user_message(messages) == ""

    def test_multimodal_content(self):
        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": "看图说话"}, {"type": "image_url", "image_url": {"url": "x"}}]
        }]
        assert self.router._extract_latest_user_message(messages) == "看图说话"

    def test_empty_messages(self):
        assert self.router._extract_latest_user_message([]) == ""


class TestFindBestDomain:
    def setup_method(self):
        self.router = VectorRouter(RouterConfig())

    def _make_domain(self, name, vector):
        d = MagicMock()
        d.name = name
        d.embedding_vector = vector
        return d

    def test_finds_highest_similarity(self):
        domains = [
            self._make_domain("code", [1.0, 0.0, 0.0]),
            self._make_domain("general", [0.0, 1.0, 0.0]),
        ]
        # 用户向量接近 code
        user_vec = [0.9, 0.1, 0.0]
        best, score = self.router._find_best_domain(user_vec, domains)
        assert best == "code"
        assert score > 0.9

    def test_no_domains(self):
        best, score = self.router._find_best_domain([1.0, 0.0], [])
        assert best is None
        assert score == 0.0

    def test_domain_without_vector_skipped(self):
        domains = [
            self._make_domain("code", None),
            self._make_domain("general", [0.0, 1.0]),
        ]
        best, score = self.router._find_best_domain([0.0, 1.0], domains)
        assert best == "general"


class TestHysteresisDecision:
    def setup_method(self):
        config = RouterConfig(threshold_high=0.75, threshold_low=0.60, fallback_domain="general")
        self.router = VectorRouter(config)

    def _make_domain(self, name, vector):
        d = MagicMock()
        d.name = name
        d.embedding_vector = vector
        return d

    def test_switch_when_above_high_threshold(self):
        """最高相似度超过 high 阈值，切换"""
        domains = [self._make_domain("code", [1.0, 0.0])]
        result = self.router._hysteresis_decision("code", 0.85, None, domains)
        assert result == "code"

    def test_no_switch_below_high_threshold(self):
        """最高相似度低于 high 阈值且无当前领域，用 fallback"""
        domains = [self._make_domain("code", [1.0, 0.0])]
        result = self.router._hysteresis_decision("code", 0.50, None, domains)
        assert result == "general"  # fallback

    def test_keep_current_domain_above_low_threshold(self):
        """当前领域相似度高于 low 阈值，且新领域未超 high 阈值，保持当前"""
        domains = [
            self._make_domain("code", [1.0, 0.0]),
            self._make_domain("general", [0.0, 1.0]),
        ]
        # 当前 general，用户向量接近 general（0.65 > low 0.60），新领域 code=0.70 < high 0.75，保持
        self.router._last_user_vector = [0.1, 0.9]
        result = self.router._hysteresis_decision("code", 0.70, "general", domains)
        assert result == "general"

    def test_switch_when_new_domain_above_high_threshold(self):
        """新领域相似度超过 high 阈值，即使当前领域 >= low，也强制切换"""
        domains = [
            self._make_domain("code", [1.0, 0.0]),
            self._make_domain("general", [0.0, 1.0]),
        ]
        # 当前 general（0.65 > low），但 code=0.80 >= high 0.75，强制切换
        self.router._last_user_vector = [0.1, 0.9]
        result = self.router._hysteresis_decision("code", 0.80, "general", domains)
        assert result == "code"

    def test_no_candidate_returns_fallback(self):
        result = self.router._hysteresis_decision(None, 0.0, None, [])
        assert result == "general"
