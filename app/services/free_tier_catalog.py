"""
免费模型目录（A7）+ 免费 tier 向导服务（A1）

内置主流厂商的免费 API 额度信息，引导用户「选厂商 → 看获取步骤 → 粘 Key → 自动配置」，
全程无需理解底层概念（建账号/同步模型/能力描述/计算向量/启用 全自动完成）。

目录覆盖 ≥8 家厂商。额度信息为定性描述，具体数字以各厂商官网实时为准（不虚标）。
"""
import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import ModelAccount

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 免费模型目录（A7）
# ══════════════════════════════════════════════════════════
# 字段说明：
#   id            厂商唯一标识（URL 友好）
#   name          厂商显示名
#   icon          展示图标
#   tag           简短标签（地域/特点）
#   region        地域: 海外/国内
#   base_url      OpenAI 兼容 API Base
#   models        免费模型列表（id/display/capability/examples）
#   signup_url    获取 API Key 的入口
#   steps         获取 Key 步骤（引导用户完成「不得不做的事」）
#   balance_support  是否支持自动获取余额（fetch_balance）
#   quota_note    额度说明（定性，以官网为准）
#   extra_fields  该厂商需要的额外配置项（如 Cloudflare 的 account_id）
FREE_TIER_VENDORS: List[dict] = [
    {
        "id": "ollama",
        "name": "本地模型（Ollama）",
        "icon": "💻",
        "tag": "本地 · 完全免费",
        "region": "本地",
        "base_url": "http://localhost:11434/v1",
        "models": [
            {
                "id": "llama3.1",
                "display": "Llama 3.1（示例）",
                "capability": "Meta 开源旗舰，通用对话、写作、代码均衡，本地运行隐私安全。",
                "tags": ["chat", "code", "writing"],
                "examples": [
                    "你好", "帮我写一封邮件", "解释一下什么是数据库索引", "用Python写一个快速排序",
                ],
            },
            {
                "id": "qwen2.5",
                "display": "Qwen2.5（示例）",
                "capability": "通义千问开源模型，中文能力强，本地运行速度快。",
                "tags": ["chat", "writing"],
                "examples": [
                    "你好", "帮我写一首诗", "解释一下量子计算",
                ],
            },
            {
                "id": "deepseek-r1",
                "display": "DeepSeek-R1（示例）",
                "capability": "深度求索开源推理模型，数学、逻辑、代码推理出色。",
                "tags": ["reasoning", "code", "math"],
                "examples": [
                    "解一道数学题", "分析这段代码的时间复杂度", "解释一下贝叶斯定理",
                ],
            },
        ],
        "signup_url": "https://ollama.com/",
        "steps": [
            "下载安装 Ollama（支持 Windows/macOS/Linux）",
            "终端执行 ollama pull 模型名，拉取想用的模型",
            "无需 Key，确保本机 Ollama 已启动，直接点击一键配置",
        ],
        "balance_support": False,
        "quota_note": "完全免费无上限，跑的是本地开源模型；卡片模型为示例，实际以你本地已安装的为准（自动探测）",
        "no_key": True,
    },
    {
        "id": "zhipu",
        "name": "智谱 AI",
        "icon": "🧪",
        "tag": "国内 · 注册赠送",
        "region": "国内",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": [
            {
                "id": "glm-4-flash",
                "display": "GLM-4-Flash（官方免费）",
                "capability": "智谱官方免费模型，通用对话、写作、问答，国内直连速度快。",
                "tags": ["chat", "writing", "fast"],
                "examples": [
                    "你好", "帮我写一段产品介绍", "解释一下什么是机器学习",
                    "推荐几本经济学入门书", "帮我写一份周报",
                ],
            },
        ],
        "signup_url": "https://open.bigmodel.cn/",
        "steps": [
            "打开上方链接注册账号（手机号即可）",
            "右上角头像菜单 → API Keys，创建 API Key",
            "复制 Key（id.secret 两段式），粘贴到下方输入框",
        ],
        "balance_support": False,
        "quota_note": "GLM-4-Flash 官方免费（限速）；注册赠送 token 可用于其他模型。具体以官网实时为准",
    },    {
        "id": "siliconflow",
        "name": "硅基流动 SiliconFlow",
        "icon": "🌊",
        "tag": "国内 · 注册赠送",
        "region": "国内",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": [
            {
                "id": "Qwen/Qwen2.5-7B-Instruct",
                "display": "Qwen2.5 7B（免费）",
                "capability": "通义千问开源模型，通用对话、写作，国内直连。",
                "tags": ["chat", "writing"],
                "examples": [
                    "你好", "帮我写一封邮件", "解释一下什么是5G",
                ],
            },
            {
                "id": "THUDM/glm-4-9b-chat",
                "display": "GLM-4 9B（免费）",
                "capability": "智谱开源模型，中文理解与对话能力好。",
                "tags": ["chat", "writing"],
                "examples": [
                    "你好", "帮我写一首诗", "解释一下量子纠缠",
                ],
            },
        ],
        "signup_url": "https://cloud.siliconflow.cn/",
        "steps": [
            "打开上方链接注册账号（手机号即可）",
            "进入 API 密钥页，点击新建密钥",
            "复制 Key（sk- 开头），粘贴到下方输入框",
        ],
        "balance_support": True,
        "quota_note": "注册赠送 14 元体验额度；部分开源模型免费（标注免费）；支持自动获取余额。具体以官网实时为准",
    },    {
        "id": "moonshot",
        "name": "月之暗面 Kimi",
        "icon": "🌙",
        "tag": "国内 · 新用户赠送",
        "region": "国内",
        "base_url": "https://api.moonshot.cn/v1",
        "models": [
            {
                "id": "moonshot-v1-8k",
                "display": "Moonshot V1 8K",
                "capability": "Kimi 基础版，长文本理解与中文对话出色。",
                "tags": ["chat", "long-context", "writing"],
                "examples": [
                    "你好", "帮我总结一份长文档", "写一篇议论文",
                ],
            },
            {
                "id": "kimi-k2.6",
                "display": "Kimi K2.6（长上下文旗舰）",
                "capability": "Kimi 旗舰模型，超长上下文（256K），创意写作、文档分析、翻译。",
                "tags": ["creative", "writing", "long-context", "translation"],
                "examples": [
                    "写一篇关于秋天的散文", "帮我润色这段营销文案", "分析这份合同的风险点",
                    "把这段中文翻译成英文", "写一个科幻短篇的开头",
                ],
            },
        ],
        "signup_url": "https://platform.moonshot.cn/",
        "steps": [
            "打开上方链接注册账号",
            "进入 API Key 管理，创建新 Key",
            "复制 Key（sk- 开头），粘贴到下方输入框",
        ],
        "balance_support": True,
        "quota_note": "新用户注册赠送额度；支持自动获取余额。具体以官网实时为准",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "icon": "🐋",
        "tag": "国内 · 极低价",
        "region": "国内",
        "base_url": "https://api.deepseek.com/v1",
        "models": [
            {
                "id": "deepseek-chat",
                "display": "DeepSeek-V3（通用）",
                "capability": "深度求索旗舰通用模型，代码、推理、写作全面，价格极低。",
                "tags": ["chat", "code", "reasoning"],
                "examples": [
                    "你好", "用Python写一个爬虫", "帮我调试这段报错", "解释一下动态规划",
                ],
            },
            {
                "id": "deepseek-reasoner",
                "display": "DeepSeek-R1（推理）",
                "capability": "深度推理模型，数学、逻辑、复杂分析能力强。",
                "tags": ["reasoning", "math", "code"],
                "examples": [
                    "解一道高中数学题", "证明费马小定理", "分析这份数据的异常点",
                ],
            },
        ],
        "signup_url": "https://platform.deepseek.com/",
        "steps": [
            "打开上方链接注册账号（手机号即可）",
            "进入 API Keys 页创建 API Key",
            "复制 Key（sk- 开头），粘贴到下方输入框",
        ],
        "balance_support": True,
        "quota_note": "按量计费价格极低（无免费额度，充 10 元可用很久）；支持自动获取余额。具体以官网实时为准",
    },
    {
        "id": "aliyun",
        "name": "阿里百炼（通义千问）",
        "icon": "🌤️",
        "tag": "国内 · 新用户赠送",
        "region": "国内",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": [
            {
                "id": "qwen-turbo",
                "display": "Qwen-Turbo（赠送）",
                "capability": "通义千问轻量模型，速度快，日常对话、写作、问答免费额度大。",
                "tags": ["chat", "writing", "fast"],
                "examples": [
                    "你好", "帮我写一段产品介绍", "解释一下什么是API",
                ],
            },
            {
                "id": "qwen-plus",
                "display": "Qwen-Plus（增强）",
                "capability": "通义千问增强模型，理解与生成质量更高，通用场景。",
                "tags": ["chat", "writing", "reasoning"],
                "examples": [
                    "你好", "帮我写一份周报", "分析这篇文章的论点",
                ],
            },
        ],
        "signup_url": "https://bailian.console.aliyun.com/",
        "steps": [
            "打开上方链接注册账号（手机号即可，需实名）",
            "开通百炼，进入 API-KEY 管理创建",
            "复制 Key（sk- 开头），粘贴到下方输入框",
        ],
        "balance_support": False,
        "quota_note": "新用户赠送免费额度，qwen-turbo 等模型有免费调用额度。具体以官网实时为准",
    },
    {
        "id": "hunyuan",
        "name": "腾讯混元",
        "icon": "🌀",
        "tag": "国内 · 注册赠送",
        "region": "国内",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "models": [
            {
                "id": "hunyuan-turbos-latest",
                "display": "混元 TurboS（免费）",
                "capability": "腾讯混元旗舰，中文对话、写作、代码均衡，TurboS 系列免费。",
                "tags": ["chat", "code", "writing"],
                "examples": [
                    "你好", "帮我写一封请假邮件", "解释一下区块链原理",
                ],
            },
            {
                "id": "hunyuan-turbo",
                "display": "混元 Turbo",
                "capability": "混元标准模型，速度快成本低，日常问答够用。",
                "tags": ["chat", "fast"],
                "examples": [
                    "你好", "今天天气怎么样", "1+1等于几",
                ],
            },
        ],
        "signup_url": "https://console.cloud.tencent.com/hunyuan",
        "steps": [
            "打开上方链接注册账号（手机号即可，需实名）",
            "开通混元大模型，进入密钥管理创建 API Key",
            "复制 Key（sk- 开头），粘贴到下方输入框",
        ],
        "balance_support": False,
        "quota_note": "混元 TurboS 等模型官方免费额度，注册赠送 token。具体以官网实时为准",
    },
    {
        "id": "doubao",
        "name": "字节豆包（火山方舟）",
        "icon": "🫘",
        "tag": "国内 · 新用户赠送",
        "region": "国内",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": [
            {
                "id": "doubao-seed-1-6-lite",
                "display": "Doubao Seed 1.6 Lite（示例）",
                "capability": "豆包轻量模型，速度快，日常对话、写作免费额度大。",
                "tags": ["chat", "fast", "writing"],
                "examples": [
                    "你好", "帮我写一句宣传语", "总结这段话",
                ],
            },
            {
                "id": "doubao-1-5-pro",
                "display": "Doubao 1.5 Pro（示例）",
                "capability": "豆包旗舰模型，理解与生成质量高，支持长上下文。",
                "tags": ["chat", "reasoning", "long-context"],
                "examples": [
                    "你好", "分析这份合同的风险点", "帮我写一份方案",
                ],
            },
        ],
        "signup_url": "https://console.volcengine.com/ark",
        "steps": [
            "打开上方链接注册账号（手机号即可，需实名）",
            "开通火山方舟，创建推理接入点（Endpoint）",
            "创建 API Key，复制 Key，下方还需填 Endpoint ID",
        ],
        "balance_support": False,
        "quota_note": "新用户赠送额度；需额外填写 Endpoint ID（方舟控制台推理接入点页复制）。具体以官网实时为准",
        "extra_fields": [
            {"key": "endpoint_id", "label": "Endpoint ID", "placeholder": "火山方舟推理接入点 ID（如 ep-2026...）"},
        ],
        "require_extra": "endpoint_id",
    },
    {
        "id": "qianfan",
        "name": "百度千帆",
        "icon": "🌐",
        "tag": "国内 · 注册赠送",
        "region": "国内",
        "base_url": "https://qianfan.baidubce.com/v2",
        "models": [
            {
                "id": "ernie-speed-8k",
                "display": "ERNIE Speed（免费）",
                "capability": "百度文心轻量模型，速度快，日常问答、写作免费。",
                "tags": ["chat", "fast", "writing"],
                "examples": [
                    "你好", "帮我写一份会议纪要", "解释一下什么是物联网",
                ],
            },
            {
                "id": "ernie-4.0-turbo-8k",
                "display": "ERNIE 4.0 Turbo",
                "capability": "文心 4.0 轻量旗舰，理解与推理质量高。",
                "tags": ["chat", "reasoning"],
                "examples": [
                    "你好", "分析这段代码的问题", "推荐一个学习路线",
                ],
            },
        ],
        "signup_url": "https://console.bce.baidu.com/qianfan/",
        "steps": [
            "打开上方链接注册账号（手机号即可，需实名）",
            "开通千帆大模型平台，进入 API Key 管理",
            "复制 API Key（bce-v3 开头），粘贴到下方输入框",
        ],
        "balance_support": False,
        "quota_note": "注册实名赠送额度，ERNIE Speed 有免费调用。具体以官网实时为准",
    },
    {
        "id": "groq",
        "name": "Groq",
        "icon": "⚡",
        "tag": "海外 · 速度极快",
        "region": "海外",
        "base_url": "https://api.groq.com/openai/v1",
        "models": [
            {
                "id": "llama-3.3-70b-versatile",
                "display": "Llama 3.3 70B（通用）",
                "capability": "通用对话能力强，推理、写作、翻译、代码问答均擅长，响应速度极快。",
                "tags": ["chat", "code", "reasoning"],
                "examples": [
                    "你好，介绍一下你自己", "用Python写一个快速排序", "帮我写一封请假邮件",
                    "解释一下什么是区块链", "把这句话翻译成英文：今天天气很好",
                ],
            },
            {
                "id": "llama-3.1-8b-instant",
                "display": "Llama 3.1 8B（轻量）",
                "capability": "轻量快速，适合简单问答、文本分类、摘要等低延迟任务。",
                "tags": ["chat", "fast", "classification"],
                "examples": [
                    "你好", "今天天气怎么样", "总结这段文字的要点", "1+1等于几",
                ],
            },
        ],
        "signup_url": "https://console.groq.com/keys",
        "steps": [
            "打开上方链接注册账号（支持 Google 一键登录）",
            "进入左侧 API Keys 页，创建 API Key",
            "复制 Key（sk- 开头），粘贴到下方输入框",
        ],
        "balance_support": False,
        "quota_note": "免费额度大（按分钟限速），适合日常薅羊毛；具体额度以官网实时为准",
        "access_note": "海外站点，国内访问可能不稳定，建议科学上网",
    },    {
        "id": "cerebras",
        "name": "Cerebras",
        "icon": "🚀",
        "tag": "海外 · 超快推理",
        "region": "海外",
        "base_url": "https://api.cerebras.ai/v1",
        "models": [
            {
                "id": "llama-3.3-70b",
                "display": "Llama 3.3 70B（极速版）",
                "capability": "世界最快推理的 Llama 3.3 70B，通用对话、代码、分析均出色，延迟极低。",
                "tags": ["chat", "code", "reasoning"],
                "examples": [
                    "你好", "解释一下TCP三次握手", "写一段Python代码计算斐波那契数列",
                    "帮我分析这段日志的报错原因", "写一个工作周报的模板",
                ],
            },
        ],
        "signup_url": "https://cloud.cerebras.ai/",
        "steps": [
            "打开上方链接注册账号",
            "进入 Settings → API Keys，新建 Key",
            "复制 Key（csk- 开头），粘贴到下方输入框",
        ],
        "balance_support": False,
        "quota_note": "注册赠送免费额度，推理速度极快；具体额度以官网实时为准",
        "access_note": "海外站点，国内访问可能不稳定，建议科学上网",
    },    {
        "id": "mistral",
        "name": "Mistral",
        "icon": "🌬️",
        "tag": "海外 · 开发者免费",
        "region": "海外",
        "base_url": "https://api.mistral.ai/v1",
        "models": [
            {
                "id": "open-mistral-nemo",
                "display": "Mistral Nemo 12B（免费）",
                "capability": "免费小模型，多语言能力强，适合日常对话、摘要、分类等常规任务。",
                "tags": ["chat", "multilingual", "fast"],
                "examples": [
                    "你好", "帮我总结一下这段话", "推荐一本法语学习书", "把这段中文翻译成英文",
                ],
            },
            {
                "id": "mistral-small-latest",
                "display": "Mistral Small（轻量旗舰）",
                "capability": "轻量级旗舰模型，代码、推理、多语言兼顾，速度快成本低。",
                "tags": ["chat", "code", "reasoning"],
                "examples": [
                    "用Python写一个二分查找", "解释一下量子计算", "帮我起一个英文品牌名",
                ],
            },
        ],
        "signup_url": "https://console.mistral.ai/",
        "steps": [
            "打开上方链接注册账号",
            "进入 API Keys 页，点击 Create new key",
            "复制 Key，粘贴到下方输入框",
        ],
        "balance_support": False,
        "quota_note": "免费 tier 赠送额度，开放模型（open- 前缀）免费使用；具体以官网实时为准",
        "access_note": "海外站点，国内访问可能不稳定，建议科学上网",
    },    {
        "id": "gemini",
        "name": "Google Gemini",
        "icon": "✨",
        "tag": "海外 · 免费额度大",
        "region": "海外",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": [
            {
                "id": "gemini-2.0-flash",
                "display": "Gemini 2.0 Flash",
                "capability": "免费额度大的多模态模型，支持文本/图像输入，速度快，综合能力强。",
                "tags": ["chat", "multimodal", "fast", "reasoning"],
                "examples": [
                    "你好", "分析这张图片的内容", "写一首关于夏天的诗",
                    "解释一下相对论", "帮我规划一次杭州三日游",
                ],
            },
            {
                "id": "gemini-2.5-flash",
                "display": "Gemini 2.5 Flash（思考型）",
                "capability": "带思考能力的 Flash 模型，复杂推理、数学、编程表现更好。",
                "tags": ["reasoning", "code", "math"],
                "examples": [
                    "解一道高中数学题", "分析这段代码的时间复杂度", "设计一个分布式锁方案",
                ],
            },
        ],
        "signup_url": "https://aistudio.google.com/apikey",
        "steps": [
            "打开上方链接（需科学上网）",
            "用 Google 账号登录，点击 Create API key",
            "复制 Key（AIza 开头），粘贴到下方输入框",
        ],
        "balance_support": False,
        "quota_note": "免费 tier 额度较大（按分钟/天限速），Flash 系列免费；具体以官网实时为准",
        "access_note": "需科学上网访问",
    },    {
        "id": "openrouter",
        "name": "OpenRouter",
        "icon": "🔀",
        "tag": "聚合 · 免费模型池",
        "region": "海外",
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            {
                "id": "meta-llama/llama-3.3-70b-instruct:free",
                "display": "Llama 3.3 70B（:free）",
                "capability": "OpenRouter 免费路由的 Llama 3.3 70B，通用对话能力强。",
                "tags": ["chat", "code", "reasoning"],
                "examples": [
                    "你好", "解释一下什么是API", "帮我写一份产品需求文档",
                ],
            },
            {
                "id": "deepseek/deepseek-chat-v3-0324:free",
                "display": "DeepSeek V3（:free）",
                "capability": "DeepSeek V3 免费路由版，代码与推理能力突出。",
                "tags": ["code", "reasoning", "chat"],
                "examples": [
                    "用Python写一个爬虫", "解释一下DP动态规划", "帮我调试这段报错",
                ],
            },
        ],
        "signup_url": "https://openrouter.ai/keys",
        "steps": [
            "打开上方链接注册账号",
            "进入 Keys 页，点击 Create Key",
            "复制 Key（sk-or-v1- 开头），粘贴到下方输入框",
        ],
        "balance_support": False,
        "quota_note": ":free 后缀模型免费（有限速/非高峰限制）；付费模型按用量扣费，需充值。具体以官网实时为准",
        "access_note": "海外站点，国内访问可能不稳定，建议科学上网",
    },    {
        "id": "github-models",
        "name": "GitHub Models",
        "icon": "🐙",
        "tag": "开发者 · 限速免费",
        "region": "海外",
        "base_url": "https://models.inference.ai.azure.com",
        "models": [
            {
                "id": "gpt-4o-mini",
                "display": "GPT-4o mini",
                "capability": "OpenAI 轻量模型，速度快，通用对话与代码辅助都够用。",
                "tags": ["chat", "code", "fast"],
                "examples": [
                    "你好", "用Python写一个冒泡排序", "帮我润色这段英文",
                ],
            },
            {
                "id": "gpt-4.1-mini",
                "display": "GPT-4.1 mini",
                "capability": "GPT-4.1 轻量版，代码与长上下文能力更强。",
                "tags": ["chat", "code", "reasoning"],
                "examples": [
                    "解释一下RESTful API设计", "写一个SQL窗口函数示例",
                ],
            },
        ],
        "signup_url": "https://github.com/settings/tokens",
        "steps": [
            "打开上方链接（需 GitHub 账号）",
            "Generate new token → Fine-grained，勾选 Models 读取",
            "复制 token（github_pat_ 开头），粘贴到下方输入框",
        ],
        "balance_support": False,
        "quota_note": "GitHub 账号免费使用，按请求限速（每分钟约 15-20 请求）；具体以官网实时为准",
        "access_note": "GitHub 国内访问可能不稳定，建议科学上网",
    },    {
        "id": "cloudflare",
        "name": "Cloudflare Workers AI",
        "icon": "☁️",
        "tag": "海外 · 每日免费额度",
        "region": "海外",
        "base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "models": [
            {
                "id": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
                "display": "Llama 3.3 70B（Workers AI）",
                "capability": "Cloudflare 边缘推理的 Llama 3.3 70B，通用对话与代码能力均衡。",
                "tags": ["chat", "code", "reasoning"],
                "examples": [
                    "你好", "帮我写一个函数", "解释一下CDN原理",
                ],
            },
        ],
        "signup_url": "https://dash.cloudflare.com/",
        "steps": [
            "打开上方链接注册账号",
            "复制右侧的 Account ID（稍后需填写）",
            "创建 API Token（需 AI 权限），复制",
            "注意：还需额外填写 Account ID",
        ],
        "balance_support": False,
        "quota_note": "免费 tier 每日赠送额度（约 10k 神经元/天）；需要 Account ID + Token 两样。具体以官网实时为准",
        "extra_fields": [
            {"key": "account_id", "label": "Account ID", "placeholder": "Cloudflare 账户 ID（如 8b3f...）"},
        ],
    },
]


