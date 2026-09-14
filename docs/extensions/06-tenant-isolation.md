# 扩展契约 06：租户隔离与缓存边界

> 版本：v0.6.0 · 状态：已定稿 · 代码位置：`app/pipeline/context.py`、`app/models/database.py`

## 1. 数据隔离层级

| 数据 | 隔离维度 | 说明 |
|---|---|---|
| 账号（ModelAccount） | `tenant_id` 列 | 企业版按租户过滤账号池 |
| 模型目录（ModelCatalog） | 经账号间接隔离 | 账号 × 模型行挂在账号下 |
| 会话状态（SessionState） | **session_id 前缀** | 多租户下 session_id 必须形如 `{tenant_id}:{session}` |
| 请求日志（RequestLog） | `tenant_id` 列 | 审计/计费按租户聚合 |
| 插件命名空间 | `ctx.extensions[plugin_name]` | 插件间互不可见 |

## 2. SessionState 前缀约定

```python
def build_scoped_session_id(tenant_id: Optional[str], session_id: str) -> str:
    """多租户会话 key：{tenant_id}:{session_id}；单租户原样返回"""
    return f"{tenant_id}:{session_id}" if tenant_id else session_id
```

- 单租户（`tenant_id=None`）：行为与 v0.5.0 完全一致；
- 多租户：不同租户即使客户端传相同 session_id 也不串数据（上下文压缩、滞回判定天然隔离）；
- v0.6.0 在 `SessionStateService.get_or_create` 统一套用，**不要求存量数据迁移**（存量单租户 session_id 无前缀，保持原样）。

## 3. 缓存边界（组件化预留）

| 缓存 | 个人版（默认） | 企业版（组件替换点） |
|---|---|---|
| 管线配置缓存 | 进程内 60s TTL | 不变（配置是全局的） |
| 会话状态 | SQLite | Redis（`SessionStateStore` SPI 预留） |
| 分类/路由结果 | 不缓存 | Redis（可选） |
| 响应缓存 | 不缓存 | Redis（企业组件，计费需先于缓存） |

> 说明：`SessionStateStore` SPI 在 v0.6.0 **只定义接口**（`app/extensions/stores.py`），内置 SQLite 实现保持不变；Redis 实现进企业组件池。

## 4. 合规红线

- 企业版下**缓存 key 必须包含租户维度**（见第 2 节前缀），杜绝跨租户缓存穿透；
- 插件不得绕过 `PluginContext` 访问其他租户的会话/日志；
- 安全审核（契约 02 第 5 节）在企业版必须开启，默认放行仅限开源单租户。
