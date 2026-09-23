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
from app.services.health import health_tracker
from app.utils.log_utils import ctx_event
from app.pipeline.context import PipelineContext, Stage
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
from app.extensions.classifiers import ClassifierFactory, ClassificationResult
from app.extensions.hooks import (
    HOOK_REQUEST_STARTED, HOOK_CLASSIFY_AFTER, HOOK_ROUTE_BEFORE,
    HOOK_ROUTE_AFTER, HOOK_SELECT_AFTER, HOOK_CONTEXT_AFTER,
    HOOK_EXECUTE_AFTER, HOOK_REQUEST_FINISHED, HOOK_ERROR_OCCURRED,
    HookBlocked,
)
from app.extensions.sdk import emit_hooks
from app.extensions.security import get_security_guard, SecurityBlocked

logger = logging.getLogger(__name__)


class Executor:
    """统一执行层——ModelRouter → AccountSelector → ContextManager → Executor 四层管线"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._router = AccountRouter(db)
        self._classifier = None  # 主分类器（v0.6.0 组件化，替代 _model_router）
        self._classifier_upgrade = None  # hybrid 升级分类器（低置信度时用）
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
        """根据 PipelineConfig 初始化分类器 / ContextManager / AccountSelector（带缓存）"""
        config = await PipelineConfig.load(self.db)

        # ① 分类引擎（v0.6.0 组件化：vector/llm/local/hybrid，含自定义 SPI）
        self._classifier, self._classifier_upgrade = ClassifierFactory.create(
            config.router_strategy,
            config.router_config.classifier_engine,
            config.router_config,
            db=self.db,
        )

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

        管线顺序：request.started → 安全入站审核 → 路由决策(分类) → 选号 → 上下文 → 上游调用
        v0.6.0 起挂载 9 个生命周期插口 + 分类引擎组件化 + 降级链。
        """
        _t0 = time.time()
        ctx.stage = Stage.REQUEST
        try:
            # ① 初始化策略（带缓存，60秒内不重复查库）
            await self._init_strategies(ctx)
            # 读取全局最大重试次数（后台配置生效）
            self._max_retries = await self._read_max_retries()

            # ①.1 请求开始插口（审计/租户注入/限流）
            await emit_hooks(HOOK_REQUEST_STARTED, ctx)

            # ①.2 安全入站审核（默认放行；企业版注入实现，SecurityBlocked → 403）
            try:
                guard = get_security_guard()
                await guard.check_input(ctx)
            except SecurityBlocked as e:
                raise HTTPException(status_code=e.status_code, detail=e.reason)
            ctx.stage_timings_ms[Stage.REQUEST] = int((time.time() - _t0) * 1000)

            # ①.5 加载会话状态（滞回判定 + 摘要复用；租户前缀隔离见契约 06）
            session = None
            if ctx.session_id:
                from app.services.session import SessionStateService
                session_svc = SessionStateService(self.db, tenant_id=ctx.tenant_id)
                session = await session_svc.get_or_create(ctx.session_id)
                ctx.current_model = session.current_model  # 供 VectorClassifier 滞回判定

            # ② 路由决策（三分支 + 用户覆盖 + 分类降级，v0.6.0 重构）
            await self._decide_route(ctx)

            # ②.6 检测模型切换，路由后更新会话模型
            if session:
                old_model = session.current_model
                if old_model and ctx.target_model and old_model != ctx.target_model:
                    ctx.model_switched = True
                    logger.info(f"[executor] 模型切换: {old_model} → {ctx.target_model}")
                if ctx.target_model:
                    from app.services.session import SessionStateService
                    await SessionStateService(self.db, tenant_id=ctx.tenant_id).set_model(
                        ctx.session_id, ctx.target_model
                    )

            # ③ ContextManager 组装消息（写入 ctx.assembled_messages）
            _t_ctx = time.time()
            ctx.stage = Stage.CONTEXT
            await self._context_manager.assemble(ctx, session=session)
            await emit_hooks(HOOK_CONTEXT_AFTER, ctx)
            ctx.stage_timings_ms[Stage.CONTEXT] = int((time.time() - _t_ctx) * 1000)

            # ④ 账号选择 + 上游调用（原有逻辑）
            ctx.stage = Stage.EXECUTE
            if ctx.stream:
                result = self._execute_stream(ctx)
            else:
                result = await self._execute_non_stream(ctx)
            ctx.stage = Stage.RESPONSE
            return result
        except HTTPException:
            await emit_hooks(HOOK_ERROR_OCCURRED, ctx)
            raise
        except Exception as e:
            ctx.status = "failed"
            ctx.error_message = str(e)
            await emit_hooks(HOOK_ERROR_OCCURRED, ctx)
            raise

    # ══════════════════════════════════════════════════════════
    # 路由决策（v0.6.0 重构：B3 分支清晰化 + A4/A5 分类组件化与降级）
    # ══════════════════════════════════════════════════════════

    async def _decide_route(self, ctx: PipelineContext) -> None:
        """
        路由决策主流程（契约 02 第 6 节时序）：

        route.before → [forced/override/named 直走 | 入口名智能分类]
        → classify.after → route.after

        分支优先级：斜杠命令 > 请求头覆盖 > 真实模型名直走 > 智能分类（入口名）
        """
        _t = time.time()
        ctx.stage = Stage.ROUTE
        await emit_hooks(HOOK_ROUTE_BEFORE, ctx)

        try:
            # 分支 1：斜杠命令强制指定（最高优先级，跳过分类）
            if ctx.forced_model:
                ctx.target_model = ctx.forced_model
                ctx.router_strategy = self._classifier.name if self._classifier else "off"
                ctx.router_decision = f"forced: 斜杠命令模型={ctx.forced_model}"
                logger.info(f"[executor] 斜杠命令直走: {ctx.forced_model}")
            # 分支 2：请求头 X-Model-Preference 覆盖（次高，跳过分类）
            elif ctx.user_override_model:
                ctx.target_model = ctx.user_override_model
                ctx.router_strategy = "override"
                ctx.router_decision = f"override: 请求头指定模型={ctx.user_override_model}"
                logger.info(f"[executor] 请求头覆盖直走: {ctx.user_override_model}")
            else:
                entry_name = await self._get_entry_name()
                is_entry = (ctx.requested_model == entry_name) or (ctx.requested_model == "chat")
                is_real = await self._is_real_model(ctx.requested_model)
                if is_real:
                    # 分支 3：客户端点名真实模型 → 直走，跳过智能路由改判
                    ctx.target_model = ctx.requested_model
                    ctx.router_strategy = "named"
                    ctx.router_decision = f"named: 客户端指定模型 {ctx.requested_model}"
                    logger.info(f"[executor] 点名直走模型: {ctx.requested_model}")
                elif is_entry:
                    # 分支 4：对外入口名 → 智能分类（含 hybrid 升级与降级链）
                    await self._classify_with_fallback(ctx)
                else:
                    # 既不是入口名也不在模型池 → 明确报错
                    raise HTTPException(
                        status_code=400,
                        detail=f"未知模型: {ctx.requested_model}，请使用对外模型名（{entry_name}）或已配置的真实模型名",
                    )

            # classify.after：分类结果定稿前可覆盖（仅 after 类钩子，见契约）
            await emit_hooks(HOOK_CLASSIFY_AFTER, ctx)
            # route.after：最终目标模型定稿后校验/修正
            await emit_hooks(HOOK_ROUTE_AFTER, ctx)
        except HookBlocked as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        finally:
            ctx.stage_timings_ms[Stage.ROUTE] = int((time.time() - _t) * 1000)

    async def _classify_with_fallback(self, ctx: PipelineContext) -> None:
        """
        智能分类主调用 + 降级链（A4/A5）。

        - 主分类器异常/无结果 → 降级 fallback_model（degraded=True）
        - hybrid：vector 置信度 < threshold_high → 升级 LLM 分类
        - 分类不可用（off）→ 直接 fallback（等价 v0.5.0 off 行为）
        """
        _t = time.time()
        ctx.stage = Stage.CLASSIFY
        config = await PipelineConfig.load(self.db)
        fallback = ctx.default_model or config.router_config.fallback_model

        if self._classifier is None:
            # 分类关闭（off/未知策略）：等价 v0.5.0 OffRouter 透传行为
            ctx.router_strategy = "off"
            ctx.router_decision = "off: 不路由"
            ctx.classify_engine = "off"
            ctx.stage_timings_ms[Stage.CLASSIFY] = int((time.time() - _t) * 1000)
            return

        try:
            result: ClassificationResult = await self._classifier.classify(ctx)
            ctx.classify_engine = result.engine
            ctx.classify_decision = result.decision

            # hybrid 升级：向量低置信度 → LLM 分类
            if self._classifier_upgrade and ctx.router_strategy == "vector":
                threshold = config.router_config.threshold_high
                confidence = getattr(ctx, "router_confidence", 0)
                if confidence < threshold and not ctx.forced_model:
                    logger.info(
                        f"[executor] 向量置信度 {confidence:.3f} < {threshold}，升级到 LLM 分类"
                    )
                    result = await self._classifier_upgrade.classify(ctx)
                    ctx.classify_engine = result.engine
                    ctx.classify_decision = result.decision

            # 分类无结果（空模型名）→ 降级 fallback
            if not ctx.target_model:
                ctx.degraded = True
                ctx.degrade_reason = "classify_empty: 分类无结果"
                ctx.target_model = fallback
                ctx.router_decision = f"fallback: 分类无结果，使用 {fallback}"
                logger.warning(f"[executor] 分类无结果，降级 fallback: {fallback}")
        except Exception as e:
            # A5 降级链：分类异常 → fallback 模型直走，绝不因分类故障拒绝服务
            ctx.degraded = True
            ctx.degrade_reason = f"classify_failed: {e}"
            ctx.target_model = fallback
            ctx.router_decision = f"fallback: 分类异常({e})，使用 {fallback}"
            ctx.router_confidence = 0.0
            logger.error(f"[executor] 分类异常，降级 fallback: {e}", exc_info=True)
        finally:
            ctx.stage_timings_ms[Stage.CLASSIFY] = int((time.time() - _t) * 1000)

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
            if prev_account and (not ctx.target_model or prev_account.default_model_name == ctx.target_model):
                ctx.selector_strategy = self._account_selector.name
                ctx.selector_decision = f"sticky: 继续使用账号 {prev_account.id}"
                ctx.account = prev_account
                logger.info(f"会话粘性：继续使用账号 {prev_account.id} ({prev_account.vendor})")
                await emit_hooks(HOOK_SELECT_AFTER, ctx)
                return prev_account
            elif prev_account:
                logger.info(f"模型切换（{prev_account.default_model_name} → {ctx.target_model}），跳过会话粘性")

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
            from app.services.model_catalog import ModelCatalogService
            from app.services.performance_learner import get_effective_cost_map
            _svc = ModelCatalogService(self.db)
            # 历史有效成本（学习型选号信号）
            _eff_cost_map = await get_effective_cost_map(self.db, target, ctx.target_model or "general")
            for _a in available:
                _row = await _svc.get_by_account_model(_a.id, target)
                _a._cost_input = _row.input_price if _row else None
                _a._cost_output = _row.output_price if _row else None
                _a._effective_cost = _eff_cost_map.get(_a.id)  # None = 无历史数据

        account = self._account_selector.select(
            available,
            model_name=target,
        )
        ctx.selector_strategy = self._account_selector.name
        if account:
            ctx.selector_decision = f"{self._account_selector.name}: 选中账号 {account.id}"
            ctx.account = account
            # 回退全量场景：路由决策模型与选中账号实际模型不一致 → 以账号实际模型为准
            if is_entry and "fallback" in (ctx.router_decision or "") and account.default_model_name:
                if account.default_model_name != ctx.target_model:
                    logger.info(
                        f"[executor] 目标模型修正 {ctx.target_model} → {account.default_model_name}（回退兜底）"
                    )
                    ctx.target_model = account.default_model_name
            await emit_hooks(HOOK_SELECT_AFTER, ctx)
        return account

    async def _get_entry_name(self) -> str:
        """读取对外暴露的模型名（system_config.virtual_model_name，默认 woolgate），本请求内缓存"""
        if self._entry_name:
            return self._entry_name
        try:
            result = await self.db.execute(
                select(SystemConfig).where(SystemConfig.id == 1)
            )
            config = result.scalar_one_or_none()
            if config and config.virtual_model_name:
                self._entry_name = config.virtual_model_name
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

        try:
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
        finally:
            # 流结束（正常/异常/客户端断开）统一触发 request.finished（只触发一次）
            await emit_hooks(HOOK_REQUEST_FINISHED, ctx)

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

            # 流式出站审核（A8）：流式内容逐块产出，整体审核需流式审核器，
            # 预留随企业组件池提供；此处触发 execute.after 钩子（可做缓存/质量评分）
            await emit_hooks(HOOK_EXECUTE_AFTER, ctx)

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

            # 出站安全审核（A8：默认放行，企业版可脱敏/拦截）
            try:
                guard = get_security_guard()
                await guard.check_output(ctx, response)
            except SecurityBlocked as e:
                raise HTTPException(status_code=e.status_code, detail=e.reason)

            # execute.after 钩子（缓存响应/质量评分）
            await emit_hooks(HOOK_EXECUTE_AFTER, ctx)
            await emit_hooks(HOOK_REQUEST_FINISHED, ctx)
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
        """统一记账（deduct_quota）+ 请求日志（RequestLog，含 M1 观测埋点 + A3 反馈/信号字段 + B1 成本）"""
        try:
            await self._router.deduct_quota(account.id, prompt_tokens, completion_tokens)

            # B1 成本计算：按账号+模型维度的单价（ModelCatalog 行）；无单价记 0（免费/未获取）
            cost_input, cost_output = await self._get_model_prices(account, ctx.target_model)
            actual_cost = (prompt_tokens / 1_000_000) * (cost_input or 0) + \
                          (completion_tokens / 1_000_000) * (cost_output or 0)
            ctx.prompt_tokens = prompt_tokens
            ctx.completion_tokens = completion_tokens
            ctx.response_time_ms = response_time
            ctx.status = status
            ctx.error_message = error_message
            ctx.actual_cost = round(actual_cost, 6)
            if status == "success":
                ctx.estimated_cost = round(
                    (ctx.estimated_tokens / 1_000_000) * (cost_input or 0), 6
                ) if cost_input else 0.0

            # B2 健康度信号：记录本次调用结果（供选号/省钱看板）
            health_tracker.record(
                account.id,
                success=(status == "success"),
                latency_ms=response_time,
                error=error_message or "",
            )

            log = RequestLog(
                account_id=account.id,
                vendor=account.vendor,
                model_name=account.default_model_name,
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
                routed_model=ctx.target_model,  # 实际路由到的目标模型名
                router_strategy=ctx.router_strategy,
                selector_strategy=ctx.selector_strategy,
                context_strategy=ctx.context_strategy,
                switch_count=ctx.switch_count,
                summary_used=ctx.summary_used,
                tenant_id=ctx.tenant_id,
                # ── A3 隐式信号 ──
                implicit_signal=implicit_signal,
                # ── C5 学习型路由：成本/决策明细/分类引擎 ──
                estimated_cost=ctx.estimated_cost,
                actual_cost=ctx.actual_cost,
                router_decision=ctx.router_decision,
                selector_decision=ctx.selector_decision,
                classify_engine=ctx.classify_engine,
                degraded=ctx.degraded,
                degrade_reason=ctx.degrade_reason,
            )
            self.db.add(log)
            await self.db.commit()

            # 结构化事件日志（B1）：每次调用输出一条 JSON 事件
            ctx_event(
                logger, "executor.call_done", ctx,
                level=logging.INFO,
                account_id=account.id, vendor=account.vendor,
                cost_input=cost_input, cost_output=cost_output,
                actual_cost=ctx.actual_cost,
            )
        except Exception as log_err:
            logger.error(f"记录请求日志失败: {log_err}", exc_info=True)

    async def _get_model_prices(self, account, model_name: str):
        """读取账号+模型维度单价（ModelCatalog 行）；无数据返回 (None, None)"""
        try:
            from app.services.model_catalog import ModelCatalogService
            row = await ModelCatalogService(self.db).get_by_account_model(account.id, model_name or account.default_model_name)
            if row:
                return row.input_price, row.output_price
        except Exception as e:
            logger.warning(f"[executor] 读取模型单价失败: {e}")
        return None, None

    @staticmethod
    def _no_account_msg(tried_accounts: set, last_error, model_name: str) -> str:
        if tried_accounts:
            return f"所有账号均不可用。最后错误: {last_error}"
        return f"没有可用账号用于模型: {model_name}"

    @staticmethod
    def _error_sse(message: str, error_type: str) -> str:
        return f"data: {json.dumps({'error': {'message': message, 'type': error_type}}, ensure_ascii=False)}\n\n"