# ══════════════════════════════════════════════════════════
# 厂商别名表
# ══════════════════════════════════════════════════════════
# 同一厂商在账号管理里可能被写成不同名称（如"月之暗面 (Moonshot)" / "月之暗面 Kimi"），
# 幂等查重与"已接入"判定必须按别名模糊匹配，否则会重复建号。
VENDOR_ALIASES: dict = {
    "groq": ["groq"],
    "cerebras": ["cerebras"],
    "mistral": ["mistral"],
    "gemini": ["gemini", "google"],
    "openrouter": ["openrouter"],
    "github-models": ["github", "github models"],
    "cloudflare": ["cloudflare"],
    "zhipu": ["智谱", "zhipu", "bigmodel", "glm"],
    "siliconflow": ["硅基流动", "siliconflow"],
    "moonshot": ["月之暗面", "moonshot", "kimi"],
    "ollama": ["ollama", "本地", "local"],
    "deepseek": ["deepseek", "深度求索"],
    "aliyun": ["阿里", "百炼", "dashscope", "通义", "qwen"],
    "hunyuan": ["腾讯", "混元", "hunyuan"],
    "doubao": ["字节", "豆包", "doubao", "火山", "方舟", "volcengine", "ark"],
    "qianfan": ["百度", "千帆", "qianfan", "文心", "ernie"],
}


