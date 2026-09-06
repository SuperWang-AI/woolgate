"""
摘要压缩策略（summary）

当对话超过阈值时，用摘要模型将历史压缩为一段摘要，
保留最近几轮 + 系统摘要，减少 token 消耗。
M2 实现同步摘要（请求时计算），M3 做异步预计算。

摘要模型支持两种：
- cloud：从账号池选指定模型的启用账号，通过 LLMClient 调用
- local：调用 Ollama 本地模型
"""
import logging
import time
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.context_manager.base import ContextManager
from app.pipeline.config import ContextConfig
from app.models.database import ModelAccount

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext, SessionState

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = (
    "请将以下对话历史压缩为一段简洁的摘要，保留关键信息、用户核心需求和上下文脉络，"
    "不超过 500 字。只输出摘要内容，不要解释。\n\n对话历史：\n{history}"
)


class SummaryManager(ContextManager):
    """摘要压缩：历史摘要 + 最近轮次原文"""

    name = "summary"

    def __init__(self, config: ContextConfig, db: Optional[AsyncSession] = None):
        self.config = config
        self.db = db

    async def assemble(
        self,
        ctx: "PipelineContext",
        session: Optional["SessionState"] = None,
    ) -> List[Dict[str, Any]]:
        """组装消息：超过阈值时触发摘要，否则直传"""
        start = time.time()
        ctx.context_strategy = self.name

        messages = ctx.original_messages
        turn_count = self._count_turns(messages)
        est_tokens = self._estimate_tokens(messages)

        # 模型切换时强制摘要（即使未达阈值），确保新模型获得压缩后的上下文
        force_summary = getattr(ctx, "model_switched", False)

        # 未达阈值且非跨语义切换，直传
        if not force_summary and (turn_count < self.config.summary_trigger_turns and
                est_tokens < self.config.summary_trigger_tokens):
            ctx.assembled_messages = list(messages)
            ctx.summary_used = False
            ctx.context_latency_ms = int((time.time() - start) * 1000)
            return ctx.assembled_messages

        # 达到阈值，触发摘要
        try:
            # 分离当前请求和历史
            current_request = messages[-1] if messages else None
            history = messages[:-1] if len(messages) > 1 else []

            # 生成摘要（优先复用 session 中的旧摘要 + 增量，M2 先全量摘要）
            summary_text = await self._generate_summary(history)

            # 保留最近 N 轮原文
            window_turns = self.config.summary_window_turns
            recent_messages = self._take_recent_turns(history, window_turns)

            # 组装：系统提示（含摘要）+ 最近轮次 + 当前请求
            assembled = []
            if summary_text:
                assembled.append({
                    "role": "system",
                    "content": f"[对话历史摘要]\n{summary_text}",
                })
            assembled.extend(recent_messages)
            if current_request:
                assembled.append(current_request)

            ctx.assembled_messages = assembled
            ctx.summary_used = True
            logger.info(
                f"[summary] 触发摘要: 轮次={turn_count}, token≈{est_tokens}, "
                f"摘要后消息数={len(assembled)}"
            )
        except Exception as e:
            # 摘要失败，回退直传
            logger.error(f"[summary] 摘要失败，回退直传: {e}", exc_info=True)
            ctx.assembled_messages = list(messages)
            ctx.summary_used = False

        ctx.context_latency_ms = int((time.time() - start) * 1000)
        return ctx.assembled_messages

    async def _generate_summary(self, history: List[Dict[str, Any]]) -> str:
        """调用摘要模型生成摘要"""
        if not history:
            return ""

        history_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in history
            if isinstance(m.get("content"), str)
        )
        if not history_text:
            return ""

        prompt = SUMMARY_PROMPT.format(history=history_text[:8000])  # 限制摘要输入长度

        if self.config.summary_provider == "local":
            return await self._summarize_local(prompt)
        else:
            return await self._summarize_cloud(prompt)

    async def _summarize_cloud(self, prompt: str) -> str:
        """云端摘要：从账号池选指定模型的启用账号，调用 LLMClient"""
        if self.db is None:
            raise RuntimeError("云端摘要需要数据库会话")

        model_name = self.config.summary_model
        if not model_name:
            raise RuntimeError("未配置摘要模型（summary_model）")

        # 查找该模型的启用账号
        result = await self.db.execute(
            select(ModelAccount).where(
                ModelAccount.model_name == model_name,
                ModelAccount.is_enable == True,  # noqa: E712
            ).order_by(ModelAccount.priority.desc())
        )
        account = result.scalars().first()
        if not account:
            raise RuntimeError(f"未找到模型 {model_name} 的启用账号")

        # 调用 LLMClient 非流式
        from app.services.llm_client import LLMClient
        client = LLMClient()
        messages = [{"role": "user", "content": prompt}]
        resp = await client.chat_completion(account, messages, max_tokens=500)

        # 解析响应（OpenAI 兼容格式）
        if isinstance(resp, dict):
            choices = resp.get("choices", [])
            if choices and "message" in choices[0]:
                return choices[0]["message"].get("content", "").strip()
        return ""

    async def _summarize_local(self, prompt: str) -> str:
        """本地摘要：调用 Ollama"""
        import httpx
        model = self.config.summary_model or "qwen2.5:1.5b"
        url = "http://host.docker.internal:11434/api/generate"
        payload = {"model": model, "prompt": prompt, "stream": False}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data.get("response", "").strip()

    def _count_turns(self, messages: List[Dict[str, Any]]) -> int:
        """统计对话轮次（user 消息数）"""
        return sum(1 for m in messages if m.get("role") == "user")

    def _estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """估算 token 数（简单按字符数 *0.5）"""
        total = 0
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += len(content)
        return int(total * 0.5)

    def _take_recent_turns(self, messages: List[Dict[str, Any]], turns: int) -> List[Dict[str, Any]]:
        """取最近 N 轮对话（每轮 = user + assistant）"""
        if turns <= 0:
            return []
        # 从后往前数第 N 个 user 消息，从它开始截取
        user_count = 0
        cut_index = 0
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                user_count += 1
                if user_count == turns:
                    cut_index = i
                    break
        return messages[cut_index:]

    async def update_summary(
        self,
        session: "SessionState",
        messages: List[Dict[str, Any]],
        response: str,
    ) -> None:
        """M2 同步摘要已在 assemble 时完成，此处空实现（M3 异步预计算用）"""
        pass
