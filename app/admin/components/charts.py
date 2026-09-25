"""
图表组件
使用 NiceGUI 内置的 ui.echart 组件渲染各种统计图表
"""
from __future__ import annotations
from typing import List, Dict, Optional
from nicegui import ui


def render_request_trend_chart(data: Dict) -> None:
    """渲染请求量趋势图（折线图）"""
    dates = data.get('dates', [])
    counts = data.get('counts', [])
    
    if not dates or not counts:
        ui.label('暂无数据').classes('text-gray-500 text-center py-8')
        return
    
    # 构建 ECharts option
    option = {
        'tooltip': {
            'trigger': 'axis',
            'backgroundColor': 'rgba(255, 255, 255, 0.95)',
            'borderColor': '#E4E3DD',
            'textStyle': {'color': '#333', 'fontSize': 12},
        },
        'grid': {
            'left': 40,
            'right': 20,
            'top': 30,
            'bottom': 30,
            'containLabel': True,
        },
        'xAxis': {
            'type': 'category',
            'data': dates,
            'axisLabel': {'color': '#555', 'fontSize': 11},
            'axisLine': {'lineStyle': {'color': '#ddd'}},
        },
        'yAxis': {
            'type': 'value',
            'axisLabel': {'color': '#555', 'fontSize': 11},
            'splitLine': {'lineStyle': {'color': '#f0f0f0'}},
        },
        'series': [{
            'name': '请求量',
            'type': 'line',
            'data': counts,
            'smooth': True,
            'itemStyle': {'color': '#3B82F6'},
            'lineStyle': {'color': '#3B82F6', 'width': 2},
            'areaStyle': {
                'color': {
                    'type': 'linear',
                    'x': 0,
                    'y': 0,
                    'x2': 0,
                    'y2': 1,
                    'colorStops': [
                        {'offset': 0, 'color': 'rgba(59, 130, 246, 0.3)'},
                        {'offset': 1, 'color': 'rgba(59, 130, 246, 0.1)'},
                    ],
                }
            },
        }],
    }
    
    ui.echart(options=option).classes('w-full h-72')


def render_token_trend_chart(data: Dict) -> None:
    """渲染 Token 使用量趋势图（堆叠柱状图）"""
    dates = data.get('dates', [])
    prompt_tokens = data.get('prompt_tokens', [])
    completion_tokens = data.get('completion_tokens', [])
    
    if not dates or not prompt_tokens:
        ui.label('暂无数据').classes('text-gray-500 text-center py-8')
        return
    
    # 转换为 M 单位
    prompt_m = [round(v / 1_000_000, 4) for v in prompt_tokens]
    completion_m = [round(v / 1_000_000, 4) for v in completion_tokens]
    
    option = {
        'tooltip': {
            'trigger': 'axis',
            'backgroundColor': 'rgba(255, 255, 255, 0.95)',
            'borderColor': '#E4E3DD',
            'textStyle': {'color': '#333', 'fontSize': 12},
        },
        'legend': {
            'data': ['输入 Token', '输出 Token'],
            'bottom': 0,
            'textStyle': {'color': '#555', 'fontSize': 11},
        },
        'grid': {
            'left': 40,
            'right': 20,
            'top': 30,
            'bottom': 50,
            'containLabel': True,
        },
        'xAxis': {
            'type': 'category',
            'data': dates,
            'axisLabel': {'color': '#555', 'fontSize': 11},
            'axisLine': {'lineStyle': {'color': '#ddd'}},
        },
        'yAxis': {
            'type': 'value',
            'axisLabel': {
                'color': '#555',
                'fontSize': 11,
            },
            'splitLine': {'lineStyle': {'color': '#f0f0f0'}},
        },
        'series': [
            {
                'name': '输入 Token',
                'type': 'bar',
                'stack': 'token',
                'data': prompt_m,
                'itemStyle': {'color': '#10B981'},
            },
            {
                'name': '输出 Token',
                'type': 'bar',
                'stack': 'token',
                'data': completion_m,
                'itemStyle': {'color': '#F59E0B'},
            },
        ],
    }
    
    ui.echart(options=option).classes('w-full h-72')


