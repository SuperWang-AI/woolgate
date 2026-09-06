"""
LLM 智能路由策略（llm）—— M4 新增

用便宜快速的小模型分析用户请求，直接推荐最合适的模型。
作为向量路由的兜底增强：向量低置信度时升级到 LLM 路由。

输入：用户消息 + 模型能力清单（含成本、延迟）
输出：推荐模型 + 理由 + 置信度
"""
import json
import logging
import time
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.router.base import ModelRouter
from app.services.model_catalog_service import ModelCatalogService

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext
    from app.pipeline.config import RouterConfig

logger = logging.getLogger(__name__)


class LLMRouter(ModelRouter):
    """LLM 智能路由：小模型分析请求，推荐最合适的模型"""

    name = "llm"

    def __init__(self, config: "RouterConfig", db: Optional[AsyncSession] = None):
        self.config = config
        self.db = db
        self._router_model: Optional[str] = None

    async def _get_router_model(self) -> str:
        """
        获取路由用的小模型。
        优先级：
        1. 配置中指定的 router_model
        2. 自动选最便宜最快的启用模型
        3. fallback_model
        """
        if self._router_model:
            return self._router_model

        # 配置中指定了路由模型
        if hasattr(self.config, 'router_model') and self.config.router_model:
            self._router_model = self.config.router_model
            return self._router_model

        # 自动选：从启用模型中选成本最低的
        if self.db:
            catalog_svc = ModelCatalogService(self.db)
            models = await catalog_svc.list_active_models()
            if models:
                # 按输入价格排序，选最便宜的
                models_with_price = [m for m in models if m.input_price is not None]
                if models_with_price:
                    cheapest = min(models_with_price, key=lambda m: m.input_price)
                    self._router_model = cheapest.model_name
                    logger.info(f"[llm-router] 自动选择路由模型: {self._router_model}")
                    return self._router_model
                # 没有价格信息，选第一个
                self._router_model = models[0].model_name
                return self._router_model

        self._router_model = self.config.fallback_model
        return self._router_model

    async def route(self, ctx: "PipelineContext") -> None:
        """执行 LLM 智能路由决策"""
        start = time.time()
        ctx.router_strategy = self.name

        if self.db is None:
            ctx.target_model = self.config.fallback_model
            ctx.router_decision = "llm: 无数据库会话，使用 fallback"
            ctx.router_latency_ms = int((time.time() - start) * 1000)
            return

        try:
            # 斜杠命令强制指定模型（最高优先级，不应该走到这里，但做防御）
            if ctx.forced_model:
                ctx.target_model = ctx.forced_model
                ctx.router_decision = f"llm: 斜杠命令强制模型={ctx.forced_model}"
                ctx.router_latency_ms = int((time.time() - start) * 1000)
                return

            # 1. 提取用户消息和对话上下文
            user_text = self._extract_latest_user_message(ctx.original_messages)
            context_summary = self._extract_context_summary(ctx.original_messages)
            if not user_text:
                target_model = ctx.default_model or self.config.fallback_model
                ctx.target_model = target_model
                ctx.router_decision = f"llm: 无用户消息，使用默认模型={target_model}"
                ctx.router_latency_ms = int((time.time() - start) * 1000)
                return

            # 2. 获取启用的模型清单
            catalog_svc = ModelCatalogService(self.db)
            models = await catalog_svc.list_active_models()
            if not models:
                target_model = ctx.default_model or self.config.fallback_model
                ctx.target_model = target_model
                ctx.router_decision = f"llm: 无可用模型，使用默认模型={target_model}"
                ctx.router_latency_ms = int((time.time() - start) * 1000)
                return

            # 3. 构建 LLM 路由 prompt（包含上下文）
            prompt = self._build_routing_prompt(user_text, models, context_summary)

            # 4. 调用路由模型
            router_model = await self._get_router_model()
            recommendation = await self._call_router_model(router_model, prompt)

            # 5. 解析推荐结果
            target_model = self._parse_recommendation(recommendation, models)
            reason = recommendation.get("reason", "") if isinstance(recommendation, dict) else ""

            ctx.target_model = target_model
            ctx.router_decision = f"llm: 模型={target_model}, 理由={reason}"
            ctx.router_confidence = recommendation.get("confidence", 0.8) if isinstance(recommendation, dict) else 0.8
            logger.info(f"[llm-router] 路由决策: 模型={target_model}, 理由={reason}")

        except Exception as e:
            logger.error(f"[llm-router] 路由异常: {e}", exc_info=True)
            # LLM 路由失败，降级到 fallback
            target_model = getattr(ctx, "default_model", None) or self.config.fallback_model
            ctx.target_model = target_model
            ctx.router_decision = f"llm: 路由异常({e})，使用 fallback={target_model}"
        finally:
            ctx.router_latency_ms = int((time.time() - start) * 1000)

    def _extract_latest_user_message(self, messages: List[dict]) -> str:
        """从消息列表中提取最新的 user 消息文本"""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content.strip()
                if isinstance(content, list):
                    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                    return " ".join(texts).strip()
        return ""

    def _extract_context_summary(self, messages: List[dict], max_rounds: int = 3) -> str:
        """提取最近几轮对话的上下文摘要，用于路由决策"""
        if not messages or len(messages) <= 1:
            return ""
        
        # 取最近 max_rounds 轮对话（排除最后一条用户消息）
        context_messages = messages[:-1] if messages[-1].get("role") == "user" else messages
        context_messages = context_messages[-(max_rounds * 2):]  # 每轮2条消息
        
        if not context_messages:
            return ""
        
        parts = []
        for msg in context_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str):
                text = content.strip()
            elif isinstance(content, list):
                text = " ".join([c.get("text", "") for c in content if c.get("type") == "text"]).strip()
            else:
                continue
            if text:
                # 截断长文本
                if len(text) > 100:
                    text = text[:100] + "..."
                role_label = "用户" if role == "user" else "助手"
                parts.append(f"{role_label}: {text}")
        
        return "\n".join(parts) if parts else ""

    def _build_routing_prompt(self, user_text: str, models: list, context_summary: str = "") -> str:
        """构建路由决策 prompt（包含对话上下文）"""
        model_list = []
        for m in models:
            cost_info = ""
            if m.input_price is not None and m.output_price is not None:
                cost_info = f"，输入¥{m.input_price}/M，输出¥{m.output_price}/M"
            latency_info = f"，平均延迟{m.avg_latency}s" if m.avg_latency else ""
            model_list.append(
                f"- {m.model_name}: {m.capability_description or '通用模型'}{cost_info}{latency_info}"
            )

        models_text = "\n".join(model_list)
        
        context_section = ""
        if context_summary:
            context_section = f"""
对话上下文（最近几轮）：
{context_summary}
"""

        prompt = f"""你是一个 AI 模型路由专家。根据用户当前请求和对话上下文，从以下模型中选择最合适的一个。

可用模型：
{models_text}
{context_section}
用户当前请求：{user_text}

请输出 JSON 格式：
{{"model": "推荐的模型名", "reason": "推荐理由（一句话）", "confidence": 0.0-1.0}}

要求：
1. 只从上面列出的模型中选择
2. 考虑用户请求的意图、复杂度、成本和延迟
3. 考虑对话上下文：如果上下文是编程/技术讨论，即使当前问题简单，也优先选择编程能力强的模型
4. 简单请求选便宜快的模型，复杂请求选能力强的模型
5. 只输出 JSON，不要其他内容"""

        return prompt

    async def _call_router_model(self, model: str, prompt: str) -> dict:
        """调用路由模型，返回解析后的推荐结果"""
        from app.services.llm_client import LLMClient
        from app.models.database import ModelAccount
        from sqlalchemy import select

        # 找一个该模型的启用账号
        result = await self.db.execute(
            select(ModelAccount).where(
                ModelAccount.model_name == model,
                ModelAccount.is_enable == True,  # noqa: E712
            )
        )
        account = result.scalars().first()
        if not account:
            raise Exception(f"路由模型 {model} 无可用账号")

        client = LLMClient()
        response = await client.chat_completion(
            account=account,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            max_tokens=200,
            temperature=0.3,
        )

        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        return self._parse_json_response(content)

    def _parse_json_response(self, content: str) -> dict:
        """解析 LLM 返回的 JSON"""
        try:
            # 尝试直接解析
            return json.loads(content.strip())
        except json.JSONDecodeError:
            # 尝试提取 JSON 部分
            start = content.find('{')
            end = content.rfind('}')
            if start >= 0 and end > start:
                try:
                    return json.loads(content[start:end + 1])
                except json.JSONDecodeError:
                    pass

        # 解析失败，返回默认
        logger.warning(f"[llm-router] JSON 解析失败: {content[:100]}")
        return {"model": "", "reason": "解析失败", "confidence": 0.5}

    def _parse_recommendation(self, recommendation: dict, models: list) -> str:
        """从推荐结果中提取模型名，验证是否在可用列表中"""
        model_name = recommendation.get("model", "") if isinstance(recommendation, dict) else ""

        # 验证模型在可用列表中
        available_models = {m.model_name for m in models}
        if model_name in available_models:
            return model_name

        # 模糊匹配（LLM 可能返回带前缀的名字）
        for m in available_models:
            if model_name and (m in model_name or model_name in m):
                return m

        # 不在列表中，用 fallback
        logger.warning(f"[llm-router] 推荐模型 {model_name} 不在可用列表中，使用 fallback")
        return self.config.fallback_model
