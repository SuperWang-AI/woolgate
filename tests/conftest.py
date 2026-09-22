"""
pytest配置文件

使用 pytest-asyncio 的 asyncio_mode=auto（见 pytest.ini），
async 测试与 async fixture 由插件统一管理，无需自定义 event_loop。
"""

import os

from cryptography.fernet import Fernet

# 测试专用环境变量：config.py 强制校验无默认凭据（安全设计），
# CI / 纯净环境无 .env 时注入测试值，保证测试可独立运行。
# 注意：加密密钥动态生成（非静态文本），避免密钥文本出现在代码库中。
os.environ.setdefault("GATEWAY_BEARER_TOKEN", "test-token")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())


async def seed_account(db, vendor, model_name, **extra):
    """主从语义测试预置：账号行 + 对应 ModelCatalog 行（挂 account_id）

    主从改造后，模型→账号映射走 ModelCatalog，纯账号行无法被路由选中，
    因此预置必须配套：账号行（key 载体）+ 目录行（模型能力载体）。
    """
    from app.models.database import ModelAccount, ModelCatalog

    extra.setdefault("balance_unit", "token")
    extra.setdefault("balance_remaining", 1000000)
    acc = ModelAccount(
        vendor=vendor,
        default_model_name=model_name,
        api_key_encrypted=f"key-{vendor}-{model_name}",
        virtual_model="chat",
        **extra,
    )
    db.add(acc)
    await db.flush()
    db.add(ModelCatalog(
        account_id=acc.id,
        vendor=vendor,
        model_name=model_name,
        is_active=True,
    ))
    return acc
