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
- CI（GitHub Actions）包含 pytest 回归 + gitleaks 密钥扫描，PR 合并前必须全绿

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
