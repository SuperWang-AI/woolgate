# Contributing to WoolGate

欢迎为 WoolGate 贡献代码、文档或建议。本项目的核心目标是：**让大模型的使用更省钱、更简单**。任何能让用户少配置一步、少花一分钱、少踩一个坑的贡献都很有价值。

## 开发环境

```bash
# 1. 克隆仓库
git clone https://github.com/SuperWang-AI/woolgate.git
cd woolgate

# 2. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt # 开发依赖见 requirements-dev.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 GATEWAY_BEARER_TOKEN 与 ENCRYPTION_KEY（生成方式见 QUICKSTART.md）

# 4. 本地启动
python main.py
```

## 代码规范

- Python 3.10+，类型标注（typing）与 docstring 是硬性要求
- 数据模型变更必须附带迁移（见 `app/models/__init__.py` 的 `MIGRATIONS`）
- 新增管线策略遵循 `app/pipeline/` 下的接口抽象（Router / Selector / ContextManager）
- 前端（`app/ui/`）遵循现有 SPA 风格，不做整页刷新
- 不使用 emoji 做装饰（用户界面文案除外）

## 测试

```bash
pytest tests/   # 全量测试必须通过
```

- 新功能必须附带单元测试
- 修改路由/选择器/上下文逻辑时，运行 `pytest tests/ -k "router or selector or context"` 做定向回归
- 新增扩展机制改动时，运行 `pytest tests/test_extensions.py`（钩子/SPI/降级/租户前缀）
- CI（GitHub Actions）包含 pytest 回归 + gitleaks 密钥扫描，PR 合并前必须全绿

## 插件 / 组件开发（v0.6.0）

WoolGate 从 v0.6.0 起提供组件化/插件化扩展能力，完整契约见 `docs/extensions/`（01 上下文对象 / 02 插口与 SPI / 03 插件 SDK / 04 分类引擎 / 05 客户端适配器 / 06 租户隔离）。

**快速开始**：复制 `examples/plugins/minimal_plugin.py` 为你的插件模块，按需修改后设置 `WOOLGATE_PLUGINS=your.plugin.module` 启动即可。该示例覆盖四个最小用例：钩子注册、命名空间读写、决策字段改写（白名单）、SPI 注册。

**核心规则**：
- 钩子：`before` 可阻断（抛 `HookBlocked`），`after` 只可观测或改写白名单决策字段；
- 命名空间：插件只能读写 `ctx.extensions[你的插件名]`，互不可见、不落库；
- 异常隔离：钩子异常不拖垮管线；插件 import 失败不影响应用启动；
- 内置行为零变化：无插件注册时所有插口零开销，默认分类器与 v0.5.0 行为一致。

## 提交 PR

1. Fork 本仓库，从 `main` 切出功能分支（如 `feat/free-tier-wizard`）
2. 提交信息遵循 Conventional Commits（`feat:` / `fix:` / `docs:` / `chore:` / `refactor:`）
3. 运行测试并补充用例
4. 发起 PR 到 `main`，描述改动动机与验证方式
5. 维护者 review 通过后合并

## 议题规范

- Bug 报告：说明复现步骤、期望行为、实际行为、环境（OS / Docker / 版本）
- 功能建议：说明要解决的问题与目标用户场景
- 安全漏洞：**不要**公开提交 issue，请走 [SECURITY.md](SECURITY.md) 的流程

## 行为准则

- 友善、专业、对事不对人
- 尊重不同语言、经验水平的贡献者
- 讨论聚焦于技术问题本身

## 路线图

当前主线与规划见仓库 [ROADMAP](ROADMAP.md)（发布时提供）与项目主页。欢迎在 Discussions 参与讨论。
