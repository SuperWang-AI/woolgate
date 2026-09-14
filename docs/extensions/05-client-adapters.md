# 扩展契约 05：客户端适配器 SPI

> 版本：v0.6.0 · 状态：已定稿 · 代码位置：`app/extensions/adapters.py`

## 1. 问题

v0.5.0 只兼容 OpenAI `/v1/chat/completions` 协议（Dify / Cherry Studio / OpenClaw 等均走此协议）。未来可能接入非 OpenAI 兼容客户端（自研协议、gRPC、MCP 等），必须在入口层预留扩展点。

## 2. SPI 定义

```python
class ClientAdapter(ABC):
    """客户端协议适配器：把任意客户端请求翻译为管线输入，把管线输出翻译回客户端协议"""

    name: str                       # "openai-compat" / "mcp" / ...

    def matches(self, request: Request) -> bool:
        """判断是否处理该请求（按路径/头部/内容类型识别）"""

    async def parse(self, request: Request) -> PipelineContext:
        """把客户端请求解析为管线上下文（已含 session_id / 密钥 / 覆盖字段）"""

    async def build_response(self, result, ctx: PipelineContext):
        """把管线结果编码回客户端协议响应"""
```

## 3. 内置实现

`OpenAICompatAdapter`：现有 `/v1/chat/completions` + `/v1/models` + `/v1/feedback` 逻辑即为该适配器的默认实现，**行为不变**。

## 4. 分发入口

`app/routes/api.py` 提供 `get_adapter(request) -> ClientAdapter`：

- 按 `matches()` 顺序匹配已注册适配器；
- 默认返回 `OpenAICompatAdapter`（兜底，永不失败）；
- 新协议客户端 = 注册一个新 Adapter，不动核心管线。

## 5. 落地边界（v0.6.0）

- 本版本只**预留接口 + 默认实现**，不新增任何协议；
- `OpenAICompatAdapter` 直接复用现有 `chat_completions` 处理函数（保持行为零变化）；
- 非 OpenAI 客户端接入作为后续版本迭代项（企业定制/社区贡献）。
