"""
管线策略页面
"""
from __future__ import annotations
from nicegui import ui
from .base import BasePage
from app.admin.services import get_system_config, save_system_config


class PipelinePage(BasePage):
    """管线策略配置"""

    async def load(self):
        """加载管线配置"""
        self.config = await get_system_config()

    async def render(self):
        """渲染管线策略页面"""
        with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
            ui.label('管线策略配置').classes('text-3xl font-bold text-gray-800')
            ui.label('三层策略串行：模型路由 → 账号调度 → 上下文管理，保存后立即生效').classes('text-sm text-gray-500 -mt-2')

            config = self.config

            # ── ① 模型路由 ──
            with ui.card().classes('w-full shadow-lg p-4'):
                ui.label('① 模型路由策略').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('根据用户请求语义，智能选择最适合的模型').classes('text-xs text-gray-500 mb-3')

                router_strategy = ui.select(
                    {
                        'off': '关闭（不路由，直接用默认模型）',
                        'vector': '向量相似度匹配',
                        'llm': '大模型分类判断',
                        'hybrid': '混合（向量高置信直接用，低置信升级大模型）',
                    },
                    label='路由策略',
                    value=getattr(config, 'router_strategy', 'hybrid'),
                ).classes('w-full max-w-md mb-3')
                ui.label('默认开启智能路由：免费额度优先，自动选择性价比最高的模型').classes('text-xs text-blue-600 -mt-2 mb-2')

                # 加载当前 router_config
                from app.pipeline.config import PipelineConfig
                from app.models import AsyncSessionLocal
                _pipeline_cfg = await PipelineConfig.load(AsyncSessionLocal())
                _router_cfg = _pipeline_cfg.router_config

                ui.label('Embedding 配置（向量 / 混合策略使用）').classes('text-sm font-bold text-gray-600 mt-2 mb-1')

                # 查询ModelCatalog中所有embedding类型的模型
                from app.models.database import ModelCatalog, ModelAccount
                from sqlalchemy import select
                async with AsyncSessionLocal() as _s:
                    _cat_result = await _s.execute(
                        select(ModelCatalog).where(ModelCatalog.model_type == 'embedding')
                    )
                    _embed_models = _cat_result.scalars().all()
                    # 查询所有账号用于显示
                    _acc_result = await _s.execute(select(ModelAccount))
                    _accounts = {a.id: a for a in _acc_result.scalars().all()}

                _embed_options = {0: '自动（选用第一个 Embedding 模型）'}
                for _m in _embed_models:
                    _acc = _accounts.get(_m.account_id)
                    _acc_name = _acc.vendor if _acc else '未知'
                    _embed_options[_m.id] = f"{_m.display_name or _m.model_name}（{_acc_name}）"

                embedding_model_id = ui.select(
                    options=_embed_options,
                    label='Embedding 模型',
                    value=getattr(_router_cfg, 'embedding_model_id', 0) or 0,
                ).classes('w-full max-w-md')
                if not _embed_models:
                    ui.label('暂无 Embedding 模型，请先在账号管理中启用').classes('text-xs text-red-500 -mt-1 mb-3')
                else:
                    ui.label('选择后自动使用该模型所属账号的 API Key，无需单独配置').classes('text-xs text-gray-400 -mt-1 mb-3')

                # edition 分组：opensource 折叠高级参数，enterprise 展开
                _is_enterprise = getattr(config, 'edition', 'opensource') == 'enterprise'

                with ui.expansion('高级参数（阈值微调 · 上下文细节 · 本地运行时）', icon='tune',
                                  value=_is_enterprise).classes('w-full'):
                    ui.label('开源版默认使用智能推荐参数，以下为极客微调项').classes('text-xs text-gray-400 -mt-1 mb-2')

                    ui.label('滞回阈值（防止频繁切换模型）').classes('text-sm font-bold text-gray-600 mt-1 mb-1')
                    with ui.grid(columns=2).classes('w-full gap-x-8 gap-y-4 max-w-2xl'):
                        with ui.column().classes('gap-1'):
                            threshold_high = ui.number(
                                '切入阈值', value=_router_cfg.threshold_high,
                                min=0.0, max=1.0, step=0.05,
                            ).classes('w-full')
                            ui.label('匹配度高于此值才切换模型').classes('text-xs text-gray-400')
                        with ui.column().classes('gap-1'):
                            threshold_low = ui.number(
                                '保持阈值', value=_router_cfg.threshold_low,
                                min=0.0, max=1.0, step=0.05,
                            ).classes('w-full')
                            ui.label('匹配度低于此值才允许切走，中间区间保持当前模型').classes('text-xs text-gray-400')

            # ── ② 账号调度 ──
            with ui.card().classes('w-full shadow-lg p-4'):
                ui.label('② 账号调度策略').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('从可用账号池中选择具体账号，管理免费额度消耗顺序').classes('text-xs text-gray-500 mb-3')

                selector_strategy = ui.select(
                    {
                        'pin': '指定模型（默认）',
                        'free-first': '免费额度优先',
                        'round-robin': '轮询',
                        'sticky': '会话粘性',
                        'failover': '主备切换',
                        'cost-first': '成本最低',
                    },
                    label='调度策略',
                    value=getattr(config, 'selector_strategy', 'pin'),
                ).classes('w-full max-w-md')
                ui.label('同一模型存在多个账号时，按此策略决定使用顺序').classes('text-xs text-gray-400 -mt-1')

            # ── ③ 上下文管理 ──
            with ui.card().classes('w-full shadow-lg p-4'):
                ui.label('③ 上下文管理策略').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('控制发送给上游的消息组装方式，平衡上下文完整性与 token 消耗').classes('text-xs text-gray-500 mb-3')

                context_strategy = ui.select(
                    {
                        'passthrough': '直传（默认，完整上下文）',
                        'window': '滑动窗口（只保留最近 N 轮）',
                        'summary': '摘要压缩（长对话自动摘要）',
                    },
                    label='上下文策略',
                    value=getattr(config, 'context_strategy', 'passthrough'),
                ).classes('w-full max-w-md mb-3')

                _context_cfg = _pipeline_cfg.context_config

                with ui.expansion('上下文细节（窗口轮数 · 摘要参数）', icon='tune',
                                  value=_is_enterprise).classes('w-full'):
                    with ui.grid(columns=2).classes('w-full gap-x-8 gap-y-4 max-w-2xl'):
                        with ui.column().classes('gap-1'):
                            window_turns = ui.number(
                                '保留最近 N 轮对话', value=_context_cfg.window_turns, min=1, max=100
                            ).classes('w-full')
                            ui.label('滑动窗口策略下保留的对话轮数').classes('text-xs text-gray-400')
                        with ui.column().classes('gap-1'):
                            summary_provider = ui.select(
                                {'cloud': '云端模型', 'local': '本地模型（Ollama）'},
                                label='摘要模型来源',
                                value=_context_cfg.summary_provider,
                            ).classes('w-full')
                            ui.label('摘要压缩策略使用哪种模型生成摘要').classes('text-xs text-gray-400')

                    with ui.grid(columns=2).classes('w-full gap-x-8 gap-y-4 max-w-2xl'):
                        with ui.column().classes('gap-1'):
                            summary_model = ui.input(
                                '摘要模型名', value=_context_cfg.summary_model
                            ).classes('w-full')
                            ui.label('云端：从账号池选该模型的启用账号；本地：直接调用').classes('text-xs text-gray-400')
                        with ui.column().classes('gap-1'):
                            summary_window_turns = ui.number(
                                '摘要后保留原文轮数', value=_context_cfg.summary_window_turns, min=0, max=20
                            ).classes('w-full')
                            ui.label('触发摘要后，最近 N 轮原文仍完整保留').classes('text-xs text-gray-400')

                    with ui.grid(columns=2).classes('w-full gap-x-8 gap-y-4 max-w-2xl'):
                        with ui.column().classes('gap-1'):
                            summary_trigger_turns = ui.number(
                                '触发阈值（对话轮数）', value=_context_cfg.summary_trigger_turns, min=1
                            ).classes('w-full')
                            ui.label('对话轮数超过该值且满足 token 阈值时触发').classes('text-xs text-gray-400')
                        with ui.column().classes('gap-1'):
                            summary_trigger_tokens = ui.number(
                                '触发阈值（token 数）', value=_context_cfg.summary_trigger_tokens, min=100
                            ).classes('w-full')
                            ui.label('累计 token 超过该值且满足轮数阈值时触发').classes('text-xs text-gray-400')

                    ui.label('跨模型切换时强制触发摘要，保证上下文不丢失').classes('text-xs text-blue-600 mt-1')

            # ── ④ 本地模型运行时 ──
            with ui.expansion('本地模型运行时（Ollama，高级）', icon='computer', value=_is_enterprise).classes('w-full'):
                ui.label('用于本地 Embedding、摘要等轻量任务，不参与主模型调度').classes('text-xs text-gray-500 mb-2')
                with ui.grid(columns=2).classes('w-full gap-x-8 gap-y-4 max-w-2xl'):
                    with ui.column().classes('gap-1'):
                        ollama_enabled = ui.checkbox('启用 Ollama', value=config.ollama_enabled)
                        ui.label('关闭后所有本地模型账号跳过调度').classes('text-xs text-gray-400')
                    with ui.column().classes('gap-1'):
                        ollama_url = ui.input('Ollama 地址', value=config.ollama_base_url).classes('w-full')
                        ui.label('默认 http://localhost:11434').classes('text-xs text-gray-400')
                    with ui.column().classes('gap-1'):
                        local_embed_model = ui.input('本地 Embedding 模型', value=config.embedding_local_plugin).classes('w-full')
                        ui.label('需先在 Ollama 中拉取，如 bge-small-zh / nomic-embed-text').classes('text-xs text-gray-400')

            # 保存按钮
            async def save_pipeline():
                # 组装 router_config_json
                router_config_json = {
                    'embedding_backend': 'cloud',
                    'embedding_model_id': int(embedding_model_id.value),
                    'threshold_high': float(threshold_high.value),
                    'threshold_low': float(threshold_low.value),
                }
                # 组装 context_config_json
                context_config_json = {
                    'window_turns': int(window_turns.value),
                    'summary_provider': summary_provider.value,
                    'summary_model': summary_model.value,
                    'summary_trigger_turns': int(summary_trigger_turns.value),
                    'summary_trigger_tokens': int(summary_trigger_tokens.value),
                    'summary_window_turns': int(summary_window_turns.value),
                }
                config_data = {
                    'router_strategy': router_strategy.value,
                    'selector_strategy': selector_strategy.value,
                    'context_strategy': context_strategy.value,
                    'ollama_enabled': ollama_enabled.value,
                    'ollama_base_url': ollama_url.value,
                    'embedding_local_plugin': local_embed_model.value,
                    'router_config_json': router_config_json,
                    'context_config_json': context_config_json,
                }
                success = await save_system_config(config_data)
                if success:
                    # 使 PipelineConfig 缓存失效，下次请求加载新配置
                    from app.pipeline.config import PipelineConfig
                    PipelineConfig.invalidate_cache()
                    ui.notify('管线策略已保存，立即生效', type='positive')
                else:
                    ui.notify('保存失败', type='negative')

            with ui.row().classes('w-full justify-end'):
                ui.button('保存策略', on_click=save_pipeline).props('color=primary size=lg')
