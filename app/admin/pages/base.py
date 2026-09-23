"""
页面基类
所有管理后台页面都继承这个基类
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session
from nicegui import ui


class BasePage:
    """管理后台页面基类"""
    
    def __init__(self, db: Session, config: dict):
        self.db = db
        self.config = config
    
    async def load(self):
        """加载数据，子类重写"""
        pass
    
    def render(self):
        """渲染页面，子类必须重写"""
        raise NotImplementedError("子类必须实现 render() 方法")
