"""
WoolGate Hello World 示例插件

这是一个最小化的插件示例，演示如何使用 WoolGate 插件系统的核心API。

功能：
1. 注册独立管理后台页面 /admin/hello-world
2. 注册导航菜单项（侧边栏显示 🧪 Hello World）
3. 注册 route.before 生命周期钩子（每次请求时打印日志）
4. 注册仪表盘组件（在首页显示 Hello World 小部件）

通过这个示例，你可以学习到：
- 插件元信息的定义规范
- 如何注册独立页面和导航菜单
- 如何注册生命周期钩子
- 如何注册UI组件到挂载点
- 如何使用插件上下文存储数据

启用方式：设置环境变量 WOOLGATE_PLUGINS=plugins.hello_world
多个插件用逗号分隔：WOOLGATE_PLUGINS=plugins.balance_monitor,plugins.hello_world
"""
import logging
from typing import TYPE_CHECKING

# 导入插件SDK的核心API
from app.extensions.sdk import (
    register_hook,           # 注册生命周期钩子
    register_page,            # 注册独立管理后台页面
    register_nav_item,        # 注册导航菜单项
    register_component,       # 注册UI组件到挂载点
    UI_HOOK_DASHBOARD_WIDGETS,  # 预设挂载点：首页仪表盘
)

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# 插件元信息（必须定义，用于插件管理页面展示）
# ══════════════════════════════════════════════════════════════

PLUGIN_NAME = "hello_world"           # 插件名称（小写字母+下划线，全局唯一）
PLUGIN_VERSION = "1.0.0"              # 语义化版本号：主版本.次版本.修订号
PLUGIN_AUTHOR = "WoolGate Team"       # 作者名称
PLUGIN_DESCRIPTION = "Hello World 示例插件：演示插件系统的核心API用法，包括页面注册、导航菜单、生命周期钩子和UI组件挂载"  # 一句话描述
PLUGIN_TAGS = ["示例", "入门", "Hello World", "教学"]  # 功能标签（用于分类和搜索）


# ══════════════════════════════════════════════════════════════
# 1. 注册独立管理后台页面
# ══════════════════════════════════════════════════════════════

def render_hello_page():
    """
    渲染 Hello World 页面。

    这个函数在 NiceGUI 页面上下文中执行，可以直接使用 ui.* 组件。
    访问路径：http://localhost:8765/admin/hello-world
    """
    from nicegui import ui

    # 页面标题
    ui.label("👋 Hello World!").classes("text-4xl font-bold text-gray-800")
    ui.label("欢迎使用 WoolGate 插件系统").classes("text-xl text-gray-600 mt-2")

    # 功能介绍卡片
    with ui.card().classes("mt-6 p-6 bg-gradient-to-r from-blue-50 to-purple-50"):
        ui.label("🎉 恭喜！你已经成功创建并加载了一个 WoolGate 插件").classes(
            "text-lg font-bold text-gray-800"
        )

        with ui.column().classes("mt-4 gap-3"):
            # 功能点1：页面注册
            with ui.row().classes("items-center gap-3"):
                ui.label("📄").classes("text-2xl")
                with ui.column().classes("gap-0"):
                    ui.label("独立页面注册").classes("font-bold text-gray-700")
                    ui.label("通过 register_page() 注册，路径为 /admin/hello-world").classes(
                        "text-sm text-gray-500"
                    )

            # 功能点2：导航菜单
            with ui.row().classes("items-center gap-3"):
                ui.label("🧭").classes("text-2xl")
                with ui.column().classes("gap-0"):
                    ui.label("导航菜单注册").classes("font-bold text-gray-700")
                    ui.label("通过 register_nav_item() 在侧边栏添加菜单项").classes(
                        "text-sm text-gray-500"
                    )

            # 功能点3：生命周期钩子
            with ui.row().classes("items-center gap-3"):
                ui.label("🪝").classes("text-2xl")
                with ui.column().classes("gap-0"):
                    ui.label("生命周期钩子").classes("font-bold text-gray-700")
                    ui.label("通过 register_hook() 在 route.before 阶段插入逻辑").classes(
                        "text-sm text-gray-500"
                    )

            # 功能点4：UI组件挂载
            with ui.row().classes("items-center gap-3"):
                ui.label("🧩").classes("text-2xl")
                with ui.column().classes("gap-0"):
                    ui.label("UI组件挂载").classes("font-bold text-gray-700")
                    ui.label("通过 register_component() 在首页仪表盘注入组件").classes(
                        "text-sm text-gray-500"
                    )

    # 技术细节
    with ui.card().classes("mt-6 p-6 bg-gray-50"):
        ui.label("📚 技术细节").classes("text-lg font-bold text-gray-800")
        with ui.column().classes("mt-3 gap-2 text-sm text-gray-600"):
            ui.label("• 插件文件位置：plugins/hello_world.py")
            ui.label("• 插件元信息：PLUGIN_NAME / PLUGIN_VERSION / PLUGIN_AUTHOR 等")
            ui.label("• 启用方式：环境变量 WOOLGATE_PLUGINS=plugins.hello_world")
            ui.label("• 钩子执行时机：每次请求的路由决策前（route.before）")
            ui.label("• 数据隔离：每个插件有独立的命名空间，互不干扰")

    # 下一步提示
    with ui.card().classes("mt-6 p-6 bg-green-50"):
        ui.label("🚀 下一步").classes("text-lg font-bold text-green-800")
        ui.label("查看 docs/plugin-development-guide.md 了解更多插件开发API和最佳实践").classes(
            "text-green-700 mt-2"
        )
        ui.label("你可以基于这个示例，开发自己的插件！").classes("text-green-600 mt-1")


