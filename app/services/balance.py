"""
厂商余额自动获取服务

支持自动获取余额的厂商：
  - Kimi / Moonshot / 月之暗面：GET /v1/users/me/balance
  - DeepSeek：GET /user/balance
  - SiliconFlow / 硅基流动：GET /v1/user/info

不支持（会抛 BalanceUnsupportedError）：
  - 阿里百炼：无官方余额查询接口（需阿里云 AccessKey 走 BSS，暂不支持）
  - Ollama：本地模型，无余额概念
  - 其他未识别厂商
"""
import httpx
import logging

logger = logging.getLogger(__name__)


class BalanceUnsupportedError(Exception):
    """该厂商不支持自动获取余额"""


def _extract_host(base_url: str) -> str:
    """从 base_url 提取 协议+主机（去掉路径），用于推导余额/模型接口"""
    if not base_url:
        return ''
    idx = base_url.find('/v1/')
    if idx > 0:
        return base_url[:idx]
    idx = base_url.find('/chat')
    if idx > 0:
        return base_url[:idx]
    return base_url.rstrip('/')


def _decrypt_key(account) -> str:
    """解密 API Key"""
    from app.utils.encryption import encryption_service
    try:
        key = encryption_service.decrypt(account.api_key_encrypted)
    except Exception:
        raise ValueError('API Key 解密失败，无法获取余额')
    if not key:
        raise ValueError('未配置 API Key，无法获取余额')
    return key


async def fetch_balance(account):
    """
    根据账号自动获取厂商真实余额

    Returns:
        (balance_unit, remaining_balance)：('currency', 金额) 或 ('token', 数量)

    Raises:
        BalanceUnsupportedError: 厂商不支持自动获取
        ValueError: 解析失败 / Key 缺失
        httpx.HTTPError: 网络或接口错误
    """
    vendor_lower = account.vendor.lower()
    api_key = _decrypt_key(account)
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}

    # Kimi / Moonshot / 月之暗面
    if any(k in vendor_lower for k in ('kimi', 'moonshot', '月之暗面')):
        host = _extract_host(account.base_url) or 'https://api.moonshot.cn'
        url = f'{host}/v1/users/me/balance'
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
        bal_data = data.get('data', data)
        bal = None
        if isinstance(bal_data, dict):
            bal = bal_data.get('available_balance') or bal_data.get('balance')
        if bal is None:
            bal = data.get('available_balance') or data.get('balance')
        if bal is None:
            raise ValueError(f'无法解析余额: {str(data)[:200]}')
        return 'currency', float(bal)

    # DeepSeek / 深度求索
    if any(k in vendor_lower for k in ('deepseek', '深度求索')):
        url = 'https://api.deepseek.com/user/balance'
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
        infos = data.get('balance_infos') or []
        if infos:
            total = infos[0].get('total_balance') or infos[0].get('total')
            if total is not None:
                return 'currency', float(total)
        raise ValueError(f'无法解析余额: {str(data)[:200]}')

    # SiliconFlow / 硅基流动
    if any(k in vendor_lower for k in ('siliconflow', '硅基流动')):
        url = 'https://api.siliconflow.cn/v1/user/info'
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
        bal_data = data.get('data', data)
        bal = None
        if isinstance(bal_data, dict):
            bal = bal_data.get('balance') or bal_data.get('totalBalance')
        if bal is None:
            bal = data.get('balance') or data.get('totalBalance')
        if bal is None:
            raise ValueError(f'无法解析余额: {str(data)[:200]}')
        return 'currency', float(bal)

    # 阿里百炼
    if any(k in vendor_lower for k in ('阿里', '百炼', 'qwen', '通义', 'dashscope')):
        raise BalanceUnsupportedError('阿里百炼无官方余额查询接口，请登录阿里云控制台查看，或手动维护额度')

    # Ollama 本地
    if 'ollama' in vendor_lower:
        raise BalanceUnsupportedError('Ollama 为本地模型，无余额概念')

    raise BalanceUnsupportedError(f'暂不支持厂商 "{account.vendor}" 的余额自动获取')


async def fetch_models(account):
    """
    获取厂商可用模型列表（OpenAI 兼容 /v1/models）

    Returns:
        list[str]：模型 ID 列表；失败时返回 []
    """
    vendor_lower = account.vendor.lower()
    try:
        api_key = _decrypt_key(account)
    except ValueError:
        # 本地模型（Ollama）无 API Key，允许继续探测；其他厂商无 Key 视为不可探测
        if any(k in account.vendor.lower() for k in ('ollama', '本地')):
            api_key = ''
        else:
            return []
    headers = {'Authorization': f'Bearer {api_key}'}

    if any(k in vendor_lower for k in ('kimi', 'moonshot', '月之暗面')):
        host = _extract_host(account.base_url) or 'https://api.moonshot.cn'
        url = f'{host}/v1/models'
    elif any(k in vendor_lower for k in ('deepseek', '深度求索')):
        url = 'https://api.deepseek.com/models'
    elif any(k in vendor_lower for k in ('siliconflow', '硅基流动')):
        url = 'https://api.siliconflow.cn/v1/models'
    elif any(k in vendor_lower for k in ('阿里', '百炼', 'qwen', '通义', 'dashscope')):
        url = 'https://dashscope.aliyuncs.com/compatible-mode/v1/models'
    elif any(k in vendor_lower for k in ('ollama', '本地')):
        # Ollama OpenAI 兼容接口：base_url 已含 /v1（如 http://host:11434/v1），免鉴权
        url = account.base_url.rstrip('/') + '/models'
        headers = {}
    else:
        return []

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return []
            data = r.json()
            return [m.get('id') for m in (data.get('data') or []) if m.get('id')]
    except Exception as e:
        logger.warning(f'获取模型列表失败: {e}')
        return []


def get_today_str() -> str:
    """获取本地日期字符串 YYYY-MM-DD（Asia/Shanghai）"""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
    except Exception:
        from datetime import timedelta, timezone
        return (datetime.now(timezone(timedelta(hours=8)))).strftime('%Y-%m-%d')
