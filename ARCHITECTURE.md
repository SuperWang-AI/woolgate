# WoolGate 架构设计

> 版本：v2.0（2026-09-13）
> 状态：与实际代码一致
> 对应：app/pipeline / app/services / app/models

## 一、总体架构

```
客户端（Dify / OpenClaw / 任意 OpenAI 兼容工具）
        │  OpenAI 兼容协议（/v1/chat/completions, /v1/models）
        ▼
┌────────────────────────── WoolGate 网关 ──────────────────────────┐
│                                                                   │
│  API 层      app/routes/api.py                                     │
│              · 鉴权（GATEWAY_BEARER_TOKEN）                         │
│              · OpenAI 兼容协议适配（SSE 流式 / 非流式）              │
│              · 模型名解析：woolgate（智能路由） / 真实模型名（直连）   │
│                                                                   │
│  管线层      app/pipeline/executor.py                              │
│              · 任务分类（LLM / 向量 / 规则）                        │
│              · 路由决策（router）                                   │
│              · 模型选择（selector）                                 │
│              · 上下文管理（context_manager）                        │
│              · 执行与重试（failover）                               │
│                                                                   │
│  路由        app/pipeline/router/                                   │
│              · llm.py    — LLM 智能判题路由（分类+推荐）             │
│              · vector.py — 能力向量匹配路由                          │
│              · off.py    — 关闭智能路由（固定选择）                  │
│                                                                   │
│  选择器      app/pipeline/selector/                                 │
│              · free_first  — 免费模型优先                           │
│              · cost_first  — 成本优先（同模型跨账号选低价）           │
│              · sticky      — 会话粘性（流式中锁定账号）              │
│              · round_robin — 轮询                                    │
│              · pin         — 指定模型直连                            │
│              · failover    — 失败重试与降级                          │
│                                                                   │
│  上下文      app/pipeline/context_manager/                          │
│              · window      — 窗口截断                                │
│              · summary     — 摘要压缩                                │
│              · passthrough — 直通                                    │
│                                                                   │
│  账号层      app/models / app/services                              │
│              · 三层：厂商(Vendor) → 账号(ApiKey) → 模型(Model)       │
│              · Key Fernet 加密存储（ENCRYPTION_KEY）                 │
│              · 免费向导幂等去重（厂商别名匹配）                       │
│              · 能力向量（模型擅长领域，供 vector 路由使用）           │
│                                                                   │
│  管理后台    app/ui/admin.py（/admin）                              │
│              · 首页引导 / 免费向导 / 账号管理 / 模型菜单              │
│              · 管线策略 / 系统配置 / 日志                            │
│                                                                   │
└────────────────────────────────────────────────────────────────────┘
        │
        ▼
  模型池：DeepSeek / 通义 / Kimi / 智谱 / 豆包 / 混元 / 千帆 /
          硅基流动 / Ollama 本地 / 其他手动添加厂商
```

## 二、一次请求的完整路径

1. **客户端请求**：`POST /v1/chat/completions`，`model=woolgate`
2. **模型名解析**：`woolgate` → 走智能路由；精确真实模型名 → `pin` 选择器直连
3. **任务分类**：判定本次请求类型（编程 / 创意写作 / 对话 / 向量 / 通用）——由 LLM 或向量匹配完成，判题模型优先本地/免费
4. **候选筛选**：过滤出可用（启用 + 有额度 + 未冷却）且能力匹配的模型
5. **选择器决策**：按配置策略排序——免费优先 → 成本优先 → 兜底（按加入时间倒序）
6. **上下文处理**：按策略压缩或截断（流式安全：SSE 出流后锁定账号，禁止中途切换）
7. **执行与重试**：调用上游模型，失败按指数退避重试，超限自动降级到下一候选

## 三、省钱设计（核心）

| 手段 | 机制 |
|---|---|
| 免费额度 | 免费向导预置国内主流免费模型，一键接入即可用 |
| 任务分类路由 | 简单任务路由到免费/本地模型，复杂任务才上付费强模型 |
| 成本优先 | 同一模型跨账号价格不同时，选单价最低的账号 |
| 本地分流 | 本地模型承担 embedding、任务判题、简单直答 |
| 领域匹配 | 免费模型中优先选能力向量最匹配当前任务类型的 |

## 四、数据模型

```
Vendor（厂商）
  └── ApiKey（账号/Key，Fernet 加密）
        └── Model（模型：名称、类型、单价、能力向量、启用状态、优先级兜底）
```

- **同一厂商可多个 Key**（多账号摊额度）
- **同一模型可在多个账号下存在**（成本不同，供 cost_first 选择）
- **能力向量**：模型擅长领域描述 → embedding 后用于向量路由匹配

## 五、关键设计决策

1. **统一对外模型名 `woolgate`**：客户端永远只配一个模型名，网关内部路由；真实模型名直连作为高级能力保留。
2. **免费向导幂等**：重复一键配置同一厂商不会重复建号（厂商别名归一化匹配）。
3. **Key 语义**：账号下填新 Key 仅用于新增模型，留空则沿用已有 Key（不覆盖）。
4. **确定性兜底**：路由/选择器全部失效时，按模型加入时间倒序选取（最近添加的最优先）。
5. **流式安全**：SSE 出流即锁定会话账号，避免响应拼接错乱。

## 六、目录结构

```
app/
├── models/            # 数据模型与迁移（Vendor / ApiKey / Model / Log）
├── pipeline/          # 请求管线
│   ├── router/        #   路由决策（llm / vector / off）
│   ├── selector/      #   选择器（free_first / cost_first / sticky / round_robin / pin / failover）
│   ├── context_manager/ # 上下文（window / summary / passthrough）
│   ├── executor.py    #   管线执行器
│   └── config.py      #   管线配置
├── routes/            # API 路由
├── services/          # 业务服务（免费向导 / 模型目录 / 账号 / 余额 / 会话 / 调度）
├── ui/                # 管理后台
├── utils/             # 工具（加密 / token 估算）
└── config.py          # 全局配置
```
