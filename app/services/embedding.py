"""
Embedding 服务——将文本转为向量，供 VectorRouter 做语义相似度计算。

支持两种后端：
- cloud（M2 实现）：阿里百炼 text-embedding-v3，OpenAI 兼容接口
- local（留接口）：Ollama embedding API，调用开源模型（nomic-embed-text 等）

统一接口：embed(text) -> List[float]
"""
import httpx
import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import ModelAccount
from app.pipeline.config import RouterConfig
from app.utils.encryption import encryption_service

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding 服务，根据 RouterConfig 选择后端"""

    def __init__(self, config: RouterConfig, db: Optional[AsyncSession] = None):
        self.config = config
        self.db = db
        self.timeout = httpx.Timeout(30.0, connect=10.0)
        # 复用连接（单进程单事件循环下安全）
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def embed(self, text: str) -> List[float]:
        """将文本转为向量"""
        if not text or not text.strip():
            return []

        backend = self.config.embedding_backend
        if backend == "cloud":
            return await self._embed_cloud(text)
        elif backend == "local":
            return await self._embed_local(text)
        else:
            raise ValueError(f"未知的 embedding 后端: {backend}")

    async def _embed_cloud(self, text: str) -> List[float]:
        """云端 embedding（根据ModelCatalog中的embedding模型配置）"""
        from app.models.database import ModelCatalog, ModelAccount

        api_key = ""
        base_url = self.config.embedding_cloud_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        model = self.config.embedding_cloud_model or "text-embedding-v3"

        # 使用embedding_model_id指定的模型（自动使用该模型所属账号的API Key）
        model_id = getattr(self.config, 'embedding_model_id', 0)
        if model_id and model_id > 0 and self.db is not None:
            result = await self.db.execute(
                select(ModelCatalog).where(ModelCatalog.id == model_id)
            )
            cat = result.scalar_one_or_none()
            if cat:
                model = cat.model_name
                # 获取关联账号的API Key
                if cat.account_id:
                    acc_result = await self.db.execute(
                        select(ModelAccount).where(ModelAccount.id == cat.account_id)
                    )
                    acc = acc_result.scalar_one_or_none()
                    if acc and acc.is_enable:
                        try:
                            api_key = encryption_service.decrypt(acc.api_key_encrypted)
                            # 注意：不要用账号的base_url（那是对话接口地址）
                            # Embedding用标准地址，从配置或默认值获取
                        except Exception:
                            pass

        # 兜底：自动选用第一个启用账号的阿里百炼 Key
        if not api_key:
            api_key = await self._find_aliyun_api_key()

        if not api_key:
            raise RuntimeError(
                "云端 embedding 未配置。请在管线策略页选择 embedding 模型，"
                "或启用一个阿里百炼账号。"
            )

        url = f"{base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": model, "input": text}

        resp = await self._client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        # 解析向量（OpenAI 兼容格式：data[0].embedding）
        try:
            embedding = data["data"][0]["embedding"]
            return [float(x) for x in embedding]
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"云端 embedding 响应解析失败: {data}, 错误: {e}")
            raise RuntimeError(f"云端 embedding 响应格式异常: {e}")

    async def _embed_local(self, text: str) -> List[float]:
        """
        本地 embedding（Ollama，留接口）。

        M2 阶段仅预留接口，实际调用需用户本地安装 Ollama 并拉取 embedding 模型。
        接口文档：POST http://localhost:11434/api/embeddings
        Body: {"model": "nomic-embed-text", "prompt": text}
        Response: {"embedding": [...]}
        """
        # 从 SystemConfig 的 ollama_base_url 读取（通过 RouterConfig 暂不直接访问，这里用默认）
        # TODO M3: 从配置注入 Ollama 地址，支持本地 embedding 模型选择
        ollama_url = "http://host.docker.internal:11434"
        model = self.config.embedding_local_plugin or "nomic-embed-text"

        if not self.config.embedding_local_installed:
            raise RuntimeError(
                f"本地 embedding 未启用。请在 Ollama 中拉取模型：`ollama pull {model}`，"
                f"然后在管线策略页将 embedding 后端设为 local 并标记已安装。"
            )

        url = f"{ollama_url.rstrip('/')}/api/embeddings"
        payload = {"model": model, "prompt": text}

        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        try:
            return [float(x) for x in data["embedding"]]
        except (KeyError, TypeError) as e:
            logger.error(f"本地 embedding 响应解析失败: {data}, 错误: {e}")
            raise RuntimeError(f"本地 embedding 响应格式异常: {e}")

    async def _find_aliyun_api_key(self) -> str:
        """从账号池找阿里百炼/通义千问的启用账号，借用其 API Key"""
        if self.db is None:
            return ""
        result = await self.db.execute(
            select(ModelAccount).where(
                ModelAccount.is_enable == True,  # noqa: E712
                ModelAccount.vendor.like("%百炼%"),
            )
        )
        accounts = result.scalars().all()
        for account in accounts:
            try:
                return encryption_service.decrypt(account.api_key_encrypted)
            except Exception:
                continue
        return ""


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
