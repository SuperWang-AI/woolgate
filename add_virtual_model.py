#!/usr/bin/env python3
"""
添加 virtual_model 字段并迁移数据
实现虚拟模型名到真实模型名的映射
"""
import sqlite3
from datetime import datetime

conn = sqlite3.connect('data/woolgate.db')
cursor = conn.cursor()

print("=" * 60)
print("WoolGate 虚拟模型名功能添加")
print("=" * 60)

# 1. 添加 virtual_model 字段
print("\n【步骤1】添加 virtual_model 字段...")
try:
    cursor.execute('''
        ALTER TABLE model_account 
        ADD COLUMN virtual_model VARCHAR(100) DEFAULT 'chat'
    ''')
    print("  ✓ 字段添加成功")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("  ⚠️  字段已存在，跳过")
    else:
        raise

# 2. 迁移现有数据
print("\n【步骤2】迁移现有数据...")
print("  策略：保持 virtual_model='chat'，恢复真实 model_name")

# 获取当前账号信息
accounts = cursor.execute('''
    SELECT id, vendor, model_name 
    FROM model_account 
    ORDER BY id
''').fetchall()

print("\n  当前配置：")
for acc in accounts:
    print(f"    账号 {acc[0]}: {acc[1]} -> {acc[2]}")

# 设置虚拟模型为 'chat'，恢复真实模型名
updates = {
    2: 'Qwen/Qwen2.5-7B-Instruct',
    3: 'deepseek-chat',
    4: 'moonshot-v1-8k',
    5: 'qwen-plus'
}

print("\n  执行迁移：")
for account_id, real_model in updates.items():
    cursor.execute('''
        UPDATE model_account 
        SET virtual_model = 'chat',
            model_name = ?,
            updated_at = ?
        WHERE id = ?
    ''', (real_model, datetime.now(), account_id))
    print(f"    ✓ 账号 {account_id}: virtual_model='chat' -> model_name='{real_model}'")

conn.commit()

# 3. 验证结果
print("\n【步骤3】验证迁移结果...")
accounts = cursor.execute('''
    SELECT id, vendor, virtual_model, model_name 
    FROM model_account 
    ORDER BY id
''').fetchall()

print("\n  新配置：")
for acc in accounts:
    print(f"    账号 {acc[0]}: {acc[1]}")
    print(f"      virtual_model: {acc[2]} (客户端请求)")
    print(f"      model_name: {acc[3]} (上游API)")

conn.close()

print("\n" + "=" * 60)
print("✅ 迁移完成！")
print("=" * 60)
print("\n【工作原理】")
print("  客户端请求: model='chat'")
print("  → WoolGate 匹配 virtual_model='chat' 的所有账号")
print("  → 选择最优账号（如账号3: DeepSeek）")
print("  → 向上游发送真实模型名: model='deepseek-chat'")
print("\n【下一步】")
print("  1. 修改 router.py 使用 virtual_model 匹配")
print("  2. 修改 llm_client.py 使用 model_name 发送请求")
print("  3. 重启 WoolGate 测试")
