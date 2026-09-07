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
MODEL_PARAM_CONSTRAINTS: Dict[str, Dict[str, Any]] = {
    # kimi-k2.6 是推理模型，只允许 temperature=1
    "kimi-k2.6": {"temperature": 1},
}


def _apply_model_param_constraints(model_name: str, payload: Dict[str, Any]) -> None:
    """根据模型名应用参数约束，原地修改 payload"""
    constraints = MODEL_PARAM_CONSTRAINTS.get(model_name)
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
        api_model = account.endpoint_id if account.endpoint_id else account.model_name
        
        payload = {
            "model": api_model,
            "messages": messages,
            "stream": True,
            **kwargs
        }
        
        # 合并账号默认参数
        if account.extra_json:
            payload.update(_normalize_extra_json(account.extra_json))
        
        # 应用模型参数约束（如 kimi-k2.6 强制 temperature=1）
        _apply_model_param_constraints(account.model_name, payload)
        
        # 确定API地址
        url = self._get_api_url(account)
        
        logger.info(f"请求上游API: {url} model={api_model}")
        logger.debug(f"请求payload: {json.dumps(payload, ensure_ascii=False)[:500]}")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
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
        api_model = account.endpoint_id if account.endpoint_id else account.model_name
        
        payload = {
            "model": api_model,
            "messages": messages,
            "stream": False,
            **kwargs
        }
        
        # 合并账号默认参数
        if account.extra_json:
            payload.update(_normalize_extra_json(account.extra_json))
        
        # 应用模型参数约束（如 kimi-k2.6 强制 temperature=1）
        _apply_model_param_constraints(account.model_name, payload)
        
        # 确定API地址
        url = self._get_api_url(account)
        
        logger.info(f"请求上游API: {url} model={api_model}")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
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
