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
import asyncio
from typing import AsyncGenerator, Union

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import RequestLog, SystemConfig, ModelCatalog
from app.services.router import AccountRouter
from app.services.llm_client import llm_client
from app.pipeline.context import PipelineContext
from app.pipeline.config import PipelineConfig
from app.pipeline.router import OffRouter
from app.pipeline.router.vector import VectorRouter
from app.pipeline.router.llm import LLMRouter
from app.pipeline.context_manager import PassthroughManager
from app.pipeline.context_manager.window import WindowManager
from app.pipeline.context_manager.summary import SummaryManager
from app.pipeline.selector import (
    AccountSelector, FreeFirstSelector, RoundRobinSelector,
    PinSelector, StickySelector, FailoverSelector, CostFirstSelector,
)

logger = logging.getLogger(__name__)


class Executor:
    """统一执行层——ModelRouter → AccountSelector → ContextManager → Executor 四层管线"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._router = AccountRouter(db)
        self._model_router = None  # 延迟初始化（M1 默认 OffRouter）
        self._llm_router = None  # 延迟初始化（hybrid 策略使用）
        self._context_manager = None  # 延迟初始化（M1 默认 PassthroughManager）
        self._account_selector = None  # 延迟初始化（M1 默认 PinSelector）
        self._max_retries = 3  # 默认值，execute 时从 SystemConfig.max_retry_count 覆盖
        self._entry_name = None  # 本请求内缓存对外模型名，避免重复查库

    async def _read_max_retries(self) -> int:
        """读取全局最大重试次数（后台配置生效；异常时回退默认 3）"""
        try:
            result = await self.db.execute(
                select(SystemConfig).where(SystemConfig.id == 1)
            )
            config = result.scalar_one_or_none()
            if config and config.max_retry_count is not None:
                return max(1, int(config.max_retry_count))
        except Exception as e:
            logger.warning(f"[executor] 读取重试次数配置失败: {e}")
        return 3

    async def _init_strategies(self, ctx: PipelineContext) -> None:
        """根据 PipelineConfig 初始化 ModelRouter 和 ContextManager（带缓存）"""
        config = await PipelineConfig.load(self.db)

        # ① ModelRouter（选羊）
        if config.router_strategy == "vector":
            self._model_router = VectorRouter(config.router_config, db=self.db)
        elif config.router_strategy == "llm":
            self._model_router = LLMRouter(config.router_config, db=self.db)
        elif config.router_strategy == "hybrid":
            # 混合路由：先向量，低置信度升级到 LLM（在 execute 中处理）
            self._model_router = VectorRouter(config.router_config, db=self.db)
            self._llm_router = LLMRouter(config.router_config, db=self.db)
        else:
            self._model_router = OffRouter()
            self._llm_router = None

        # ③ ContextManager（上下文）
        if config.context_strategy == "window":
            self._context_manager = WindowManager(config.context_config.window_turns)
        elif config.context_strategy == "summary":
            self._context_manager = SummaryManager(config.context_config, db=self.db)
        else:
            self._context_manager = PassthroughManager()

        # ② AccountSelector（薅羊毛）
        if config.selector_strategy == "free-first":
            self._account_selector = FreeFirstSelector()
        elif config.selector_strategy == "round-robin":
            self._account_selector = RoundRobinSelector()
        elif config.selector_strategy == "sticky":
            self._account_selector = StickySelector()
        elif config.selector_strategy == "failover":
            self._account_selector = FailoverSelector()
        elif config.selector_strategy == "cost-first":
            self._account_selector = CostFirstSelector()
        else:
            # pin（默认）：从 PinSelectorConfig 读取指定模型/账号
            self._account_selector = PinSelector(
                pin_model=config.pin_config.pin_model,
                pin_account_id=config.pin_config.pin_account_id,
            )

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
        # 读取全局最大重试次数（后台配置生效）
        self._max_retries = await self._read_max_retries()

        # ①.5 加载会话状态（滞回判定 + 摘要复用）
        session = None
        if ctx.session_id:
            from app.services.session_service import SessionStateService
            session_svc = SessionStateService(self.db)
            session = await session_svc.get_or_create(ctx.session_id)
            ctx.current_model = session.current_model  # 供 VectorRouter 滞回判定

        # ② ModelRouter 路由决策（三分支：斜杠命令 / 对外入口名 / 真实模型名）
        if ctx.forced_model:
            # 斜杠命令强制指定（最高优先级，路由内部处理）
            await self._model_router.route(ctx)
        else:
            entry_name = await self._get_entry_name()
            is_entry = (ctx.requested_model == entry_name) or (ctx.requested_model == "chat")
            is_real = await self._is_real_model(ctx.requested_model)
            if is_real:
                # 客户端点名真实模型 → 直走，跳过智能路由改判
                ctx.target_model = ctx.requested_model
                ctx.router_strategy = "named"
                ctx.router_decision = f"named: 客户端指定模型 {ctx.requested_model}"
                logger.info(f"[executor] 点名直走模型: {ctx.requested_model}")
            elif is_entry:
                # 对外入口名 → 智能路由（向量/LLM 决策真实模型）
                await self._model_router.route(ctx)
            else:
                # 既不是入口名也不在模型池 → 明确报错（不再笼统报"没有可用账号"）
                raise HTTPException(
                    status_code=400,
                    detail=f"未知模型: {ctx.requested_model}，请使用对外模型名（{entry_name}）或已配置的真实模型名",
                )

        # ②.5 hybrid 混合路由：向量低置信度时升级到 LLM 路由（点名直走时不升级）
        config = await PipelineConfig.load(self.db)
        if config.router_strategy == "hybrid" and self._llm_router and ctx.router_strategy == "vector":
            confidence = getattr(ctx, "router_confidence", 0)
            threshold = config.router_config.threshold_high
            if confidence < threshold and not ctx.forced_model:
                logger.info(f"[executor] 向量置信度 {confidence:.3f} < {threshold}，升级到 LLM 路由")
                await self._llm_router.route(ctx)

        # ②.6 检测模型切换，路由后更新会话模型
        if session:
            old_model = session.current_model
            if old_model and ctx.target_model and old_model != ctx.target_model:
                ctx.model_switched = True
                logger.info(f"[executor] 模型切换: {old_model} → {ctx.target_model}")
            if ctx.target_model:
                from app.services.session_service import SessionStateService
                await SessionStateService(self.db).set_model(ctx.session_id, ctx.target_model)

        # ③ ContextManager 组装消息（写入 ctx.assembled_messages）
        await self._context_manager.assemble(ctx, session=session)

        # ④ 账号选择 + 上游调用（原有逻辑）
        if ctx.stream:
            return self._execute_stream(ctx)
        return await self._execute_non_stream(ctx)

    # ══════════════════════════════════════════════════════════
    # 账号选择（粘性推断 + 过滤 + Selector）
    # ══════════════════════════════════════════════════════════

    async def _select_account(self, ctx: PipelineContext):
        """
        统一账号选择：粘性推断 → 过滤可用账号 → AccountSelector 选择。

        行为与现有 AccountRouter.select_account 完全一致：
        1. 有 messages 时先做粘性推断，推断到可用账号直接返回
        2. 否则过滤可用账号（启用、匹配模型、未冷却、额度充足）
        3. 用 AccountSelector 策略从可用账号中选一个
        """
        # 1. 粘性推断（与现有逻辑一致）
        if ctx.original_messages:
            prev_account = await self._router._infer_previous_account(
                ctx.original_messages, ctx.requested_model, ctx.estimated_tokens
            )
            # 粘性只在同一模型内有效：路由决策切换模型时不保持旧账号粘性
            if prev_account and (not ctx.target_model or prev_account.model_name == ctx.target_model):
                ctx.selector_strategy = self._account_selector.name
                ctx.selector_decision = f"sticky: 继续使用账号 {prev_account.id}"
                logger.info(f"会话粘性：继续使用账号 {prev_account.id} ({prev_account.vendor})")
                return prev_account
            elif prev_account:
                logger.info(f"模型切换（{prev_account.model_name} → {ctx.target_model}），跳过会话粘性")

        # 2. 过滤可用账号
        # 入口名场景：按路由决策的 target_model（真实模型）过滤；决策模型不可用时回退全量候选
        # 真实模型名场景：按客户端点名过滤
        entry_name = await self._get_entry_name()
        is_entry = (ctx.requested_model == entry_name) or (ctx.requested_model == "chat")
        if is_entry:
            filter_model = ctx.target_model
            available = await self._router._filter_available_accounts(
                filter_model, ctx.estimated_tokens
            )
            if not available and ctx.target_model:
                # 智能兜底：路由决策的模型当前无可用账号（如本地模型停用/额度不足）
                # → 回退全量可用账号，交给选择器（free-first 等）智能挑选
                logger.warning(
                    f"[executor] 路由决策模型 {ctx.target_model} 无可用账号，回退全量候选"
                )
                ctx.router_decision = f"{ctx.router_decision or ''}; fallback: 决策模型不可用，全量候选"
                available = await self._router._filter_available_accounts(
                    None, ctx.estimated_tokens
                )
        else:
            filter_model = ctx.requested_model
            available = await self._router._filter_available_accounts(
                filter_model, ctx.estimated_tokens
            )

        if not available:
            return None

        # 3. AccountSelector 选择（优先用路由决策后的 target_model，回退到 requested_model）
        target = ctx.target_model or ctx.requested_model

        # cost-first 需要"账号+模型"维度的单价：注入临时属性供排序，不落库
        if self._account_selector.name == "cost-first" and target:
            from app.services.model_catalog_service import ModelCatalogService
            _svc = ModelCatalogService(self.db)
            for _a in available:
                _row = await _svc.get_by_account_model(_a.id, target)
                _a._cost_input = _row.input_price if _row else None
                _a._cost_output = _row.output_price if _row else None

        account = self._account_selector.select(
            available,
            model_name=target,
        )
        ctx.selector_strategy = self._account_selector.name
        if account:
            ctx.selector_decision = f"{self._account_selector.name}: 选中账号 {account.id}"
            # 回退全量场景：路由决策模型与选中账号实际模型不一致 → 以账号实际模型为准
            if is_entry and "fallback" in (ctx.router_decision or "") and account.model_name:
                if account.model_name != ctx.target_model:
                    logger.info(
                        f"[executor] 目标模型修正 {ctx.target_model} → {account.model_name}（回退兜底）"
                    )
                    ctx.target_model = account.model_name
        return account

    async def _get_entry_name(self) -> str:
        """读取对外暴露的模型名（system_config.virtual_entry_name，默认 woolgate），本请求内缓存"""
        if self._entry_name:
            return self._entry_name
        try:
            result = await self.db.execute(
                select(SystemConfig).where(SystemConfig.id == 1)
            )
            config = result.scalar_one_or_none()
            if config and config.virtual_entry_name:
                self._entry_name = config.virtual_entry_name
                return self._entry_name
        except Exception as e:
            logger.warning(f"[executor] 读取对外模型名失败: {e}")
        self._entry_name = "woolgate"
        return self._entry_name

    async def _is_real_model(self, model_name: str) -> bool:
        """判断请求名是否为模型池中的真实模型名"""
        if not model_name:
            return False
        result = await self.db.execute(
            select(ModelCatalog.id)
            .where(ModelCatalog.model_name == model_name)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

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

        for attempt in range(self._max_retries):
            account = await self._select_account(ctx)

            if not account:
                msg = self._no_account_msg(tried_accounts, last_error, ctx.requested_model)
                logger.warning(msg)
                yield self._error_sse(msg, "no_available_account")
                return

            if account.id in tried_accounts:
                logger.warning(f"账号 {account.id} 已尝试过，跳过")
                continue

            tried_accounts.add(account.id)
            ctx.switch_count = attempt  # M1 观测：第几次尝试（0=首次，1+=切换次数）
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
        full_content = ""  # 累加输出内容，用于估算 token
        produced_any = False  # A3: 本账号是否已产出内容（判定 stream_interrupted 信号）
        cancelled = False  # A3: 客户端主动断开（asyncio.CancelledError）

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
                
                # 累加输出内容（用于 usage 为空时估算 token）
                try:
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_content += content
                            produced_any = True
                except Exception:
                    pass
                
                yield chunk

        except asyncio.CancelledError:
            # A3: 客户端主动断开/取消流（CancelledError 继承 BaseException，需单独捕获）
            # 无论是否已产出内容，一律记为「输出中断」信号
            error_occurred = True
            cancelled = True
            error_message = "客户端中断"
            logger.info(f"账号 {account.id} 流被客户端中断")
            raise

        except Exception as e:
            error_occurred = True
            error_message = str(e)
            logger.error(f"流式请求失败: {e}", exc_info=True)
            raise

        finally:
            response_time = int((time.time() - start_time) * 1000)
            
            # 如果模型没有返回 usage，用字符数估算 token（统一口径见 app/utils/token_estimator.py）
            from app.utils.token_estimator import estimate_tokens
            if prompt_tokens == 0 and ctx.original_messages:
                input_text = ""
                for msg in ctx.original_messages:
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        input_text += content
                if input_text:
                    prompt_tokens = estimate_tokens(input_text)
            
            if completion_tokens == 0 and full_content:
                completion_tokens = estimate_tokens(full_content)

            # A3: 隐式信号——客户端中断/输出后中断 vs 输出前失败（由外层决定是否切换）
            implicit_signal = None
            if error_occurred and (cancelled or produced_any):
                implicit_signal = "stream_interrupted"
            elif error_occurred:
                implicit_signal = "switch_retry"

            await self._record(
                account, ctx, prompt_tokens, completion_tokens,
                "success" if not error_occurred else "failed",
                error_message, response_time,
                implicit_signal=implicit_signal,
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

        for attempt in range(self._max_retries):
            account = await self._select_account(ctx)

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
            ctx.switch_count = attempt  # M1 观测：第几次尝试（0=首次，1+=切换次数）
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

                if attempt == self._max_retries - 1:
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

            # 记账（失败日志，A3: 非流式失败必然触发切换 → switch_retry 信号）
            await self._record(
                account, ctx, 0, 0, "failed", error_message, response_time,
                implicit_signal="switch_retry",
            )
            # 冷却统一由外层 _execute_non_stream 处理（避免双重冷却）
            raise

    # ══════════════════════════════════════════════════════════
    # 公共方法
    # ══════════════════════════════════════════════════════════

    async def _record(
        self, account, ctx: PipelineContext,
        prompt_tokens: int, completion_tokens: int,
        status: str, error_message, response_time: int,
        implicit_signal: str = None,
    ):
        """统一记账（deduct_quota）+ 请求日志（RequestLog，含 M1 观测埋点 + A3 反馈/信号字段）"""
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
                # ── M1 观测埋点 ──
                request_id=ctx.request_id,
                session_id=ctx.session_id,
                domain_tag=ctx.target_model,  # M4 后存目标模型名
                router_strategy=ctx.router_strategy,
                selector_strategy=ctx.selector_strategy,
                context_strategy=ctx.context_strategy,
                switch_count=ctx.switch_count,
                summary_used=ctx.summary_used,
                tenant_id=ctx.tenant_id,
                # ── A3 隐式信号 ──
                implicit_signal=implicit_signal,
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
