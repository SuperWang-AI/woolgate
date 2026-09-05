"""
加密工具 - 使用Fernet对称加密保护厂商API Key
"""
from cryptography.fernet import Fernet
from app.config import settings


class EncryptionService:
    """AES加密服务（基于Fernet）"""
    
    def __init__(self):
        if not settings.ENCRYPTION_KEY:
            raise ValueError("加密密钥未配置")
        self.cipher = Fernet(settings.ENCRYPTION_KEY.encode())
    
    def encrypt(self, plaintext: str) -> str:
        """加密字符串"""
        if not plaintext:
            return ""
        encrypted = self.cipher.encrypt(plaintext.encode())
        return encrypted.decode()
    
    def decrypt(self, encrypted: str) -> str:
        """解密字符串"""
        if not encrypted:
            return ""
        decrypted = self.cipher.decrypt(encrypted.encode())
        return decrypted.decode()


# 全局加密服务实例
encryption_service = EncryptionService()


def generate_key() -> str:
    """生成新的加密密钥"""
    return Fernet.generate_key().decode()
