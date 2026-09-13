#!/usr/bin/env python3
"""
修复 WoolGate 账号的模型名称配置
"""
import sqlite3
from datetime import datetime

# 连接数据库
conn = sqlite3.connect('data/woolgate.db')
cursor = conn.cursor()

# 正确的模型名称映射
MODEL_FIXES = {
    2: {  # 硅基流动
        'model_name': 'Qwen/Qwen2.5-7B-Instruct',
        'vendor': '硅基流动 (SiliconFlow)'
    },
    3: {  # DeepSeek
        'model_name': 'deepseek-chat',
        'vendor': 'DeepSeek'
    },
    4: {  # 月之暗面
        'model_name': 'moonshot-v1-8k',
        'vendor': '月之暗面 (Moonshot)'
    },
    5: {  # 阿里百炼
        'model_name': 'qwen-plus',
        'vendor': '阿里百炼 (Qwen)'
    }
}

print("=" * 60)
print("WoolGate 模型名称修复脚本")
print("=" * 60)

# 显示当前配置
print("\n【修复前】当前配置：")
accounts = cursor.execute('''
    SELECT id, vendor, model_name 
    FROM model_account 
    ORDER BY id
''').fetchall()

for acc in accounts:
    print(f"  账号 {acc[0]}: {acc[1]} -> {acc[2]}")

# 执行修复
print("\n【执行修复】")
for account_id, fix in MODEL_FIXES.items():
    cursor.execute('''
        UPDATE model_account 
        SET model_name = ?, 
            vendor = ?,
            updated_at = ?
        WHERE id = ?
    ''', (fix['model_name'], fix['vendor'], datetime.now(), account_id))
    print(f"  ✓ 账号 {account_id}: {fix['vendor']} -> {fix['model_name']}")

conn.commit()

# 验证修复结果
print("\n【修复后】新配置：")
accounts = cursor.execute('''
    SELECT id, vendor, model_name 
    FROM model_account 
    ORDER BY id
''').fetchall()

for acc in accounts:
    print(f"  账号 {acc[0]}: {acc[1]} -> {acc[2]}")

conn.close()

print("\n" + "=" * 60)
print("✅ 修复完成！")
print("=" * 60)
print("\n⚠️  注意：")
print("  1. 需要重启 WoolGate 容器使配置生效")
print("  2. 建议在管理界面测试每个账号是否正常")
print("  3. 如需其他模型，请在管理界面手动调整")
print("\n重启命令：")
print("  docker restart woolgate")
