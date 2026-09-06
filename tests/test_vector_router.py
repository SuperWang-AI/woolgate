"""
VectorRouter 纯逻辑测试（不依赖数据库和 embedding 服务）
M4 重构后：从领域向量路由改为模型能力向量路由
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


class TestFindBestModel:
    def setup_method(self):
        self.router = VectorRouter(RouterConfig())

    def _make_model(self, name, vector):
        m = MagicMock()
        m.model_name = name
        m.embedding_vector = vector
        return m

    def test_finds_highest_similarity(self):
        models = [
            self._make_model("qwen-plus", [1.0, 0.0, 0.0]),
            self._make_model("kimi-k2.6", [0.0, 1.0, 0.0]),
        ]
        # 用户向量接近 qwen-plus
        user_vec = [0.9, 0.1, 0.0]
        best, score = self.router._find_best_model(user_vec, models)
        assert best == "qwen-plus"
        assert score > 0.9

    def test_no_models(self):
        best, score = self.router._find_best_model([1.0, 0.0], [])
        assert best is None
        assert score == 0.0

    def test_model_without_vector_skipped(self):
        models = [
            self._make_model("qwen-plus", None),
            self._make_model("kimi-k2.6", [0.0, 1.0]),
        ]
        best, score = self.router._find_best_model([0.0, 1.0], models)
        assert best == "kimi-k2.6"


class TestHysteresisDecision:
    def setup_method(self):
        config = RouterConfig(threshold_high=0.65, threshold_low=0.55, fallback_model="kimi-k2.6")
        self.router = VectorRouter(config)

    def _make_model(self, name, vector):
        m = MagicMock()
        m.model_name = name
        m.embedding_vector = vector
        return m

    def test_switch_when_above_high_threshold(self):
        """最高相似度超过 high 阈值，切换"""
        models = [self._make_model("qwen-plus", [1.0, 0.0])]
        result = self.router._hysteresis_decision("qwen-plus", 0.75, None, models)
        assert result == "qwen-plus"

    def test_no_current_model_returns_best(self):
        """无当前模型时，直接返回最优模型（不做滞回）"""
        models = [self._make_model("qwen-plus", [1.0, 0.0])]
        result = self.router._hysteresis_decision("qwen-plus", 0.50, None, models)
        assert result == "qwen-plus"

    def test_keep_current_model_above_low_threshold(self):
        """当前模型相似度高于 low 阈值，且新模型未超 high 阈值，保持当前"""
        models = [
            self._make_model("qwen-plus", [1.0, 0.0]),
            self._make_model("kimi-k2.6", [0.0, 1.0]),
        ]
        # 当前 kimi，用户向量接近 kimi（0.65 > low 0.55），新模型 qwen=0.60 < high 0.65，保持
        self.router._last_user_vector = [0.1, 0.9]
        result = self.router._hysteresis_decision("qwen-plus", 0.60, "kimi-k2.6", models)
        assert result == "kimi-k2.6"

    def test_switch_when_new_model_above_high_threshold(self):
        """新模型相似度超过 high 阈值，即使当前模型 >= low，也强制切换"""
        models = [
            self._make_model("qwen-plus", [1.0, 0.0]),
            self._make_model("kimi-k2.6", [0.0, 1.0]),
        ]
        # 当前 kimi（0.65 > low），但 qwen=0.80 >= high 0.65，强制切换
        self.router._last_user_vector = [0.1, 0.9]
        result = self.router._hysteresis_decision("qwen-plus", 0.80, "kimi-k2.6", models)
        assert result == "qwen-plus"

    def test_no_candidate_returns_fallback(self):
        result = self.router._hysteresis_decision(None, 0.0, None, [])
        assert result == "kimi-k2.6"
