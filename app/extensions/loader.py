"""
插件加载器（A3）——v0.6.0

启动时扫描 WOOLGATE_PLUGINS 环境变量（逗号分隔模块路径）逐个 import。
插件 import 失败：记日志、跳过，不影响应用启动（契约 03 第 5 节）。
"""
import importlib
import logging
import os
from typing import List

logger = logging.getLogger(__name__)

ENV_PLUGINS = "WOOLGATE_PLUGINS"


def load_plugins() -> List[str]:
    """
    加载所有配置的插件模块。

    Returns:
        成功加载的插件模块名列表
    """
    raw = os.environ.get(ENV_PLUGINS, "").strip()
    if not raw:
        return []

    loaded: List[str] = []
    for module_name in [m.strip() for m in raw.split(",") if m.strip()]:
        try:
            importlib.import_module(module_name)
            loaded.append(module_name)
            logger.info(f"[extensions] 插件加载成功: {module_name}")
        except Exception as e:
            logger.error(f"[extensions] 插件加载失败（已跳过，不影响启动）: {module_name}: {e}",
                         exc_info=True)
    return loaded
