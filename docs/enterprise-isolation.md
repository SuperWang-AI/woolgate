# 企业版 vs 开源版隔离方案（执行时按此执行）

> 记录时间：2026-09-17
> 状态：架构方向已定，企业版未开工。开工时严格按此三重隔离执行。

## 核心原则

不用分支隔离，用"开源仓库 + 闭源插件包"两层分离。
企业版代码**永远不进开源仓库目录树**。

## 三重隔离防线

### 第一重：物理隔离（最硬）

企业版目录独立，不在开源仓库目录树内：

```
~/woolgate/              ← 开源仓库（GitHub 公开，Apache-2.0）
~/woolgate-enterprise/   ← 企业版（私有，独立目录，独立 git）
```

物理上不在同一个 git 仓库里，`git add` 够不着企业代码，想误传都传不出去。

### 第二重：工程兜底

1. 开源仓库 `.gitignore` 显式排除企业版相关路径
2. git pre-commit hook：commit 前扫描是否含企业版标识（如 `enterprise_only=True`），命中即拦截
3. CI 增加一个 job：扫描代码是否引用了企业插件模块

### 第三重：研发协作侧（不可靠，仅兜底）

每次 commit/push 前检查 `git status` 是否有企业版文件混入。
**注意：这是"记得"，不是机制，不能作为主要保障。**

## 企业版加载机制（基于 v0.6.0 已有 SPI）

企业版实现以下 SPI，通过 `WOOLGATE_PLUGINS=/path/to/enterprise` 环境变量加载：

| SPI | 企业版实现 |
|---|---|
| SecurityGuard | 入站/出站内容审核、Prompt Injection 防护 |
| SessionStateStore | Redis 多租户会话存储 |
| register_hook | 配额校验、用量计费、审计日志钩子 |
| ClientAdapter | SSO/OIDC 接入层 |

## 分离点

| 层 | 开源版 | 企业版 |
|---|---|---|
| 代码 | GitHub 公开仓库，不含企业代码 | 私有仓库，独立版本号 |
| 运行 | 无企业插件 → 打印"社区版" | 加载企业插件 → 打印"企业版" |
| 升级 | `docker pull` 独立升级 | 插件包独立升级，不碰开源版 |

## 开工 Checklist（企业版启动时执行）

- [ ] 新建 `~/woolgate-enterprise/` 独立目录
- [ ] 按 `examples/plugins/minimal_plugin.py` 模板实现 SPI
- [ ] 开源仓库 `.gitignore` 补企业版路径排除
- [ ] 加 pre-commit hook 扫描企业版标识
- [ ] CI 加企业版代码引用扫描 job
- [ ] README 提一句"企业版通过插件解锁"
