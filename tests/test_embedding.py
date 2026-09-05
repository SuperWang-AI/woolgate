"""
Embedding 服务测试
"""
import pytest
from app.services.embedding import cosine_similarity, EmbeddingService
from app.pipeline.config import RouterConfig


class TestCosineSimilarity:
    def test_identical_vectors(self):
        """相同向量相似度为 1.0"""
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        """正交向量相似度为 0.0"""
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        """相反向量相似度为 -1.0"""
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_empty_vectors(self):
        """空向量返回 0.0"""
        assert cosine_similarity([], [1.0]) == 0.0
        assert cosine_similarity([1.0], []) == 0.0

    def test_length_mismatch(self):
        """长度不匹配返回 0.0"""
        assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_zero_vector(self):
        """零向量返回 0.0"""
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_similar_vectors(self):
        """相似向量相似度高"""
        v1 = [1.0, 0.8, 0.2]
        v2 = [0.9, 0.7, 0.3]
        sim = cosine_similarity(v1, v2)
        assert sim > 0.95


class TestEmbeddingService:
    def test_init_with_cloud_config(self):
        """云端配置初始化"""
        config = RouterConfig(embedding_backend="cloud")
        service = EmbeddingService(config)
        assert service.config.embedding_backend == "cloud"

    def test_init_with_local_config(self):
        """本地配置初始化"""
        config = RouterConfig(embedding_backend="local")
        service = EmbeddingService(config)
        assert service.config.embedding_backend == "local"

    @pytest.mark.asyncio
    async def test_embed_empty_text(self):
        """空文本返回空列表"""
        config = RouterConfig(embedding_backend="cloud")
        service = EmbeddingService(config)
        result = await service.embed("")
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_whitespace_text(self):
        """纯空白文本返回空列表"""
        config = RouterConfig(embedding_backend="cloud")
        service = EmbeddingService(config)
        result = await service.embed("   ")
        assert result == []

    @pytest.mark.asyncio
    async def test_unknown_backend_raises(self):
        """未知后端抛出 ValueError"""
        config = RouterConfig(embedding_backend="unknown")
        service = EmbeddingService(config)
        with pytest.raises(ValueError, match="未知的 embedding 后端"):
            await service.embed("test")
