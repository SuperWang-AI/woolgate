"""
数据库模型定义
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, JSON, UniqueConstraint
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class SystemConfig(Base):
    """系统配置表（单行记录）"""
    __tablename__ = "system_config"
    
    id = Column(Integer, primary_key=True, default=1)
    
    # 额度耗尽策略
    quota_exhaust_strategy = Column(String(50), default="auto_switch_next", 
                                   comment="auto_switch_next/return_warn_error/allow_pay_quota")
    
    # 重试配置
    max_retry_count = Column(Integer, default=3, comment="全局最大重试次数")
    cool_down_seconds = Column(Integer, default=300, comment="故障冷却秒数")
    
    # Ollama配置
    ollama_enabled = Column(Boolean, default=True, comment="Ollama调度总开关")
    ollama_base_url = Column(String(255), default="http://host.docker.internal:11434", 
                            comment="Ollama地址")
    embedding_local_plugin = Column(String(100), default="bge-small-zh",
                                     comment="本地Embedding模型名（Ollama）")
    
    # 日志配置
    log_retention_days = Column(Integer, default=30, comment="日志保留天数")
    

    # ── M1 架构重构：模型路由（选羊）──
    router_strategy = Column(String(20), default="off",
                             comment="路由策略: off/vector/llm（rules 策略已废弃）")
    router_config_json = Column(JSON, nullable=True,
                                comment="RouterConfig 序列化（领域原型、阈值、关键词表等）")

    # ── M1 架构重构：账号调度（薅羊毛）──
    selector_strategy = Column(String(20), default="pin",
                               comment="选号策略: pin/free-first/cost-first/sticky/failover/round-robin")
    selector_config_json = Column(JSON, nullable=True,
                                  comment="SelectorConfig 序列化（pin_model/pin_account_id 等）")

    # ── M1 架构重构：上下文管理 ──
    context_strategy = Column(String(20), default="passthrough",
                              comment="passthrough/window/summary")
    context_config_json = Column(JSON, nullable=True,
                                 comment="ContextConfig 序列化")

    # ── M1 架构重构：治理层（企业版）──
    tenant_enabled = Column(Boolean, default=False,
                            comment="多租户开关（企业版）")
    budget_enabled = Column(Boolean, default=False,
                            comment="配额预算开关（企业版）")

    # ── M1 架构重构：版本标识 ──
    edition = Column(String(20), default="opensource",
                     comment="opensource/enterprise（决定哪些策略可用）")

    # ── A2 启动意图引导（消灭用户侧配置）──
    onboarded = Column(Boolean, default=False, comment="是否完成启动引导")
    onboard_profile = Column(String(100), nullable=True, comment="引导应用的推荐配置模板名")

    # ── M5 对外模型名（网关统一入口）──
    virtual_entry_name = Column(String(50), default="woolgate",
                                comment="对外暴露的入口模型名（全局级，客户端统一用这个，智能路由自动映射真实模型；跟账号级的 default_model 不是一个层级）")

    # ── P0 技术债：模型参数约束配置化 ──
    model_param_constraints_json = Column(JSON, nullable=True,
        comment="模型参数约束覆盖表 {model_name: {param: value}}，为空则用内置默认值")

    # ── 插件系统：统一插件配置存储 ──
    plugin_configs = Column(JSON, nullable=True, default=dict,
        comment="所有插件的配置存储 {plugin_name: {config_key: value}}，通过插件SDK get_plugin_config/set_plugin_config 读写")

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModelAccount(Base):
    """模型账号表——真账号行（一个 API Key 一行）

    主从架构（T1 改造后）：
    - 本表承载账号级信息：key/base_url/余额/健康度/厂商
    - 模型级信息（能力/示例/向量/价格）在 ModelCatalog（挂 account_id）
    - default_model/default_model_name 语义为"账号默认模型"（兼容旧查询；匹配优先走 ModelCatalog）
    """
    __tablename__ = "model_account"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 基础信息
    vendor = Column(String(50), nullable=False, comment="厂商名称")
    default_model = Column(String(100), default="woolgate", comment="【已废弃，勿用】历史遗留字段，无代码使用；账号默认模型请用 default_model_name")
    default_model_name = Column(String(100), nullable=False, comment="账号默认模型名（T1 后降级，模型级信息在 ModelCatalog；原 model_name）")
    endpoint_id = Column(String(100), nullable=True, comment="Endpoint ID(如豆包/火山引擎需要,调用时优先使用)")
    api_key_encrypted = Column(Text, nullable=False, comment="加密后的API Key")
    base_url = Column(String(255), nullable=True, comment="接口地址")
    
    # 启用状态
    is_enable = Column(Boolean, default=True, comment="是否启用")
    
    # 调度配置
    priority = Column(Integer, default=50, comment="历史遗留优先级字段，CostFirstSelector 已不按此排序")
    # 重试配置
    retry_enable = Column(Boolean, default=True, comment="是否允许重试")
    cool_down_seconds = Column(Integer, default=300, comment="故障冷却时间")
    cool_down_until = Column(DateTime, nullable=True, comment="冷却结束时间")

    # 统一余额（初始额度 = 厂商真实余额，每日首次使用时同步一次）
    # 额度判断只走这一套：有效余额 = balance_remaining - 当日本地用量
    balance_remaining = Column(Float, nullable=True, comment="初始额度/厂商真实余额(自动获取或手动维护)")
    balance_unit = Column(String(20), nullable=True, comment="余额单位(token/currency)")
    balance_sync_date = Column(String(10), nullable=True, comment="最近余额同步日期(YYYY-MM-DD)")

    # 厂商内部结算单价(元/1M token)，用于把 token 消耗换算成金额
    currency_rate = Column(Float, default=0.0, comment="厂商内部结算单价(元/1M token)")

    # 本地消耗统计（当天 woolgate 内统计，实时更新）
    daily_used_tokens = Column(Integer, default=0, comment="当日消耗Token数")
    daily_used_currency = Column(Float, default=0.0, comment="当日消耗金额(元)")

    # 过期时间
    free_expire_time = Column(DateTime, nullable=True, comment="一次性额度过期时间")

    # 累计统计（token 计数，不计算具体费用）
    total_prompt_tokens = Column(Integer, default=0, comment="累计输入Token")
    total_completion_tokens = Column(Integer, default=0, comment="累计输出Token")
    total_used_currency = Column(Float, default=0.0, comment="累计消耗金额(元)")
    
    # 扩展参数
    extra_json = Column(JSON, nullable=True, comment="模型默认参数")
    
    # Key 验证状态（向导探测结果）
    key_verified = Column(Boolean, default=True, comment="API Key 是否已验证（向导探测结果）")

    # ── M1 架构重构：多租户地基（企业版）──
    tenant_id = Column(String(64), nullable=True, comment="租户ID（企业版，NULL=单租户模式）")

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RequestLog(Base):
    """请求日志表"""
    __tablename__ = "request_log"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 关联信息
    account_id = Column(Integer, nullable=True, comment="关联账号ID")
    vendor = Column(String(50), nullable=True, comment="厂商")
    model_name = Column(String(100), nullable=True, comment="模型")
    
    # Token消耗
    prompt_tokens = Column(Integer, default=0, comment="输入Token")
    completion_tokens = Column(Integer, default=0, comment="输出Token")
    total_tokens = Column(Integer, default=0, comment="总Token")
    
    # 请求状态
    status = Column(String(20), default="success", comment="success/failed")
    error_message = Column(Text, nullable=True, comment="错误信息")
    
    # 请求详情
    request_time = Column(DateTime, default=datetime.utcnow, comment="请求时间")
    response_time_ms = Column(Integer, default=0, comment="响应时间(毫秒)")
    
    # IP和路径
    client_ip = Column(String(50), nullable=True)
    endpoint = Column(String(100), nullable=True)

    # ── M1 架构重构：观测埋点 ──
    request_id = Column(String(64), nullable=True, comment="请求唯一ID，关联管线上下文")
    session_id = Column(String(64), nullable=True, comment="会话ID，用于学习型路由按会话聚合")
    routed_model = Column(String(100), nullable=True, comment="实际路由到的目标模型名（M4 后复用，原 domain_tag）")
    router_strategy = Column(String(20), nullable=True, comment="实际路由策略")
    selector_strategy = Column(String(20), nullable=True, comment="实际调度策略")
    context_strategy = Column(String(20), nullable=True, comment="实际上下文策略")
    switch_count = Column(Integer, default=0, comment="本次请求切换账号次数")
    summary_used = Column(Boolean, default=False, comment="是否使用了摘要压缩")
    tenant_id = Column(String(64), nullable=True, comment="租户ID（企业版）")

    # ── A3 学习型路由：反馈与隐式信号 ──
    user_feedback = Column(String(20), nullable=True, comment="用户显式反馈: up/down/neutral")
    feedback_at = Column(DateTime, nullable=True, comment="反馈时间")
    implicit_signal = Column(String(50), nullable=True,
                             comment="隐式信号: stream_interrupted(流式中断)/switch_retry(失败切换)/followup(继续追问)")

    # ── C5 学习型路由：成本/决策明细/分类引擎（样本标签）──
    estimated_cost = Column(Float, default=0.0, comment="估算成本(元)，路由后按预估token×单价")
    actual_cost = Column(Float, default=0.0, comment="实际成本(元)，执行后按实际token×单价")
    router_decision = Column(String(200), nullable=True, comment="路由决策明细（字符串格式：策略: 说明）")
    selector_decision = Column(String(200), nullable=True, comment="选号决策明细（字符串格式：策略: 说明）")
    classify_engine = Column(String(20), nullable=True, comment="实际分类引擎: vector/llm/off（local 预留未实现）")
    degraded = Column(Boolean, default=False, comment="是否降级兜底（分类失败/无可用账号回退等）")
    degrade_reason = Column(String(100), nullable=True, comment="降级原因描述")

    created_at = Column(DateTime, default=datetime.utcnow)


class RoundRobinState(Base):
    """轮询索引持久化表（解决重启归零问题）"""
    __tablename__ = "round_robin_state"

    model_name = Column(String(100), primary_key=True, comment="虚拟模型名")
    last_index = Column(Integer, default=0, comment="上次选中的索引")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModelPerformance(Base):
    """模型历史表现表（学习型路由选号信号）"""
    __tablename__ = "model_performance"
    __table_args__ = (
        UniqueConstraint("account_id", "model_name", "routed_model", name="uq_perf_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, nullable=False, comment="账号ID")
    model_name = Column(String(100), nullable=False, comment="模型名")
    routed_model = Column(String(50), nullable=True, comment="实际路由到的目标模型名（M4 后复用，原 domain_tag）")

    request_count = Column(Integer, default=0, comment="总请求数")
    success_count = Column(Integer, default=0, comment="成功数")
    interrupted_count = Column(Integer, default=0, comment="流式中断次数（stream_interrupted 信号统计）")
    retry_count = Column(Integer, default=0, comment="失败切换重试次数（switch_retry 信号统计）")
    avg_actual_cost = Column(Float, default=0.0, comment="平均实际成本(元)")

    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def success_rate(self) -> float:
        if self.request_count == 0:
            return 1.0
        return self.success_count / self.request_count

    @property
    def interrupted_rate(self) -> float:
        """流式中断率 = 中断次数 / 总请求数"""
        if self.request_count == 0:
            return 0.0
        return self.interrupted_count / self.request_count

    @property
    def retry_rate(self) -> float:
        """重试率 = 重试次数 / 总请求数"""
        if self.request_count == 0:
            return 0.0
        return self.retry_count / self.request_count

    @property
    def quality_score(self) -> float:
        """综合质量分 = 成功率 x (1-中断率) x (1-重试率)
        考虑了请求成功、流式不中断、不需要重试三个维度，越低说明账号质量越差。
        """
        sr = self.success_rate
        ir = self.interrupted_rate
        rr = self.retry_rate
        return sr * (1 - ir) * (1 - rr)

    @property
    def effective_cost(self) -> float:
        """有效成本 = 平均实际成本 / 综合质量分
        质量分低（成功率低、中断多、需重试）意味着实际需要多次请求，有效成本更高。
        """
        qs = self.quality_score
        if qs <= 0.01:
            return float("inf")
        return self.avg_actual_cost / qs

class SessionState(Base):
    """会话状态表（ContextManager 依赖，初期用 SQLite，可换 Redis）"""
    __tablename__ = "session_state"

    session_id = Column(String(64), primary_key=True, comment="会话ID")
    current_model = Column(String(100), nullable=True, comment="当前模型（滞回判定用）")
    current_account_id = Column(Integer, nullable=True, comment="当前账号（会话粘性）")
    summary = Column(Text, nullable=True, comment="异步维护的对话摘要")
    summary_version = Column(Integer, default=0, comment="摘要版本号，每次更新+1")
    turn_count = Column(Integer, default=0, comment="会话轮次")
    last_activity = Column(DateTime, default=datetime.utcnow, comment="最后活跃时间")
    created_at = Column(DateTime, default=datetime.utcnow)


class ModelCatalog(Base):
    """模型供应目录——模型能力清单（账号×模型行：一账号 N 模型，同模型跨账号可多行、单价独立）"""
    __tablename__ = "model_catalog"
    __table_args__ = (
        UniqueConstraint('account_id', 'model_name', name='uq_catalog_account_model'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, nullable=False, comment="关联账号ID（一账号 N 模型；同模型跨账号可多行）")
    vendor = Column(String(50), nullable=False, comment="厂商名称")
    model_name = Column(String(100), nullable=False, comment="真实模型ID（唯一性由 account_id+model_name 保证）")
    model_type = Column(String(20), default="chat", comment="模型类型: chat/embedding（image/audio 规划中，暂未实现）")
    display_name = Column(String(100), nullable=True, comment="展示名")
    capability_description = Column(Text, nullable=True, comment="能力描述（给 LLM 路由和 embedding 用）")
    capability_tags = Column(JSON, nullable=True, comment="能力标签: ['code','chat','vision']")
    examples = Column(JSON, nullable=True, comment="典型用户请求示例列表（List[str]，用于计算平均向量）")
    input_price = Column(Float, nullable=True, comment="输入单价 元/1M token")
    output_price = Column(Float, nullable=True, comment="输出单价 元/1M token")
    avg_latency = Column(Float, nullable=True, comment="平均延迟（秒），LLM 路由做延迟优化参考")
    context_window = Column(Integer, nullable=True, comment="上下文窗口")
    embedding_vector = Column(JSON, nullable=True, comment="能力描述的向量（List[float]，自动计算）")
    param_constraints_json = Column(JSON, nullable=True, comment="模型参数约束（如推理模型强制 temperature=1），JSON 格式；优先于全局默认约束")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# M3 企业化能力：API Key 表
# ══════════════════════════════════════════════════════════════

class ApiKey(Base):
    """API Key 表——绑定默认模型，企业化部署的权限控制"""
    __tablename__ = "api_key"

    id = Column(Integer, primary_key=True, autoincrement=True)
    api_key = Column(String(128), nullable=False, unique=True, index=True, comment="API Key 字符串")
    name = Column(String(100), nullable=True, comment="Key 名称，便于管理")
    default_model = Column(String(100), nullable=True, comment="默认模型；NULL=向量/LLM 路由自动选择")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VendorOverride(Base):
    """厂商目录用户覆盖层：内置目录(FREE_TIER_VENDORS) + 本表 = 最终目录（向导/一键配置读合并结果）"""
    __tablename__ = "vendor_override"

    id = Column(String(64), primary_key=True, comment="厂商 id（与内置目录 id 对齐则覆盖，新 id 则新增）")
    vendor_json = Column(Text, nullable=False, comment="完整厂商配置（JSON，与 FREE_TIER_VENDORS 字典同构）")
    is_deleted = Column(Boolean, default=False, comment="停用标记：True 表示从目录隐藏（用于下架内置厂商）")
    enabled = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