def render_cost_distribution_chart(data: Dict) -> None:
    """渲染成本分布饼图"""
    vendors = data.get('vendors', [])
    costs = data.get('costs', [])
    free_count = data.get('free_count', 0)
    
    if not vendors and free_count == 0:
        ui.label('暂无数据').classes('text-gray-500 text-center py-8')
        return
    
    # 构建饼图数据
    pie_data = []
    for i, vendor in enumerate(vendors):
        if costs[i] > 0:
            pie_data.append({
                'name': vendor,
                'value': costs[i],
            })
    
    # 添加免费请求
    if free_count > 0:
        pie_data.append({
            'name': '免费请求',
            'value': 0.001,  # 占位，实际显示为免费
            'itemStyle': {'color': '#10B981'},
        })
    
    option = {
        'tooltip': {
            'trigger': 'item',
            'backgroundColor': 'rgba(255, 255, 255, 0.95)',
            'borderColor': '#E4E3DD',
            'textStyle': {'color': '#333', 'fontSize': 12},
        },
        'legend': {
            'orient': 'vertical',
            'right': 10,
            'top': 'center',
            'textStyle': {'color': '#555', 'fontSize': 11},
        },
        'series': [{
            'name': '成本分布',
            'type': 'pie',
            'radius': ['40%', '70%'],
            'center': ['40%', '50%'],
            'data': pie_data,
            'emphasis': {
                'itemStyle': {
                    'shadowBlur': 10,
                    'shadowOffsetX': 0,
                    'shadowColor': 'rgba(0, 0, 0, 0.2)',
                },
            },
            'label': {
                'show': True,
                'fontSize': 11,
                'color': '#555',
            },
        }],
    }
    
    ui.echart(options=option).classes('w-full h-72')


def render_success_rate_gauge(data: Dict) -> None:
    """渲染成功率环形进度图"""
    success_rate = data.get('success_rate', 0)
    total = data.get('total', 0)
    success = data.get('success', 0)
    failed = data.get('failed', 0)
    
    # 根据成功率选择颜色
    if success_rate >= 95:
        color = '#10B981'  # 绿色
    elif success_rate >= 80:
        color = '#3B82F6'  # 蓝色
    elif success_rate >= 60:
        color = '#F59E0B'  # 橙色
    else:
        color = '#EF4444'  # 红色
    
    option = {
        'series': [
            # 背景圆环
            {
                'type': 'pie',
                'radius': ['70%', '85%'],
                'center': ['50%', '45%'],
                'silent': True,
                'data': [{'value': 100, 'itemStyle': {'color': '#f0f0f0'}}],
                'label': {'show': False},
            },
            # 进度圆环
            {
                'type': 'pie',
                'radius': ['70%', '85%'],
                'center': ['50%', '45%'],
                'startAngle': 90,
                'data': [
                    {
                        'value': success_rate,
                        'itemStyle': {'color': color},
                    },
                    {
                        'value': 100 - success_rate,
                        'itemStyle': {'color': 'transparent'},
                    },
                ],
                'label': {'show': False},
            },
        ],
        'graphic': [
            # 中心数字
            {
                'type': 'text',
                'left': 'center',
                'top': '38%',
                'style': {
                    'text': f'{success_rate}%',
                    'fontSize': 32,
                    'fontWeight': 'bold',
                    'fill': '#333',
                    'textAlign': 'center',
                },
            },
            {
                'type': 'text',
                'left': 'center',
                'top': '50%',
                'style': {
                    'text': '成功率',
                    'fontSize': 12,
                    'fill': '#666',
                    'textAlign': 'center',
                },
            },
        ],
    }
    
    with ui.row().classes('w-full items-center justify-center'):
        ui.echart(options=option).classes('w-64 h-64')
    
    # 底部统计
    with ui.row().classes('w-full justify-around mt-2 text-sm'):
        ui.label(f'总请求: {total}').classes('text-gray-600')
        ui.label(f'成功: {success}').classes('text-green-600')
        ui.label(f'失败: {failed}').classes('text-red-600')
