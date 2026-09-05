"""
统一执行层（Executor）

合并流式/非流式两套独立的重试循环，消除重复代码。
行为与现有 api.py 中的 stream_with_failover + non_stream_handler 完全一致。

共同逻辑：
- 循环选账号（最多 max_retries 次）
- 失败（输出前）→ 冷却 → 切换下一个账号
- 成功 → 记账 + 请求日志 → 返回
- 全部失败 → 返回错误

差异：
- 流式：yield chunks，输出后失败不切换，以 SSE error chunk 结束
- 非流式：直接返回 JSONResponse，失败抛异常
"""
import json
import time
import logging
from typing import AsyncGenerator, Union

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import RequestLog
from app.services.router import AccountRouter
from app.services.llm_client import llm_client
from app.pipeline.context import PipelineContext
from app.pipeline.config import PipelineConfig
from app.pipeline.router import OffRouter, RulesRouter
from app.pipeline.router.vector import VectorRouter
from app.pipeline.router.llm import LLMRouter
from app.pipeline.context_manager import PassthroughManager
from app.pipeline.context_manager.window import WindowManager
from app.pipeline.context_manager.summary import SummaryManager

logger = logging.getLogger(__name__)

MAX_RETRIES = 3  # 与现有硬编码一致


class Executor:
    """统一执行层——ModelRouter → AccountSelector → ContextManager → Executor 四层管线"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._router = AccountRouter(db)
        self._model_router = None  # 延迟初始化（M1 默认 OffRouter）
        self._context_manager = None  # 延迟初始化（M1 默认 PassthroughManager）

    async def _init_strategies(self, ctx: PipelineContext) -> None:
        """根据 PipelineConfig 初始化 ModelRouter 和 ContextManager（带缓存）"""
        config = await PipelineConfig.load(self.db)

        # ① ModelRouter（选羊）
        if config.router_strategy == "rules":
            self._model_router = RulesRouter(self.db, config.router_config.rules_match_mode)
        elif config.router_strategy == "vector":
            self._model_router = VectorRouter(config.router_config)
        elif config.router_strategy == "llm":
            self._model_router = LLMRouter(config.router_config)
        else:
            self._model_router = OffRouter()

        # ③ ContextManager（上下文）
        if config.context_strategy == "window":
            self._context_manager = WindowManager(config.context_config.window_turns)
        elif config.context_strategy == "summary":
            self._context_manager = SummaryManager(config.context_config)
        else:
            self._context_manager = PassthroughManager()

    async def execute(self, ctx: PipelineContext) -> Union[AsyncGenerator, JSONResponse]:
        """
        统一执行入口。

        管线顺序：ModelRouter → 账号选择循环 → ContextManager → 上游调用
        M1 默认 router=off, context=passthrough，行为与现有完全一致。

        Returns:
            流式: AsyncGenerator（yield SSE chunks）
            非流式: JSONResponse
        """
        # ① 初始化策略（带缓存，60秒内不重复查库）
        await self._init_strategies(ctx)

        # ② ModelRouter 路由决策（写入 ctx.domain_tag / ctx.target_model）
        await self._model_router.route(ctx)

        # ③ ContextManager 组装消息（写入 ctx.assembled_messages）
        await self._context_manager.assemble(ctx)

        # ④ 账号选择 + 上游调用（原有逻辑）
        if ctx.stream:
            return self._execute_stream(ctx)
        return await self._execute_non_stream(ctx)

    # ══════════════════════════════════════════════════════════
    # 流式
    # ══════════════════════════════════════════════════════════

    async def _execute_stream(self, ctx: PipelineContext) -> AsyncGenerator:
        """
        流式执行（带账号自动切换）

        规则（与现有 stream_with_failover 完全一致）：
        - 输出前失败 → 冷却 + 切换下一个账号
        - 输出后失败 → 不切换，返回 error chunk
        - 任何失败均以 SSE error chunk 正常结束，不中断连接
        """
        last_error = None
        tried_accounts: set[int] = set()

        for attempt in range(MAX_RETRIES):
            account = await self._router.select_account(
                model_name=ctx.requested_model,
                estimated_tokens=ctx.estimated_tokens,
                messages=ctx.original_messages,
            )

            if not account:
                msg = self._no_account_msg(tried_accounts, last_error, ctx.requested_model)
                logger.warning(msg)
                yield self._error_sse(msg, "no_available_account")
                return

            if account.id in tried_accounts:
                logger.warning(f"账号 {account.id} 已尝试过，跳过")
                continue

            tried_accounts.add(account.id)
            logger.info(f"尝试账号 {account.id} (第 {attempt + 1} 次尝试)")

            produced_any = False
            try:
                async for chunk in self._stream_single(account, ctx):
                    if not produced_any:
                        produced_any = True
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

                # 流正常结束
                yield "data: [DONE]\n\n"
                return

            except HTTPException:
                raise
            except Exception as e:
                last_error = str(e)
                logger.error(f"账号 {account.id} 流式请求失败: {last_error}", exc_info=True)

                if produced_any:
                    # 已开始输出，不能切换账号
                    logger.error(f"账号 {account.id} 已输出内容后中断，无法切换账号")
                    yield self._error_sse(f"请求中断: {last_error}", "stream_error")
                    return

                # 输出前失败，冷却并切换
                logger.warning(f"账号 {account.id} 输出前失败: {last_error}，尝试下一个账号")
                await self._router.mark_account_failed(account.id)
                await self.db.commit()
                continue

        # 所有账号均在输出前失败
        yield self._error_sse(f"所有账号均失败。最后错误: {last_error}", "no_available_account")

    async def _stream_single(self, account, ctx: PipelineContext) -> AsyncGenerator:
        """
        单个账号流式消费 + 记账（与现有 stream_account 完全一致）

        异常向上传播，由 _execute_stream 决定切换或返回错误。
        """
        start_time = time.time()
        prompt_tokens = 0
        completion_tokens = 0
        error_occurred = False
        error_message = None

        try:
            async for chunk in llm_client.chat_completion_stream(
                account, ctx.assembled_messages, **ctx.kwargs
            ):
                # 提取 token 统计
                if "usage" in chunk:
                    usage = chunk["usage"]
                    if usage:
                        prompt_tokens = usage.get("prompt_tokens", 0)
                        completion_tokens = usage.get("completion_tokens", 0)
                yield chunk

        except Exception as e:
            error_occurred = True
            error_message = str(e)
            logger.error(f"流式请求失败: {e}", exc_info=True)
            raise

        finally:
            response_time = int((time.time() - start_time) * 1000)
            await self._record(
                account, ctx, prompt_tokens, completion_tokens,
                "success" if not error_occurred else "failed",
                error_message, response_time,
            )

    # ══════════════════════════════════════════════════════════
    # 非流式
    # ══════════════════════════════════════════════════════════

    async def _execute_non_stream(self, ctx: PipelineContext) -> JSONResponse:
        """
        非流式执行（带账号自动切换）

        与现有 chat_completions 非流式分支 + non_stream_handler 完全一致。
        """
        last_error = None
        tried_accounts: set[int] = set()

        for attempt in range(MAX_RETRIES):
            account = await self._router.select_account(
                model_name=ctx.requested_model,
                estimated_tokens=ctx.estimated_tokens,
                messages=ctx.original_messages,
            )

            if not account:
                if tried_accounts:
                    raise HTTPException(
                        status_code=503,
                        detail=f"所有账号均不可用。最后错误: {last_error}",
                    )
                raise HTTPException(
                    status_code=503,
                    detail=f"没有可用账号用于模型: {ctx.requested_model}",
                )

            if account.id in tried_accounts:
                logger.warning(f"账号 {account.id} 已尝试过，跳过")
                continue

            tried_accounts.add(account.id)
            logger.info(f"尝试账号 {account.id} (第 {attempt + 1} 次尝试)")

            try:
                return await self._non_stream_single(account, ctx)

            except HTTPException:
                raise
            except Exception as e:
                last_error = str(e)
                logger.warning(f"账号 {account.id} 失败: {last_error}，尝试下一个账号")

                # 冷却（与现有行为一致：non_stream_handler 内部已冷却一次，这里再冷却一次）
                await self._router.mark_account_failed(account.id)
                await self.db.commit()

                if attempt == MAX_RETRIES - 1:
                    raise HTTPException(
                        status_code=503,
                        detail=f"所有账号均失败。最后错误: {last_error}",
                    )
                continue

    async def _non_stream_single(self, account, ctx: PipelineContext) -> JSONResponse:
        """单个账号非流式调用 + 记账（与现有 non_stream_handler 完全一致）"""
        start_time = time.time()

        try:
            response = await llm_client.chat_completion(
                account, ctx.assembled_messages, **ctx.kwargs
            )

            usage = response.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            response_time = int((time.time() - start_time) * 1000)

            await self._record(
                account, ctx, prompt_tokens, completion_tokens,
                "success", None, response_time,
            )
            return JSONResponse(content=response)

        except Exception as e:
            error_message = str(e)
            logger.error(f"非流式请求失败: {e}", exc_info=True)
            response_time = int((time.time() - start_time) * 1000)

            # 记账（失败日志）
            await self._record(
                account, ctx, 0, 0, "failed", error_message, response_time,
            )
            # 冷却（与现有 non_stream_handler 一致）
            await self._router.mark_account_failed(account.id)
            await self.db.commit()
            raise

    # ══════════════════════════════════════════════════════════
    # 公共方法
    # ══════════════════════════════════════════════════════════

    async def _record(
        self, account, ctx: PipelineContext,
        prompt_tokens: int, completion_tokens: int,
        status: str, error_message, response_time: int,
    ):
        """统一记账（deduct_quota）+ 请求日志（RequestLog）"""
        try:
            await self._router.deduct_quota(account.id, prompt_tokens, completion_tokens)

            log = RequestLog(
                account_id=account.id,
                vendor=account.vendor,
                model_name=account.model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                status=status,
                error_message=error_message,
                response_time_ms=response_time,
                client_ip=ctx.client_ip,
                endpoint="/v1/chat/completions",
            )
            self.db.add(log)
            await self.db.commit()
        except Exception as log_err:
            logger.error(f"记录请求日志失败: {log_err}", exc_info=True)

    @staticmethod
    def _no_account_msg(tried_accounts: set, last_error, model_name: str) -> str:
        if tried_accounts:
            return f"所有账号均不可用。最后错误: {last_error}"
        return f"没有可用账号用于模型: {model_name}"

    @staticmethod
    def _error_sse(message: str, error_type: str) -> str:
        return f"data: {json.dumps({'error': {'message': message, 'type': error_type}}, ensure_ascii=False)}\n\n"