# 注册页面路由
# 参数说明：
#   route: 页面路由路径（最终为 /admin/hello-world）
#   title: 页面标题
#   render_func: 页面渲染函数
register_page("/hello-world", "Hello World", render_hello_page)


# ══════════════════════════════════════════════════════════════
# 2. 注册导航菜单项
# ══════════════════════════════════════════════════════════════

# 在管理后台侧边栏添加菜单项
# 参数说明：
#   label: 菜单显示名称
#   route: 点击跳转的路由（与 register_page 的 route 对应）
#   icon: 可选图标（emoji 或字符）
register_nav_item("🧪 Hello World", "/hello-world", icon="science", description="插件开发示例，演示Hook/SPI/UI扩展点用法")


# ══════════════════════════════════════════════════════════════
# 3. 注册生命周期钩子
# ══════════════════════════════════════════════════════════════

@register_hook("route.before", priority=1000)
async def hello_world_route_before_hook(ctx: "PipelineContext"):
    """
    route.before 生命周期钩子。

    这个钩子在每次请求的路由决策前执行，可以用来：
    - 记录请求日志
    - 过滤/修改请求
    - 在插件命名空间中存储数据

    参数说明：
        ctx: PipelineContext 对象，包含请求的所有上下文信息
            - ctx.request: 请求对象
            - ctx.messages: 消息列表
            - ctx.extensions: 插件命名空间字典（每个插件有独立的命名空间）

    注意事项：
        - 钩子函数必须是 async 函数
        - 钩子异常会被捕获并记录日志，不会影响核心流程
        - 如需阻断请求，抛出 HookBlocked 异常（仅 before 类钩子）
    """
    # 获取请求路径（兼容不同的请求对象结构）
    request_path = "unknown"
    if hasattr(ctx, "request") and ctx.request is not None:
        if hasattr(ctx.request, "path"):
            request_path = ctx.request.path
        elif hasattr(ctx.request, "url"):
            request_path = str(ctx.request.url)

    # 在日志中打印请求信息
    logger.info(f"[Hello World] 收到请求: {request_path}")

    # 在插件自己的命名空间中存储数据（不会影响其他插件）
    # ctx.extensions 的结构：{plugin_name: {key: value}}
    if hasattr(ctx, "extensions"):
        ctx.extensions.setdefault("hello_world", {})["last_visit_path"] = request_path
        # 增加访问计数
        visit_count = ctx.extensions["hello_world"].get("visit_count", 0) + 1
        ctx.extensions["hello_world"]["visit_count"] = visit_count

        logger.debug(f"[Hello World] 插件访问计数: {visit_count}")


# ══════════════════════════════════════════════════════════════
# 4. 注册UI组件到挂载点
# ══════════════════════════════════════════════════════════════

def render_dashboard_widget():
    """
    渲染首页仪表盘组件。

    这个函数在 NiceGUI 上下文中执行，会被注入到首页仪表盘区域。
    通过 register_component() 注册到 UI_HOOK_DASHBOARD_WIDGETS 挂载点。
    """
    from nicegui import ui

    with ui.card().classes("p-4 bg-gradient-to-r from-pink-50 to-rose-50"):
        with ui.row().classes("items-center gap-3"):
            ui.label("👋").classes("text-3xl")
            with ui.column().classes("gap-0"):
                ui.label("Hello World 插件").classes("font-bold text-gray-800")
                ui.label("示例插件已加载运行").classes("text-xs text-gray-500")


# 注册组件到首页仪表盘挂载点
# 参数说明：
#   hook_point: 挂载点ID（使用预设常量 UI_HOOK_DASHBOARD_WIDGETS）
#   render_func: 组件渲染函数
#   priority: 优先级，数字越小越靠前（默认100）
register_component(UI_HOOK_DASHBOARD_WIDGETS, render_dashboard_widget, priority=200)


# ══════════════════════════════════════════════════════════════
# 插件加载完成日志
# ══════════════════════════════════════════════════════════════

logger.info(
    f"[{PLUGIN_NAME}] 插件加载完成！"
    f" (v{PLUGIN_VERSION}, 作者: {PLUGIN_AUTHOR})"
)
logger.info(
    f"[{PLUGIN_NAME}] 已注册: 1个页面 + 1个导航菜单 + 1个钩子 + 1个UI组件"
)
logger.info(
    f"[{PLUGIN_NAME}] 访问 http://localhost:8765/admin/hello-world 查看效果"
)
