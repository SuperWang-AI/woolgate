# WoolGate 插件开发指南

> 版本：v0.7.1 | 最后更新：2026-09-21

## 目录

1. [插件系统概述](#1-插件系统概述)
2. [快速开始：5分钟创建你的第一个插件](#2-快速开始5分钟创建你的第一个插件)
3. [插件元信息规范](#3-插件元信息规范)
4. [五大扩展点详解](#4-五大扩展点详解)
5. [插件配置管理](#5-插件配置管理)
6. [插件上下文与数据隔离](#6-插件上下文与数据隔离)
7. [开发最佳实践](#7-开发最佳实践)
8. [调试与排错](#8-调试与排错)
9. [插件发布与分发](#9-插件发布与分发)

---

## 1. 插件系统概述

### 1.1 设计理念

WoolGate 采用"核心精简 + 插件扩展"的架构设计：

- **核心层**：请求接入、路由决策、账号选择、上下文管理、执行转发——保持稳定，不轻易改动
- **插件层**：通过标准化的扩展点（插口），允许开发者在不修改核心代码的情况下扩展功能

### 1.2 五大扩展点

| 扩展点类型 | API | 用途 | 典型场景 |
|-----------|-----|------|---------|
| **生命周期钩子** | `register_hook()` | 在请求处理的9个阶段插入逻辑 | 请求过滤、日志记录、成本统计 |
| **SPI实现** | `register_spi()` | 替换核心组件的实现 | 自定义路由策略、自定义选择器 |
| **页面路由** | `register_page()` | 注入独立管理后台页面 | 余额看板、统计报表 |
| **导航菜单** | `register_nav_item()` | 在侧边栏添加菜单项 | 插件页面入口 |
| **组件挂载** | `register_component()` | 在预设位置注入UI组件 | 首页仪表盘、账号卡片底部 |
| **配置界面** | `register_config()` | 注入插件配置表单 | 阈值设置、开关控制 |

### 1.3 请求处理的9个阶段（插口）

```
客户端请求
    ↓
1. 请求接入（security）── 安全校验、鉴权
    ↓
2. 前置钩子（route.before）── 请求过滤、修改
    ↓
3. 意图分类（classifier）── 智能分类请求类型
    ↓
4. 路由决策（router）── 选择目标模型
    ↓
5. 账号选择（selector）── 选择具体账号/Key
    ↓
6. 上下文管理（context）── 会话上下文处理
    ↓
7. 执行转发（adapter）── 转发请求到厂商API
    ↓
8. 后置钩子（route.after）── 响应处理、修改
    ↓
9. 日志存储（store）── 记录请求/响应日志
    ↓
返回客户端
```

---

## 2. 快速开始：5分钟创建你的第一个插件

### 2.1 创建插件文件

在 `plugins/` 目录下创建 `hello_world.py`：

```python
"""
WoolGate Hello World 示例插件

这是一个最小化的插件示例，演示如何使用 WoolGate 插件系统的核心API。
功能：
1. 注册独立页面 /admin/hello-world
2. 注册导航菜单项
3. 注册 route.before 钩子（日志打印）

启用方式：设置环境变量 WOOLGATE_PLUGINS=plugins.hello_world
"""
import logging
from app.extensions.sdk import (
    register_hook, register_page, register_nav_item,
)

logger = logging.getLogger(__name__)

# 插件元信息（必须定义，用于插件管理页面展示）
PLUGIN_NAME = "hello_world"
PLUGIN_VERSION = "1.0.0"
PLUGIN_AUTHOR = "Your Name"
PLUGIN_DESCRIPTION = "Hello World 示例插件：演示插件系统的核心API用法"
PLUGIN_TAGS = ["示例", "入门", "Hello World"]


# ══════════════════════════════════════════════════════════════
# 1. 注册独立页面
# ══════════════════════════════════════════════════════════════
def render_hello_page():
    """渲染 Hello World 页面（在 NiceGUI 页面上下文中执行）"""
    from nicegui import ui

    ui.label("👋 Hello World!").classes("text-4xl font-bold text-gray-800")
    ui.label("这是你的第一个 WoolGate 插件！").classes("text-lg text-gray-600 mt-4")

    with ui.card().classes("mt-6 p-6 bg-blue-50"):
        ui.label("🎉 恭喜！").classes("text-xl font-bold text-blue-800")
        ui.label("你已经成功创建并加载了一个 WoolGate 插件。").classes("text-blue-700 mt-2")
        ui.label("这个页面是通过 register_page() API 注册的。").classes("text-blue-600 mt-1")


# 注册页面路由（最终路径为 /admin/hello-world）
register_page("/hello-world", "Hello World", render_hello_page)


# ══════════════════════════════════════════════════════════════
# 2. 注册导航菜单项
# ══════════════════════════════════════════════════════════════
register_nav_item("🧪 Hello World", "/hello-world", icon="science")


# ══════════════════════════════════════════════════════════════
# 3. 注册生命周期钩子
# ══════════════════════════════════════════════════════════════
@register_hook("route.before", priority=1000)
async def hello_world_hook(ctx):
    """
    route.before 钩子：在路由决策前执行。

    Args:
        ctx: PipelineContext 对象，包含请求的所有上下文信息
    """
    logger.info(f"[Hello World] 收到请求: {ctx.request.path if hasattr(ctx, 'request') else 'unknown'}")
    # 钩子可以修改 ctx（请求上下文），但要小心不要破坏核心逻辑
    # ctx.set("hello_world_visited", True)  # 在插件自己的命名空间中存储数据


logger.info("[Hello World] 插件加载完成！")
```

### 2.2 启用插件

在 `.env` 文件中添加：

```bash
WOOLGATE_PLUGINS=plugins.hello_world
```

如果有多个插件，用逗号分隔：

```bash
WOOLGATE_PLUGINS=plugins.balance_monitor,plugins.hello_world
```

### 2.3 重启服务

```bash
docker compose up -d --build
```

### 2.4 验证效果

1. **导航菜单**：打开管理后台，侧边栏会出现 "🧪 Hello World" 菜单项
2. **独立页面**：访问 `http://localhost:8765/admin/hello-world`，看到 Hello World 页面
3. **钩子日志**：发送任意请求，查看日志中是否有 `[Hello World] 收到请求`
4. **插件管理**：访问 `http://localhost:8765/admin/plugins`，在插件详情中看到 hello_world 插件

---

## 3. 插件元信息规范

每个插件必须在模块级别定义以下元信息常量：

```python
PLUGIN_NAME = "your_plugin_name"        # 插件名称（小写字母+下划线，唯一标识）
PLUGIN_VERSION = "1.0.0"                 # 语义化版本号
PLUGIN_AUTHOR = "Your Name"              # 作者名称
PLUGIN_DESCRIPTION = "插件功能描述"       # 一句话描述（建议不超过100字）
PLUGIN_TAGS = ["标签1", "标签2"]          # 功能标签（用于分类和搜索）
```

### 命名规范

- `PLUGIN_NAME`：小写字母、数字、下划线，必须以字母开头，全局唯一
- 建议与文件名一致（如 `hello_world.py` → `PLUGIN_NAME = "hello_world"`）
- 避免使用核心保留词：`core`、`system`、`internal`、`woolgate`

### 版本规范

采用语义化版本（SemVer）：`主版本.次版本.修订号`

- **主版本**：不兼容的API改动
- **次版本**：向下兼容的功能性新增
- **修订号**：向下兼容的问题修正

---

## 4. 五大扩展点详解

### 4.1 生命周期钩子（Hook）

钩子是最常用的扩展点，允许在请求处理的9个阶段插入自定义逻辑。

#### 可用的钩子事件

| 事件名 | 阶段 | 可修改 | 可阻断 | 说明 |
|--------|------|--------|--------|------|
| `security.before` | 1.请求接入前 | ❌ | ✅ | 安全校验前 |
| `route.before` | 2.路由决策前 | ✅ | ✅ | 最常用，可过滤/修改请求 |
| `classifier.before` | 3.意图分类前 | ✅ | ❌ | 分类前 |
| `classifier.after` | 3.意图分类后 | ✅ | ❌ | 分类后，可修改分类结果 |
| `router.before` | 4.路由决策前 | ✅ | ❌ | 路由前 |
| `router.after` | 4.路由决策后 | ✅ | ❌ | 路由后，可修改路由决策 |
| `selector.before` | 5.账号选择前 | ✅ | ❌ | 选号前 |
| `selector.after` | 5.账号选择后 | ✅ | ❌ | 选号后，可修改选号决策 |
| `context.before` | 6.上下文管理前 | ✅ | ❌ | 上下文处理前 |
| `context.after` | 6.上下文管理后 | ✅ | ❌ | 上下文处理后 |
| `adapter.before` | 7.执行转发前 | ✅ | ✅ | 转发前，可修改请求体 |
| `adapter.after` | 7.执行转发后 | ✅ | ❌ | 转发后，可修改响应 |
| `route.after` | 8.后置钩子 | ✅ | ❌ | 响应返回前 |
| `error.occurred` | 异常发生时 | ❌ | ❌ | 错误处理 |
| `store.before` | 9.日志存储前 | ✅ | ❌ | 日志存储前 |

#### 注册钩子

```python
from app.extensions.sdk import register_hook

@register_hook("route.before", priority=1000)
async def my_hook(ctx):
    """
    钩子函数

    Args:
        ctx: PipelineContext 对象
            - ctx.request: 请求对象
            - ctx.messages: 消息列表
            - ctx.target_model: 目标模型（路由后）
            - ctx.selected_account: 选中的账号（选号后）
            - ctx.response: 响应对象（转发后）
            - ctx.extensions: 插件命名空间字典
    """
    # 读取请求信息
    path = ctx.request.path if hasattr(ctx, 'request') else 'unknown'

    # 在自己的命名空间中存储数据（不会影响其他插件）
    ctx.extensions.setdefault("my_plugin", {})["visited"] = True

    # 可改写的决策字段（仅 after 类钩子）
    # ctx.target_model = "new-model"  # 修改目标模型

    # 阻断请求（仅 before 类钩子，抛出 HookBlocked）
    # from app.extensions.hooks import HookBlocked
    # raise HookBlocked("请求被拒绝")
```

#### 优先级

- `priority` 数字越小，越先执行
- 默认值为 1000
- 同优先级按注册顺序执行

#### 异常隔离

- 钩子函数抛出异常时，会被捕获并记录日志，不会影响核心流程
- 只有 `HookBlocked` 异常会向上传播，用于主动阻断请求

---

### 4.2 SPI实现（Service Provider Interface）

SPI 允许替换核心组件的实现，是更深度的扩展方式。

#### 可用的SPI类型

| SPI类型 | 说明 | 核心默认实现 |
|---------|------|-------------|
| `classifier` | 意图分类器 | 基于关键词的简单分类 |
| `router` | 路由器 | 低资费优先路由 |
| `selector` | 选择器 | 轮询/故障转移选择 |
| `context` | 上下文管理器 | 本地内存上下文 |
| `security` | 安全守卫 | Noop（无操作） |
| `adapter` | 模型适配器 | OpenAI兼容适配器 |
| `store` | 日志存储 | SQLite存储 |

#### 注册SPI实现

```python
from app.extensions.sdk import register_spi

class MyCustomRouter:
    """自定义路由器"""

    async def route(self, ctx):
        """
        路由决策

        Args:
            ctx: PipelineContext 对象

        Returns:
            str: 目标模型名称
        """
        # 自定义路由逻辑
        return "my-custom-model"

# 注册SPI实现
# spi_type: SPI类型
# name: 实现名称（用于配置中选择）
# impl: 实现对象（需要符合对应接口）
register_spi("router", "my_router", MyCustomRouter())
```

#### SPI与钩子的区别

| 维度 | 钩子（Hook） | SPI实现 |
|------|-------------|---------|
| 定位 | 在现有流程中插入逻辑 | 替换核心组件的实现 |
| 数量 | 可注册多个，按优先级执行 | 同名覆盖，后注册优先 |
| 复杂度 | 简单，适合日志/过滤/统计 | 复杂，适合深度定制 |
| 风险 | 低（异常隔离） | 高（直接影响核心流程） |

---

### 4.3 页面路由注入

允许插件注册独立的管理后台页面。

#### 注册页面

```python
from app.extensions.sdk import register_page

def render_my_page():
    """渲染页面（在 NiceGUI 页面上下文中执行）"""
    from nicegui import ui

    ui.label("我的插件页面").classes("text-2xl font-bold")
    # ... 更多UI组件

# route: 页面路由（最终路径为 /admin/{route}）
# title: 页面标题
# render_func: 渲染函数
register_page("/my-page", "我的页面", render_my_page)
```

#### 页面渲染函数

- 渲染函数在 NiceGUI 页面上下文中执行，可以直接使用 `ui.*` 组件
- 不需要手动调用 `ui.run()`，框架会自动处理
- 可以使用 NiceGUI 的所有组件和特性

---

### 4.4 导航菜单扩展

允许在管理后台侧边栏添加菜单项。

#### 注册菜单项

```python
from app.extensions.sdk import register_nav_item

# label: 菜单显示名称
# route: 点击跳转的路由
# icon: 可选图标（emoji 或字符）
register_nav_item("📊 统计报表", "/stats", icon="bar_chart")
```

#### 注意事项

- 菜单项会显示在核心菜单项之后
- 建议使用 emoji 作为图标，保持视觉一致性
- route 应该与 `register_page()` 注册的路由对应

---

### 4.5 组件挂载点

允许在预设的UI位置注入组件。

#### 预设挂载点

| 挂载点ID | 位置 | 说明 |
|----------|------|------|
| `dashboard.widgets` | 首页仪表盘 | 首页的小部件区域 |
| `account.card.footer` | 账号卡片底部 | 每个账号卡片的底部 |
| `log.detail.extra` | 日志详情页 | 日志详情的额外信息区域 |
| `config.page.extra` | 系统配置页 | 系统配置页面的额外区域 |

#### 注册组件

```python
from app.extensions.sdk import register_component, UI_HOOK_DASHBOARD_WIDGETS

def render_dashboard_widget():
    """渲染仪表盘组件（在 NiceGUI 上下文中执行）"""
    from nicegui import ui

    with ui.card().classes("p-4"):
        ui.label("我的统计").classes("text-lg font-bold")
        ui.label("数据: 123").classes("text-gray-600")

# hook_point: 挂载点ID
# render_func: 渲染函数
# priority: 优先级（数字越小越靠前，默认100）
register_component(UI_HOOK_DASHBOARD_WIDGETS, render_dashboard_widget, priority=100)
```

#### 自定义挂载点

除了预设挂载点，插件也可以注册自定义挂载点：

```python
register_component("my_custom_hook_point", render_func)
```

但自定义挂载点需要主程序或其他插件支持才能显示。

---

### 4.6 配置界面注入

允许插件注册配置表单，在统一的插件配置页面展示和保存。

#### 注册配置

```python
from app.extensions.sdk import register_config

CONFIG_SCHEMA = {
    "api_key": {
        "type": "string",           # 字段类型：string/number/boolean/select/textarea
        "label": "API密钥",          # 显示标签
        "default": "",               # 默认值
        "help": "请输入API密钥",     # 帮助文本
    },
    "threshold": {
        "type": "number",
        "label": "阈值",
        "default": 0.5,
        "help": "触发阈值",
    },
    "enabled": {
        "type": "boolean",
        "label": "启用功能",
        "default": True,
    },
    "mode": {
        "type": "select",
        "label": "模式",
        "default": "auto",
        "options": [                  # select类型需要提供选项
            {"value": "auto", "label": "自动"},
            {"value": "manual", "label": "手动"},
        ],
    },
    "description": {
        "type": "textarea",
        "label": "描述",
        "default": "",
    },
}

def on_config_saved(config):
    """配置保存时的回调函数"""
    print(f"配置已保存: {config}")

register_config(
    schema=CONFIG_SCHEMA,
    default={
        "api_key": "",
        "threshold": 0.5,
        "enabled": True,
        "mode": "auto",
        "description": "",
    },
    on_save=on_config_saved,  # 可选
)
```

#### 配置优先级

配置值的读取优先级（从高到低）：

1. **环境变量**：`WOOLGATE_PLUGIN_{PLUGIN_NAME}_{KEY}`
2. **数据库配置**：通过插件管理页面保存的配置
3. **默认值**：`register_config()` 中定义的默认值

环境变量格式示例：

```bash
# 插件 plugins.hello_world 的 api_key 配置
WOOLGATE_PLUGIN_PLUGINS_HELLO_WORLD_API_KEY=my-secret-key
```

---

## 5. 插件配置管理

### 5.1 读取配置

```python
from app.extensions.sdk import get_plugin_config

# 在异步函数中读取配置
async def my_function():
    config = await get_plugin_config("plugins.hello_world")
    api_key = config.get("api_key", "")
```

### 5.2 保存配置

```python
from app.extensions.sdk import set_plugin_config

# 在异步函数中保存配置
async def save_my_config():
    await set_plugin_config("plugins.hello_world", {
        "api_key": "new-key",
        "threshold": 0.8,
    })
```

### 5.3 配置存储位置

插件配置存储在 `SystemConfig` 表的 `plugin_configs` JSON字段中，结构如下：

```json
{
  "plugins.hello_world": {
    "api_key": "xxx",
    "threshold": 0.5
  },
  "plugins.balance_monitor": {
    "warning_threshold": 5.0
  }
}
```

---

## 6. 插件上下文与数据隔离

### 6.1 PluginContext

每个插件都有自己的命名空间，通过 `PluginContext` 访问：

```python
from app.extensions.sdk import get_plugin

async def my_hook(ctx):
    # 获取插件自己的上下文视图
    plugin_ctx = get_plugin("my_plugin", ctx)

    # 读写自己的命名空间（不会影响其他插件）
    plugin_ctx.set("my_key", "my_value")
    value = plugin_ctx.get("my_key", "default")

    # 只读访问核心字段
    target_model = plugin_ctx.ctx.target_model

    # after类钩子可以改写决策字段
    # plugin_ctx.set_decision("target_model", "new-model")
```

### 6.2 数据隔离原则

- **插件命名空间隔离**：每个插件只能读写自己的 `ctx.extensions[plugin_name]`
- **核心字段只读**：插件不能直接修改核心字段（如 `ctx.messages`）
- **决策字段白名单**：只有 after 类钩子可以修改白名单内的决策字段
- **异常隔离**：插件异常不会影响核心流程

### 6.3 可改写的决策字段

只有以下字段可以通过 `set_decision()` 修改（仅 after 类钩子）：

- `target_model`：目标模型
- `router_decision`：路由决策
- `router_confidence`：路由置信度
- `selector_decision`：选择器决策
- `assembled_messages`：组装后的消息
- `degraded`：是否降级
- `degrade_reason`：降级原因
- `actual_cost`：实际成本

---

## 7. 开发最佳实践

### 7.1 插件结构模板

```python
"""
插件名称 - 一句话功能描述

功能：
1. 功能点1
2. 功能点2
3. 功能点3

启用方式：设置环境变量 WOOLGATE_PLUGINS=plugins.your_plugin
"""
import logging
from typing import TYPE_CHECKING

from app.extensions.sdk import (
    register_hook, register_page, register_nav_item,
    register_component, register_config,
)

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# 插件元信息
# ══════════════════════════════════════════════════════════════
PLUGIN_NAME = "your_plugin"
PLUGIN_VERSION = "1.0.0"
PLUGIN_AUTHOR = "Your Name"
PLUGIN_DESCRIPTION = "一句话描述插件功能"
PLUGIN_TAGS = ["标签1", "标签2"]

# ══════════════════════════════════════════════════════════════
# 配置定义
# ══════════════════════════════════════════════════════════════
CONFIG_SCHEMA = {
    # ... 配置字段定义
}

register_config(CONFIG_SCHEMA, default={
    # ... 默认值
})

# ══════════════════════════════════════════════════════════════
# 核心逻辑
# ══════════════════════════════════════════════════════════════

# ... 你的插件核心代码

# ══════════════════════════════════════════════════════════════
# 注册扩展点
# ══════════════════════════════════════════════════════════════

# ... 注册钩子、页面、菜单、组件等

logger.info(f"[{PLUGIN_NAME}] 插件加载完成 (v{PLUGIN_VERSION})")
```

### 7.2 性能优化

1. **懒加载**：重型依赖在使用时才导入，避免插件加载时拖慢启动
2. **缓存**：频繁计算的结果使用缓存，避免重复计算
3. **异步**：IO操作使用异步，避免阻塞事件循环
4. **节流**：钩子中的重型操作使用节流，避免每个请求都执行

### 7.3 安全注意事项

1. **不要硬编码密钥**：使用配置或环境变量
2. **验证用户输入**：不要信任任何外部输入
3. **最小权限原则**：只申请必要的权限
4. **异常处理**：捕获并处理所有可能的异常
5. **日志脱敏**：日志中不要输出敏感信息（API密钥、密码等）

### 7.4 兼容性

1. **版本兼容**：注意 WoolGate 核心API的版本变化
2. **降级方案**：核心功能不可用时，提供降级方案
3. **配置默认值**：所有配置都要有合理的默认值

---

## 8. 调试与排错

### 8.1 查看插件加载状态

访问插件管理页面：`http://localhost:8765/admin/plugins`

#### 页面布局

插件管理页面采用左右分栏布局：

**左侧：接口插座概览（程序执行阶段）**
- 按请求处理的9个阶段展示所有插口（Hook + SPI）
- 每个节点卡片显示该阶段已注册的插件
- 点击概览中的插件名称，右侧对应插件卡片会**闪烁5秒**定位

**右侧：插件详情**
- 展示每个插件的完整信息：名称、版本、描述、作者、注册的扩展点列表
- 配置区域：插件专属配置界面

#### 导航菜单

插件的前端页面通过**下拉菜单**挂载到导航栏：
- 导航栏显示「🔌 插件」下拉入口
- 鼠标**悬停（hover）**自动展开下拉菜单
- 下拉列表展示所有有前端页面的插件（无前端页面的插件不显示）
- 点击菜单项打开对应插件页面

#### 插件清单

点击「插件清单」按钮可查看所有插件的完整列表，包括：
- 插件名称、版本、作者
- 类型（内置/外置）
- 状态（启用/禁用）
- 注册的扩展点数量

### 8.2 查看日志

```bash
# 查看容器日志
docker logs woolgate -f

# 过滤插件相关日志
docker logs woolgate 2>&1 | grep -i "plugin\|sdk\|hook"

# 过滤特定插件日志
docker logs woolgate 2>&1 | grep -i "hello_world"
```

### 8.3 常见问题

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| 插件未加载 | 环境变量未配置 | 检查 `.env` 中的 `WOOLGATE_PLUGINS` |
| 插件加载报错 | 代码语法错误 | 查看日志中的错误信息 |
| 钩子未执行 | 事件名错误 | 检查 `register_hook()` 的事件名 |
| 页面404 | 路由未注册 | 检查 `register_page()` 的路由 |
| 配置不生效 | 配置名错误 | 检查 `register_config()` 的 schema 键名 |
| 数据冲突 | 命名空间冲突 | 使用 `PLUGIN_NAME` 作为命名空间前缀 |

### 8.4 开发模式调试

在开发环境中，可以添加更多调试日志：

```python
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # 开发环境设置为DEBUG
```

---

## 9. 插件发布与分发

### 9.1 插件目录结构

```
plugins/
├── __init__.py              # 包初始化文件（空文件）
├── hello_world.py           # Hello World 示例插件
├── balance_monitor.py       # 余额监控插件
└── your_plugin.py           # 你的插件
```

### 9.2 发布检查清单

发布前请确认：

- [ ] 插件元信息完整（名称、版本、作者、描述、标签）
- [ ] 所有配置都有合理的默认值
- [ ] 代码通过语法检查（`python -m py_compile`）
- [ ] 异常处理完善，不会导致核心流程崩溃
- [ ] 日志中不包含敏感信息
- [ ] 文档完善（README、使用说明）
- [ ] 测试通过（功能测试、性能测试）

### 9.3 版本升级注意事项

1. **向后兼容**：新版本尽量保持向后兼容
2. **配置迁移**：配置结构变化时，提供迁移逻辑
3. **变更日志**：记录每个版本的变更内容
4. **降级方案**：升级失败时，提供降级方案

---

## 附录

### A. 完整API参考

| API | 说明 |
|-----|------|
| `register_hook(event, priority)` | 注册生命周期钩子（装饰器） |
| `register_spi(spi_type, name, impl)` | 注册SPI实现 |
| `register_page(route, title, render_func)` | 注册独立页面 |
| `register_nav_item(label, route, icon)` | 注册导航菜单项 |
| `register_component(hook_point, render_func, priority)` | 注册组件到挂载点 |
| `register_config(schema, default, on_save)` | 注册配置表单 |
| `get_plugin_config(plugin_name)` | 异步读取插件配置 |
| `set_plugin_config(plugin_name, config)` | 异步保存插件配置 |
| `get_plugin(name, ctx)` | 获取插件上下文视图 |
| `PluginContext` | 插件上下文类 |

### B. 预设挂载点常量

```python
from app.extensions.sdk import (
    UI_HOOK_DASHBOARD_WIDGETS,      # "dashboard.widgets"
    UI_HOOK_ACCOUNT_CARD_FOOTER,     # "account.card.footer"
    UI_HOOK_LOG_DETAIL_EXTRA,        # "log.detail.extra"
    UI_HOOK_CONFIG_PAGE_EXTRA,       # "config.page.extra"
)
```

### D. 学习型路由与插件

WoolGate v0.7.0+ 内置学习型选号路由，插件可以通过以下方式参与或影响学习过程：

**学习机制说明：**
- 系统每小时自动聚合最近7天的请求日志（滑动窗口，时间衰减）
- 按 (账号×模型×路由模型) 统计：请求数、成功数、流式中断数、重试数、平均成本
- 综合质量分 = 成功率 × (1-中断率) × (1-重试率)
- 有效成本 = 平均实际成本 / 综合质量分（质量越低，有效成本越高）
- 选号排序：免费优先 → 有效成本升序 → 价格升序 → 余额降序 → id降序

**插件可参与的方式：**
1. 通过 `selector.before` 钩子修改候选账号列表
2. 通过 `selector.after` 钩子修改选号结果
3. 通过 `adapter.after` 钩子记录自定义质量信号（写入 RequestLog.implicit_signal）
4. 自定义 SPI 选号策略（`register_spi("selector", "my_strategy", MySelector)`）

**相关源码：**
- 学习聚合：`app/services/performance_learner.py`
- 选号策略：`app/pipeline/selector/cost_first.py`
- 数据模型：`app/models/database.py` → `ModelPerformance`

### C. 相关资源

- 示例插件：`plugins/hello_world.py`
- 完整插件：`plugins/balance_monitor.py`
- 插件SDK源码：`app/extensions/sdk.py`
- 钩子系统源码：`app/extensions/hooks.py`
- 插件加载器源码：`app/extensions/loader.py`

---

**如有问题或建议，欢迎提交 Issue 或 PR！**
