"""
核心路由调度算法
实现优先级排序、额度预判、账号筛选、轮询/顺序策略
"""
from typing import List, Optional, Tuple
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import ModelAccount, SystemConfig, RequestLog
from app.pipeline.selector import FreeFirstSelector, RoundRobinSelector
import logging
import random

logger = logging.getLogger(__name__)


class AccountRouter:
    """账号路由调度器"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self._round_robin_index = {}  # 轮询索引缓存（保留兼容，实际委托给 RoundRobinSelector）
        # M1: 委托给 Selector 策略类（行为与现有完全一致）
        self._free_first_selector = FreeFirstSelector()
        self._round_robin_selector = RoundRobinSelector()
    
    async def get_system_config(self) -> SystemConfig:
        """获取系统配置"""
        result = await self.session.execute(select(SystemConfig).where(SystemConfig.id == 1))
        config = result.scalar_one_or_none()
        if not config:
            config = SystemConfig(id=1)
            self.session.add(config)
            await self.session.commit()
        return config
    
    async def select_account(
        self,
        model_name: str,
        estimated_tokens: int = 1000,
        strategy: Optional[str] = None,
        messages: Optional[list] = None
    ) -> Optional[ModelAccount]:
        """
        选择最优账号
        
        Args:
            model_name: 模型名称
            estimated_tokens: 预估Token数（用于额度预判）
            strategy: 路由策略，None时使用全局默认
            messages: 消息历史（用于会话粘性）
        
        Returns:
            选中的账号，无可用账号返回None
        """
        # 1. 会话粘性：尝试推断之前使用的账号
        if messages:
            prev_account = await self._infer_previous_account(messages, model_name, estimated_tokens)
            if prev_account:
                logger.info(f"会话粘性：继续使用账号 {prev_account.id} ({prev_account.vendor})")
                return prev_account
        
        # 2. 获取系统配置
        config = await self.get_system_config()
        if strategy is None:
            strategy = config.default_route_strategy
        
        # 3. 筛选可用账号
        accounts = await self._filter_available_accounts(model_name, estimated_tokens)
        
        if not accounts:
            logger.warning(f"没有可用账号用于模型: {model_name}")
            return None
        
        # 4. 根据策略选择账号
        if strategy == "sequential":
            return await self._select_sequential(accounts)
        elif strategy == "round_robin":
            return await self._select_round_robin(accounts, model_name)
        else:
            logger.error(f"未知路由策略: {strategy}")
            return accounts[0] if accounts else None
    
    async def _filter_available_accounts(
        self,
        model_name: str,
        estimated_tokens: int
    ) -> List[ModelAccount]:
        """
        筛选可用账号
        
        筛选条件：
        1. 启用状态
        2. 匹配模型名称
        3. 未在冷却中
        4. 额度充足（Ollama除外）
        """
        now = datetime.utcnow()
        
        # 查询所有启用且匹配虚拟模型的账号
        result = await self.session.execute(
            select(ModelAccount)
            .where(ModelAccount.is_enable == True)
            .where(ModelAccount.virtual_model == model_name)
        )
        accounts = result.scalars().all()
        
        available = []
        for account in accounts:
            # 检查冷却状态
            if account.cool_down_until and account.cool_down_until > now:
                logger.debug(f"账号 {account.id} 在冷却中，跳过")
                continue
            
            # Ollama特殊处理：跳过额度检查
            if account.vendor.lower() == "ollama":
                available.append(account)
                continue
            
            # 额度预判
            if not self._check_quota_sufficient(account, estimated_tokens):
                logger.debug(f"账号 {account.id} 额度不足，跳过")
                continue
            
            available.append(account)
        
        return available
    
    def _check_quota_sufficient(self, account: ModelAccount, estimated_tokens: int) -> bool:
        """检查账号额度是否充足

        统一余额逻辑：有效余额 = 初始额度(balance_remaining) - 当日本地用量(daily_used_*)
        - 有初始额度：按余额单位判断
        - 无初始额度（无余额接口厂商且未手动维护）：不做额度限制
        """
        if account.balance_remaining is None:
            return True

        if account.balance_unit == "token":
            used = account.daily_used_tokens or 0
            remaining = account.balance_remaining - used
            return remaining >= estimated_tokens

        elif account.balance_unit == "currency":
            # 预估消耗金额 = Token数 * 单价 / 1M
            estimated_cost = (estimated_tokens * (account.currency_rate or 0)) / 1_000_000
            used = account.daily_used_currency or 0
            remaining = account.balance_remaining - used
            return remaining >= estimated_cost

        return True
    
    async def _infer_previous_account(
        self,
        messages: list,
        model_name: str,
        estimated_tokens: int
    ) -> Optional[ModelAccount]:
        """
        从消息历史推断之前使用的账号（会话粘性）
        
        策略：
        1. 检查是否有 assistant 消息（表示多轮对话）
        2. 查询最近的成功请求日志
        3. 返回最近使用且仍可用的账号
        """
        # 检查是否有 assistant 消息
        has_assistant = any(msg.get('role') == 'assistant' for msg in messages)
        if not has_assistant:
            return None  # 新对话，无需粘性
        
        # 查询最近10分钟内的成功请求
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        
        try:
            result = await self.session.execute(
                select(RequestLog)
                .where(RequestLog.created_at > cutoff)
                .where(RequestLog.status == 'success')
                .where(RequestLog.model_name.in_(
                    select(ModelAccount.model_name)
                    .where(ModelAccount.virtual_model == model_name)
                ))
                .order_by(RequestLog.created_at.desc())
                .limit(1)
            )
            last_log = result.scalar_one_or_none()
            
            if not last_log:
                return None
            
            # 获取该账号
            account_result = await self.session.execute(
                select(ModelAccount)
                .where(ModelAccount.id == last_log.account_id)
                .where(ModelAccount.is_enable == True)
            )
            account = account_result.scalar_one_or_none()
            
            if not account:
                return None
            
            # 检查账号是否仍然可用
            now = datetime.utcnow()
            
            # 检查冷却状态
            if account.cool_down_until and account.cool_down_until > now:
                logger.debug(f"推断的账号 {account.id} 在冷却中")
                return None
            
            # 检查额度
            if account.vendor.lower() != "ollama" and not self._check_quota_sufficient(account, estimated_tokens):
                logger.debug(f"推断的账号 {account.id} 额度不足")
                return None
            
            return account
            
        except Exception as e:
            logger.warning(f"推断之前账号失败: {e}")
            return None
    
    async def _select_sequential(self, accounts: List[ModelAccount]) -> Optional[ModelAccount]:
        """
        顺序耗尽策略（委托给 FreeFirstSelector）
        按优先级降序排序，选择第一个可用账号
        """
        # M1: 委托给 Selector 策略类，行为与原实现完全一致
        return self._free_first_selector.select(accounts)
    
    async def _select_round_robin(
        self,
        accounts: List[ModelAccount],
        model_name: str
    ) -> Optional[ModelAccount]:
        """
        轮询策略（委托给 RoundRobinSelector）
        轮流选择账号，忽略优先级
        """
        # M1: 委托给 Selector 策略类，行为与原实现完全一致
        return self._round_robin_selector.select(accounts, model_name=model_name)
    
    async def mark_account_failed(self, account_id: int):
        """标记账号失败，进入冷却"""
        result = await self.session.execute(
            select(ModelAccount).where(ModelAccount.id == account_id)
        )
        account = result.scalar_one_or_none()
        
        if account:
            from datetime import timedelta
            account.cool_down_until = datetime.utcnow() + timedelta(seconds=account.cool_down_seconds)
            await self.session.commit()
            logger.warning(f"账号 {account_id} 进入冷却，直到 {account.cool_down_until}")
    
    async def deduct_quota(
        self,
        account_id: int,
        prompt_tokens: int,
        completion_tokens: int
    ) -> Tuple[float, bool]:
        """
        记录账号消耗（统一余额逻辑下的本地统计）

        - 不修改初始额度(balance_remaining)，余额以厂商为准（每日同步覆盖）
        - 实时累加：当日用量(daily_used_*) + 累计用量(total_*)
        - 预计余额 = 初始额度 - 当日用量（由 UI 计算展示）
        - 不计算具体费用，仅做 token 计数

        Returns:
            (保留兼容返回值, 是否计费成功)
        """
        result = await self.session.execute(
            select(ModelAccount).where(ModelAccount.id == account_id)
        )
        account = result.scalar_one_or_none()
        
        if not account:
            return 0.0, False
        
        # 实际消耗金额（按厂商结算单价，用于当日用量/累计金额统计）
        cost = (
            ((prompt_tokens + completion_tokens) * (account.currency_rate or 0)) / 1_000_000
        )
        
        # 本地消耗统计：当日用量 + 累计用量（不碰初始额度）
        account.total_prompt_tokens += prompt_tokens
        account.total_completion_tokens += completion_tokens
        account.total_used_currency = (account.total_used_currency or 0) + cost
        account.daily_used_tokens = (account.daily_used_tokens or 0) + prompt_tokens + completion_tokens
        account.daily_used_currency = (account.daily_used_currency or 0) + cost
        
        await self.session.commit()
        
        logger.info(f"账号 {account_id} 记录消耗: {prompt_tokens}+{completion_tokens} tokens, "
                   f"金额: ¥{cost:.4f}")
        
        return 0.0, True
