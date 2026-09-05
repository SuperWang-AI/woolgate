"""
数据库模型定义
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
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
    
    # 日志配置
    log_retention_days = Column(Integer, default=30, comment="日志保留天数")
    
    # 额度预警
    quota_warning_threshold = Column(Float, default=0.1, comment="额度预警阈值(0-1)")
    
    # 路由策略
    default_route_strategy = Column(String(20), default="sequential", 
                                   comment="sequential/round_robin")
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModelAccount(Base):
    """模型账号表"""
    __tablename__ = "model_account"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 基础信息
    vendor = Column(String(50), nullable=False, comment="厂商名称")
    virtual_model = Column(String(100), default="chat", comment="虚拟模型名(客户端请求)")
    model_name = Column(String(100), nullable=False, comment="真实模型ID(上游API)")
    api_key_encrypted = Column(Text, nullable=False, comment="加密后的API Key")
    base_url = Column(String(255), nullable=True, comment="接口地址")
    
    # 启用状态
    is_enable = Column(Boolean, default=True, comment="是否启用")
    
    # 调度配置
    priority = Column(Integer, default=50, comment="优先级(数值越大越优先)")
    route_strategy = Column(String(20), default="sequential", 
                           comment="sequential/round_robin")
    
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
    
    created_at = Column(DateTime, default=datetime.utcnow)