def vendor_matches(vendor_name: str, vendor_id: str) -> bool:
    """判断账号的 vendor 名称是否属于目录中的某厂商（别名模糊匹配）"""
    if not vendor_name:
        return False
    aliases = VENDOR_ALIASES.get(vendor_id, [])
    if not aliases:
        return False
    n = vendor_name.lower()
    return any(a.lower() in n for a in aliases)


def get_vendor(vendor_id: str) -> Optional[dict]:
    """按 id 获取厂商目录项"""
    for v in FREE_TIER_VENDORS:
        if v["id"] == vendor_id:
            return v
    return None


def list_vendors() -> List[dict]:
    """返回厂商简要列表（不含模型 examples，减少传输）"""
    return [
        {
            "id": v["id"],
            "name": v["name"],
            "icon": v["icon"],
            "tag": v["tag"],
            "region": v["region"],
            "models": [m["id"] for m in v["models"]],
            "signup_url": v["signup_url"],
            "balance_support": v["balance_support"],
            "quota_note": v["quota_note"],
            "no_key": v.get("no_key", False),
            "extra_fields": v.get("extra_fields", []),
            "access_note": v.get("access_note", ""),
        }
        for v in FREE_TIER_VENDORS
    ]


# ══════════════════════════════════════════════════════════
# 免费 tier 向导服务（A1）
# ══════════════════════════════════════════════════════════

