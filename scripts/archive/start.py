#!/usr/bin/env python3
"""
WoolGate 启动脚本
"""
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import settings
from app.utils.encryption import generate_key


def check_env():
    """检查环境配置"""
    if not os.path.exists(".env"):
        print("❌ .env文件不存在")
        print("请复制 .env.example 为 .env 并填写配置")
        return False
    
    if not settings.GATEWAY_BEARER_TOKEN:
        print("❌ GATEWAY_BEARER_TOKEN 未配置")
        return False
    
    if not settings.ENCRYPTION_KEY:
        print("❌ ENCRYPTION_KEY 未配置")
        print("\n生成新密钥:")
        print(f"  {generate_key()}")
        print("\n请将密钥添加到 .env 文件中")
        return False
    
    return True


def main():
    """主函数"""
    print("=" * 60)
    print("🐑 WoolGate - LLM多账号免费额度智能调度网关")
    print("=" * 60)
    
    # 检查配置
    if not check_env():
        sys.exit(1)
    
    print("\n✅ 配置检查通过")
    print(f"📍 监听地址: {settings.HOST}:{settings.PORT}")
    print(f"📁 数据路径: {settings.DATA_PATH}")
    print(f"📊 日志级别: {settings.LOG_LEVEL}")
    print("\n正在启动服务...\n")
    
    # 启动服务
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower()
    )


if __name__ == "__main__":
    main()
