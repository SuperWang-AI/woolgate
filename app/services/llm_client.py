"""
LiteLLM适配服务
负责调用上游LLM API，支持流式和非流式
"""
from typing import AsyncGenerator, Dict, Any, Optional
import httpx
import json
import logging
from app.models.database import ModelAccount
from app.utils.encryption import encryption_service

logger = logging.getLogger(__name__)


def _normalize_extra_json(extra_json):
    """将 extra_json 统一为 dict（历史数据可能存成 JSON 字符串，防止 payload.update 报错）"""
    if isinstance(extra_json, dict):
        return extra_json
    if isinstance(extra_json, str):
        try:
            parsed = json.loads(extra_json)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


# 模型参数约束——部分模型对参数有硬性限制，自动修正避免 400 错误
# 内置默认值，可被系统配置覆盖
DEFAULT_MODEL_PARAM_CONSTRAINTS: Dict[str, Dict[str, Any]] = {
    # kimi-k2.6 是推理模型，只允许 temperature=1
    "kimi-k2.6": {"temperature": 1},
}

# 运行时缓存的模型参数约束（从系统配置加载）
_runtime_constraints: Dict[str, Dict[str, Any]] = {}
_constraints_loaded: bool = False


def _load_constraints_from_db() -> None:
    """从系统配置加载模型参数约束（首次调用时）"""
    global _constraints_loaded, _runtime_constraints
    if _constraints_loaded:
        return
    try:
        from app.models.database import AsyncSessionLocal, SystemConfig
        from sqlalchemy import select
        import asyncio
        # 在同步上下文里创建事件循环
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        async def _fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(SystemConfig).where(SystemConfig.id == 1))
                config = result.scalar_one_or_none()
                if config and config.model_param_constraints_json:
                    return config.model_param_constraints_json
                return {}
        custom = loop.run_until_complete(_fetch())
        # 合并：默认值 + 自定义覆盖
        merged = dict(DEFAULT_MODEL_PARAM_CONSTRAINTS)
        merged.update(custom or {})
        _runtime_constraints = merged
    except Exception as e:
        logger.warning(f"加载模型参数约束失败，使用默认值: {e}")
        _runtime_constraints = dict(DEFAULT_MODEL_PARAM_CONSTRAINTS)
    _constraints_loaded = True


def get_model_param_constraints() -> Dict[str, Dict[str, Any]]:
    """获取当前生效的模型参数约束"""
    if not _constraints_loaded:
        _load_constraints_from_db()
    return _runtime_constraints


def reload_model_param_constraints() -> None:
    """强制重新加载（系统配置修改后调用）"""
    global _constraints_loaded
    _constraints_loaded = False
    _load_constraints_from_db()


def _apply_model_param_constraints(model_name: str, payload: Dict[str, Any], account_id: int = None) -> None:
    """根据模型名应用参数约束，原地修改 payload。
    优先级：ModelCatalog 账号级约束 > 全局默认约束
    """
    constraints = None
    # 优先查 ModelCatalog 账号级约束
    if account_id and model_name:
        try:
            from app.models.database import AsyncSessionLocal, ModelCatalog
            from sqlalchemy import select
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            async def _fetch_catalog():
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(ModelCatalog).where(
                            ModelCatalog.account_id == account_id,
                            ModelCatalog.model_name == model_name
                        )
                    )
                    catalog = result.scalar_one_or_none()
                    if catalog and catalog.param_constraints_json:
                        return catalog.param_constraints_json
                    return None
            constraints = loop.run_until_complete(_fetch_catalog())
        except Exception as e:
            logger.debug(f"查询 ModelCatalog 参数约束失败，回退全局约束: {e}")
    # 回退全局默认约束
    if not constraints:
        constraints = get_model_param_constraints().get(model_name)
    if not constraints:
        return
    for key, value in constraints.items():
        if key in payload and payload[key] != value:
            logger.info(f"模型参数兼容: {model_name} {key}={payload[key]} → {value}")
            payload[key] = value