class FreeTierService:
    """
    向导自动配置：给定厂商 + API Key（+额外字段如 account_id），
    自动完成 建账号 → 同步模型 → 能力描述 → 计算向量 → 启用。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def auto_configure(
        self,
        vendor_id: str,
        api_key: str,
        extra: Optional[dict] = None,
    ) -> dict:
        """
        执行自动配置。

        Args:
            vendor_id: 厂商 id（FREE_TIER_VENDORS）
            api_key: 用户粘贴的 API Key
            extra: 额外字段（如 Cloudflare account_id）

        Returns:
            {
                "vendor": 厂商名,
                "created_accounts": [账号列表],
                "skipped": [已存在跳过的模型],
                "models_synced": [同步的模型],
                "balance": (unit, bal) 或 None,
                "errors": [错误信息],
            }
        """
        from app.utils.encryption import encryption_service

        vendor = get_vendor(vendor_id)
        if not vendor:
            raise ValueError(f"未知厂商: {vendor_id}")
        extra = extra or {}

        # 必填 extra 字段校验（Cloudflare account_id / 豆包 endpoint_id）
        req_key = vendor.get("require_extra") or "account_id"
        req_label = {"account_id": "Account ID", "endpoint_id": "Endpoint ID"}.get(req_key, req_key)
        if vendor.get("require_extra") or "{account_id}" in vendor["base_url"]:
            if not (extra.get(req_key) or "").strip():
                raise ValueError(f"{vendor['name']} 需要填写 {req_label}")

        # no_key 厂商（本地 Ollama）：跳过 API Key 校验
        if not vendor.get("no_key") and (not api_key or not api_key.strip()):
            raise ValueError("API Key 不能为空")

        # 处理 base_url 模板（Cloudflare 需要 account_id 填入 URL）
        base_url = vendor["base_url"]
        if "{account_id}" in base_url:
            account_id = (extra.get("account_id") or "").strip()
            base_url = base_url.replace("{account_id}", account_id)

        # 1. 探测真实模型列表（优先用真实模型，目录兜底）
        catalog_model_ids = [m["id"] for m in vendor["models"]]
        real_models = []
        try:
            from app.services.balance import fetch_models
            tmp = ModelAccountProxy(
                vendor=vendor["name"],
                api_key_encrypted=encryption_service.encrypt(api_key.strip()),
                base_url=base_url,
            )
            real_models = await fetch_models(tmp)
        except Exception as e:
            logger.warning(f"[向导] {vendor['name']} 模型探测失败: {e}")

        if vendor.get("no_key"):
            # 本地模型（Ollama）：必须探测到真实本地模型，探测失败直接返回提示
            if not real_models:
                return {
                    "vendor": vendor["name"],
                    "created_accounts": [],
                    "skipped": [],
                    "models_synced": [],
                    "balance": None,
                    "errors": ["未检测到本地 Ollama 服务或模型，请先安装 Ollama 并执行 ollama pull 拉取模型"],
                }
            models = real_models
        elif vendor.get("require_extra") == "endpoint_id" and (extra.get("endpoint_id") or "").strip():
            # 豆包（火山方舟）：以推理接入点 Endpoint 作为模型入口
            models = [(extra.get("endpoint_id") or "").strip()]
        elif real_models:
            # 目录优先：取 目录∩真实；交集为空则用真实前 2 个
            models = [m for m in catalog_model_ids if m in real_models]
            if not models:
                models = real_models[:2]
        else:
            models = catalog_model_ids
        logger.info(f"[向导] {vendor['name']} 模型清单: {models}（真实探测 {len(real_models)} 个）")

        # 2. 逐个模型建账号 + 同步目录 + 计算向量
        result = {
            "vendor": vendor["name"],
            "created_accounts": [],
            "skipped": [],
            "models_synced": [],
            "balance": None,
            "errors": [],
        }

        for model_id in models:
            try:
                # 查重：同厂商（别名匹配）同模型已存在则跳过，避免重复建号
                existing_result = await self.db.execute(
                    select(ModelAccount).where(ModelAccount.model_name == model_id)
                )
                duplicated = None
                for acc in existing_result.scalars().all():
                    if vendor_matches(acc.vendor or "", vendor["id"]):
                        duplicated = acc
                        break
                if duplicated:
                    result["skipped"].append(model_id)
                    continue

                account = ModelAccountProxy.to_model(
                    vendor_name=vendor["name"],
                    model_name=model_id,
                    api_key_encrypted=encryption_service.encrypt(api_key.strip()),
                    base_url=base_url,
                )
                self.db.add(account)
                await self.db.flush()
                result["created_accounts"].append(f"{vendor['name']} / {model_id}")

                # 同步模型目录 + 能力描述 + 向量
                display_override = None
                if (
                    vendor.get("require_extra") == "endpoint_id"
                    and (extra.get("endpoint_id") or "").strip()
                    and model_id == (extra.get("endpoint_id") or "").strip()
                    and vendor["models"]
                ):
                    display_override = vendor["models"][0]["display"]
                await self._sync_model(account, vendor, model_id, display_override)
                result["models_synced"].append(model_id)
            except Exception as e:
                logger.error(f"[向导] 配置 {model_id} 失败: {e}", exc_info=True)
                result["errors"].append(f"{model_id}: {str(e)[:100]}")

        await self.db.commit()

        # 3. 尝试自动获取余额（支持的厂商）
        if vendor["balance_support"] and result["created_accounts"]:
            try:
                from app.services.balance import fetch_balance
                unit, bal = await fetch_balance(
                    ModelAccountProxy(
                        vendor=vendor["name"],
                        api_key_encrypted=encryption_service.encrypt(api_key.strip()),
                        base_url=base_url,
                    )
                )
                result["balance"] = (unit, float(bal))
            except Exception as e:
                logger.warning(f"[向导] 余额获取失败: {e}")

        return result

    async def _sync_model(self, account, vendor: dict, model_id: str, display_override: str = None):
        """建 ModelCatalog + 能力描述 + 示例 + 计算向量（多示例平均）"""
        from app.models.database import ModelCatalog
        from app.pipeline.config import PipelineConfig
        from app.services.embedding import EmbeddingService

        # 从目录取该模型的信息
        model_meta = next((m for m in vendor["models"] if m["id"] == model_id), None)

        catalog_result = await self.db.execute(
            select(ModelCatalog).where(ModelCatalog.model_name == model_id)
        )
        catalog = catalog_result.scalar_one_or_none()
        if not catalog:
            catalog = ModelCatalog(
                vendor=vendor["name"],
                model_name=model_id,
                display_name=display_override or (model_meta or {}).get("display") or model_id,
                capability_description=(model_meta or {}).get("capability")
                or f"{vendor['name']} {model_id} 模型，具备通用对话能力。",
                capability_tags=(model_meta or {}).get("tags") or ["chat", "general"],
                examples=(model_meta or {}).get("examples") or [],
                is_active=True,
            )
            self.db.add(catalog)
            await self.db.flush()
        elif not catalog.examples and model_meta and model_meta.get("examples"):
            catalog.examples = model_meta["examples"]
            catalog.capability_description = model_meta["capability"]
            catalog.embedding_vector = None

        # 计算向量（多示例平均；无示例则用能力描述）
        examples = catalog.examples or []
        cfg = await PipelineConfig.load(self.db)
        embed_svc = EmbeddingService(cfg.router_config, db=self.db)
        if examples:
            vectors = []
            for ex in examples[:8]:
                vec = await embed_svc.embed(ex)
                if vec:
                    vectors.append(vec)
            if vectors:
                dim = len(vectors[0])
                catalog.embedding_vector = [
                    sum(v[i] for v in vectors) / len(vectors) for i in range(dim)
                ]
        elif catalog.capability_description:
            vec = await embed_svc.embed(catalog.capability_description)
            if vec:
                catalog.embedding_vector = vec


class ModelAccountProxy:
    """轻量账号代理：供 fetch_models/fetch_balance 探测使用（不落库）"""

    def __init__(self, vendor: str, api_key_encrypted: str, base_url: str):
        self.vendor = vendor
        self.api_key_encrypted = api_key_encrypted
        self.base_url = base_url
        self.id = None
        self.model_name = "probe"

    @staticmethod
    def to_model(vendor_name: str, model_name: str, api_key_encrypted: str, base_url: str):
        from app.models.database import ModelAccount
        return ModelAccount(
            vendor=vendor_name,
            model_name=model_name,
            api_key_encrypted=api_key_encrypted,
            base_url=base_url,
            virtual_model="chat",
            priority=50,
            is_enable=True,
            balance_unit="token",
            balance_remaining=None,
        )
