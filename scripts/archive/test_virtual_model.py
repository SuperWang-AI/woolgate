#!/usr/bin/env python3
"""
测试 WoolGate 虚拟模型名映射功能
"""
import requests
import json
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

WOOLGATE_URL = "http://localhost:8765"
BEARER_TOKEN = os.getenv("GATEWAY_BEARER_TOKEN", "your-token-here")

print("=" * 60)
print("WoolGate 虚拟模型名映射测试")
print("=" * 60)

# 测试1: 请求虚拟模型 "chat"
print("\n【测试1】请求虚拟模型: chat")
print("-" * 60)

headers = {
    "Authorization": f"Bearer {BEARER_TOKEN}",
    "Content-Type": "application/json"
}

payload = {
    "model": "chat",  # 虚拟模型名
    "messages": [
        {"role": "user", "content": "请用一句话介绍你自己"}
    ],
    "stream": False
}

try:
    response = requests.post(
        f"{WOOLGATE_URL}/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✓ 请求成功")
        print(f"  选中模型: {result.get('model', 'unknown')}")
        print(f"  响应内容: {result['choices'][0]['message']['content'][:100]}...")
        print(f"  Token消耗: {result['usage']}")
    else:
        print(f"✗ 请求失败: {response.status_code}")
        print(f"  错误信息: {response.text}")
        
except Exception as e:
    print(f"✗ 请求异常: {e}")

# 测试2: 列出可用模型
print("\n【测试2】列出可用模型")
print("-" * 60)

try:
    response = requests.get(
        f"{WOOLGATE_URL}/v1/models",
        headers=headers,
        timeout=10
    )
    
    if response.status_code == 200:
        models = response.json()
        print(f"✓ 获取成功，共 {len(models.get('data', []))} 个模型:")
        for model in models.get('data', []):
            print(f"  - {model['id']}")
    else:
        print(f"✗ 请求失败: {response.status_code}")
        
except Exception as e:
    print(f"✗ 请求异常: {e}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
print("\n【工作原理验证】")
print("  如果上面显示的模型是真实模型名（如 deepseek-chat）")
print("  说明虚拟模型映射工作正常！")
print("\n【预期结果】")
print("  客户端请求: model='chat'")
print("  WoolGate 内部: 匹配 virtual_model='chat' 的账号")
print("  向上游发送: model='deepseek-chat' 或其他真实模型名")
