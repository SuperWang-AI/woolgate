#!/usr/bin/env python3
"""
WoolGate 会话粘性设计方案

问题：
每次请求都重新选择账号，导致多轮对话中模型切换，出现：
1. 上下文丢失（不同模型没有共享记忆）
2. 身份混乱（Qwen 回答了 A，DeepSeek 回答了 B）
3. 效率低下（不必要的账号选择）

解决方案A：基于消息历史的隐式粘性（推荐）
=========================================

原理：
- 从 messages 中检测之前的 assistant 回复
- 推断之前使用的模型/账号
- 优先复用该账号（如果额度充足）

优点：
- 无需客户端改动
- OpenAI API 标准兼容
- 自动处理会话连续性

实现：
1. 在 AccountRouter 中添加 infer_previous_account() 方法
2. 分析 messages 中的 assistant 回复特征
3. select_account() 时优先返回推断的账号

代码示例：
```python
class AccountRouter:
    async def infer_previous_account(
        self, 
        messages: List[Dict],
        model_name: str
    ) -> Optional[int]:
        \"\"\"
        从消息历史推断之前使用的账号
        
        策略：
        1. 检查最后一条 assistant 消息
        2. 查询最近的请求日志
        3. 匹配相同的对话特征
        \"\"\"
        # 提取最后一条 assistant 消息
        last_assistant = None
        for msg in reversed(messages):
            if msg.get('role') == 'assistant':
                last_assistant = msg.get('content')
                break
        
        if not last_assistant:
            return None  # 新对话
        
        # 查询最近的请求日志（最近10分钟内）
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        
        result = await self.session.execute(
            select(RequestLog)
            .where(RequestLog.created_at > cutoff)
            .where(RequestLog.status == 'success')
            .order_by(RequestLog.created_at.desc())
            .limit(50)
        )
        logs = result.scalars().all()
        
        # 简单策略：返回最近成功的账号
        # TODO: 更精确的匹配（比如对比回复内容特征）
        if logs:
            return logs[0].account_id
        
        return None
    
    async def select_account(
        self,
        model_name: str,
        estimated_tokens: int = 1000,
        strategy: Optional[str] = None,
        messages: Optional[List[Dict]] = None  # 新增参数
    ) -> Optional[ModelAccount]:
        # 1. 尝试推断之前的账号
        if messages:
            prev_account_id = await self.infer_previous_account(messages, model_name)
            if prev_account_id:
                # 检查该账号是否仍然可用
                prev_account = await self._get_account_by_id(prev_account_id)
                if prev_account and self._is_account_available(prev_account, estimated_tokens):
                    logger.info(f\"会话粘性：继续使用账号 {prev_account_id}\")
                    return prev_account
        
        # 2. 正常选择逻辑
        # ... 原有代码 ...
```

解决方案B：基于会话ID的显式粘性（需客户端支持）
===============================================

原理：
- 客户端在请求中传递 session_id
- WoolGate 维护 session_id → account_id 映射
- 同一 session 始终使用同一账号

优点：
- 精确、可靠
- 支持长时间会话

缺点：
- 需要客户端改动（自定义请求头）
- 不符合 OpenAI API 标准

实现：
```python
# 请求头
headers = {
    "X-Session-ID": "user123_conv456"
}

# WoolGate 内存缓存
session_account_map = {}

async def select_account(self, model_name, session_id=None):
    # 1. 检查会话绑定
    if session_id and session_id in session_account_map:
        account_id = session_account_map[session_id]
        account = await self._get_account_by_id(account_id)
        if account and self._is_account_available(account):
            return account
        else:
            # 账号不可用，解绑
            del session_account_map[session_id]
    
    # 2. 选择新账号
    account = await self._select_new_account(model_name)
    
    # 3. 建立绑定
    if session_id and account:
        session_account_map[session_id] = account.id
    
    return account
```

推荐方案：A（基于消息历史）
=========================

理由：
1. 无需客户端改动
2. 符合 OpenAI API 标准
3. 自动处理大部分场景
4. 实现简单

下一步：
1. 实现 infer_previous_account() 方法
2. 修改 select_account() 支持 messages 参数
3. 修改 api.py 传递 messages 给路由器
4. 测试多轮对话场景
"""

print(__doc__)
