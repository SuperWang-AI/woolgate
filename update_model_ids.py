#!/usr/bin/env python3
"""
临时脚本：批量修改账号的模型ID
"""
import sqlite3
import sys

def main():
    db_path = "data/woolgate.db"
    
    # 连接数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 查看当前账号
    print("当前账号列表：")
    cursor.execute("SELECT id, vendor, model_name, priority FROM model_accounts")
    accounts = cursor.fetchall()
    for acc in accounts:
        print(f"  ID: {acc[0]}, 厂商: {acc[1]}, 模型: {acc[2]}, 优先级: {acc[3]}")
    
    if not accounts:
        print("没有找到账号")
        return
    
    # 询问新的模型ID
    new_model_id = input("\n请输入新的模型ID（所有账号将使用这个ID）: ").strip()
    if not new_model_id:
        print("未输入模型ID，退出")
        return
    
    # 更新所有账号
    cursor.execute("UPDATE model_accounts SET model_name = ?", (new_model_id,))
    conn.commit()
    
    print(f"\n已将所有账号的模型ID更新为: {new_model_id}")
    
    # 显示更新后的结果
    print("\n更新后的账号列表：")
    cursor.execute("SELECT id, vendor, model_name, priority FROM model_accounts")
    accounts = cursor.fetchall()
    for acc in accounts:
        print(f"  ID: {acc[0]}, 厂商: {acc[1]}, 模型: {acc[2]}, 优先级: {acc[3]}")
    
    conn.close()
    print("\n✅ 更新完成！")

if __name__ == "__main__":
    main()
