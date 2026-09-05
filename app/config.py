"""
WoolGate 配置管理
分为启动配置(.env)和运行时业务配置(数据库)
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    """启动配置 - 修改后需重启服务"""
    
    # 服务配置
    HOST: str = Field(default="0.0.0.0", description="监听地址")
    PORT: int = Field(default=8765, description="服务端口")
    
    # 数据路径
    DATA_PATH: str = Field(default="./data", description="数据库存放路径")
    
    # 日志配置
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")
    
    # 鉴权
    GATEWAY_BEARER_TOKEN: str = Field(default="", description="全局API鉴权密钥")
    
    # 加密密钥
    ENCRYPTION_KEY: str = Field(default="", description="AES加密密钥(Fernet格式)")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
    
    @property
    def database_url(self) -> str:
        """SQLite数据库连接URL"""
        db_path = Path(self.DATA_PATH) / "woolgate.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{db_path}"
    
    def validate_required(self):
        """验证必需配置"""
        if not self.GATEWAY_BEARER_TOKEN:
            raise ValueError("GATEWAY_BEARER_TOKEN 未配置，请在.env中设置")
        if not self.ENCRYPTION_KEY:
            raise ValueError("ENCRYPTION_KEY 未配置，请运行生成命令创建密钥")


# 全局配置实例
settings = Settings()