class LLMClient:
    """LLM客户端（基于LiteLLM协议）"""
    
    def __init__(self):
        self.timeout = httpx.Timeout(120.0, connect=10.0)
        # 复用连接（FastAPI 单进程单事件循环下安全；减少 TLS 握手与连接建立开销）
        self._client = httpx.AsyncClient(timeout=self.timeout)
    
    async def chat_completion_stream(
        self,
        account: ModelAccount,
        messages: list,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式聊天补全
        
        Yields:
            SSE事件字典
        """
        # 解密API Key
        api_key = encryption_service.decrypt(account.api_key_encrypted)
        
        # 构建请求
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        # 确定调用时使用的模型名：优先使用endpoint_id（如豆包/火山引擎），否则用model_name
        api_model = account.endpoint_id if account.endpoint_id else account.default_model_name
        
        payload = {
            "model": api_model,
            "messages": messages,
            "stream": True,
            **kwargs
        }
        
        # 合并账号默认参数（注意：extra_json 不得包含 model 键，防止覆盖正确模型）
        if account.extra_json:
            payload.update(_normalize_extra_json(account.extra_json))
        # 强制恢复 model（防历史脏数据/手工误填覆盖）
        payload["model"] = api_model
        
        # 应用模型参数约束（如 kimi-k2.6 强制 temperature=1）
        _apply_model_param_constraints(api_model, payload, account.id)
        
        # 确定API地址
        url = self._get_api_url(account)
        
        logger.info(f"请求上游API: {url} model={api_model}")
        logger.debug(f"请求payload: {json.dumps(payload, ensure_ascii=False)[:500]}")
        
        async with self._client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    logger.error(f"上游API错误 {response.status_code}: {body.decode('utf-8', errors='replace')[:500]}")
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    
                    if line.startswith("data: "):
                        data = line[6:]
                        
                        if data == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(data)
                            yield chunk
                        except json.JSONDecodeError:
                            logger.warning(f"无法解析SSE数据: {data}")
                            continue
    
    async def chat_completion(
        self,
        account: ModelAccount,
        messages: list,
        **kwargs
    ) -> Dict[str, Any]:
        """
        非流式聊天补全
        
        Returns:
            完整响应字典
        """
        # 解密API Key
        api_key = encryption_service.decrypt(account.api_key_encrypted)
        
        # 构建请求
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        # 确定调用时使用的模型名：优先使用endpoint_id（如豆包/火山引擎），否则用model_name
        api_model = account.endpoint_id if account.endpoint_id else account.default_model_name
        
        payload = {
            "model": api_model,
            "messages": messages,
            "stream": False,
            **kwargs
        }
        
        # 合并账号默认参数（注意：extra_json 不得包含 model 键，防止覆盖正确模型）
        if account.extra_json:
            payload.update(_normalize_extra_json(account.extra_json))
        # 强制恢复 model（防历史脏数据/手工误填覆盖）
        payload["model"] = api_model
        
        # 应用模型参数约束（如 kimi-k2.6 强制 temperature=1）
        _apply_model_param_constraints(api_model, payload, account.id)
        
        # 确定API地址
        url = self._get_api_url(account)
        
        logger.info(f"请求上游API: {url} model={api_model}")
        
        response = await self._client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            error_body = response.text
            logger.error(f"上游API返回错误 {response.status_code}: {error_body}")
        response.raise_for_status()
        return response.json()
    
    def _get_api_url(self, account: ModelAccount) -> str:
        """获取API地址"""
        if account.base_url:
            # 如果已经包含 chat/completions 路径，直接返回
            base = account.base_url.rstrip("/")
            if "chat/completions" in base:
                return base
            # 标准OpenAI兼容base（以/v1结尾）→ 加 /chat/completions
            if base.endswith("/v1"):
                return f"{base}/chat/completions"
            # 否则添加标准路径
            return f"{base}/v1/chat/completions"
        
        # 默认地址映射（常见厂商）
        default_urls = {
            "deepseek": "https://api.deepseek.com/v1/chat/completions",
            "openai": "https://api.openai.com/v1/chat/completions",
            "moonshot": "https://api.moonshot.cn/v1/chat/completions",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "ollama": "http://host.docker.internal:11434/v1/chat/completions",
        }
        
        vendor_lower = account.vendor.lower()
        for key, url in default_urls.items():
            if key in vendor_lower:
                return url
        
        # 无法确定，抛出异常
        raise ValueError(f"账号 {account.id} 未配置base_url且无法自动推断")


# 全局客户端实例
llm_client = LLMClient()
