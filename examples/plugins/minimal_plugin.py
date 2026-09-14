"""
WoolGate 最小示例插件（A3 / B4 模板）

展示插件开发的四个最小用例：
1. 钩子注册（register_hook）
2. 命名空间读写（ctx.set / ctx.get）
3. after 类钩子改写决策字段（ctx.set_decision）
4. SPI 替换（register_spi）

启用方式：设置环境变量 WOOLGATE_PLUGINS=examples.plugins.minimal_plugin
（或把本文件复制到你的插件模块，按需 import 进启动路径）。

本插件默认全部为演示逻辑（no-op 或仅打日志），可安全启用，不改变任何路由行为。
"""
import logging
from typing import TYPE_CHECKING

from app.extensions.sdk import register_hook, register_spi, PluginContext
from app.extensions.security import SecurityGuard

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)

PLUGIN_NAME = "minimal_plugin"


@register_hook("request.started", priority=1000)
async def on_request_started(ctx: "PipelineContext") -> None:
    """用例 1+2：请求开始时往自己的命名空间写入一个时间戳"""
    pc = PluginContext(ctx, PLUGIN_NAME)
    import time
    pc.set("started_at", time.time())
    logger.info(f"[{PLUGIN_NAME}] request.started 已记录")


@register_hook("route.after", priority=1000)
async def on_route_after(ctx: "PipelineContext") -> None:
    """用例 3：路由定稿后可改写决策字段（白名单内，如 target_model）"""
    pc = PluginContext(ctx, PLUGIN_NAME)
    started = pc.get("started_at")
    logger.info(f"[{PLUGIN_NAME}] route.after 触发，路由决策: {ctx.router_decision}")
    # 演示 set_decision 白名单机制（默认不实际改模型，避免影响行为）：
    # pc.set_decision("target_model", "qwen-turbo")
    pc.set("last_decision", ctx.router_decision)
    if started:
        logger.info(f"[{PLUGIN_NAME}] 请求耗时 {time.time() - started:.3f}s（写命名空间，不落库）")


class DemoAuditGuard(SecurityGuard):
    """用例 4：SPI 替换演示——只审计不打乱（不做任何拦截，仅日志）"""

    name = "demo-audit"

    async def check_input(self, ctx: "PipelineContext") -> None:
        logger.info(f"[{PLUGIN_NAME}] 入站审核（demo）: {len(ctx.original_messages or [])} 条消息")

    async def check_output(self, ctx: "PipelineContext", response: dict) -> None:
        logger.info(f"[{PLUGIN_NAME}] 出站审计（demo）: status={ctx.status}")


# 注意：注册 SPI 会覆盖默认 noop 守卫——本示例仅演示注册 API，
# 生产环境请按企业策略实现真正的审核逻辑。
# register_spi("security", "demo-audit", DemoAuditGuard())

logger.info(f"[{PLUGIN_NAME}] 插件已加载（演示模式，未改变任何路由行为）")
