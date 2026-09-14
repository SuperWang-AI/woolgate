"""
结构化日志工具（B1）——v0.6.0

关键路径（executor/api）输出 JSON 行日志，便于指标采集与日志分析。
与 PipelineContext.to_log_dict() 配合：核心事件携带请求上下文全字段。
"""
import json
import logging
from typing import Any, Dict, Optional


def log_event(
    logger_: logging.Logger,
    event: str,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """
    输出一条结构化事件日志（JSON 行）。

    Args:
        logger_: 目标 logger
        event: 事件名（如 executor.route_done）
        level: 日志级别
        fields: 结构化字段（推荐扁平键值；嵌套对象自动序列化）
    """
    record: Dict[str, Any] = {"event": event, **fields}
    logger_.log(level, json.dumps(record, ensure_ascii=False, default=str))


def ctx_event(
    logger_: logging.Logger,
    event: str,
    ctx: Optional[Any] = None,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """
    带管线上下文的事件日志：自动合并 ctx.to_log_dict() 字段。

    Args:
        ctx: PipelineContext（可为 None，字段自动跳过）
    """
    payload: Dict[str, Any] = dict(fields)
    if ctx is not None and hasattr(ctx, "to_log_dict"):
        try:
            payload.update(ctx.to_log_dict())
        except Exception:
            pass
    log_event(logger_, event, level=level, **payload)
