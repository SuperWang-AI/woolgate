"""
Token 估算工具（统一口径）

中文约 1.5 字符/token，英文约 4 字符/token。
替代 api.py 与 executor.py 中重复的两套实现。
"""


def estimate_tokens(text: str) -> int:
    """估算单段文本 token 数"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def estimate_messages_tokens(messages) -> int:
    """估算消息列表总 token 数（OpenAI 格式 message dict 列表）"""
    total = 0
    for msg in messages or []:
        if isinstance(msg, dict):
            total += estimate_tokens(msg.get("content", ""))
        else:
            total += estimate_tokens(str(msg))
    return total
