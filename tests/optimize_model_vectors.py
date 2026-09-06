"""
M4 路由优化：更新模型能力描述 + 多示例平均向量
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.models import AsyncSessionLocal
from app.models.database import ModelCatalog
from app.services.embedding import EmbeddingService
from app.pipeline.config import PipelineConfig
from sqlalchemy import select

# 优化后的能力描述（更短、更精准、关键词突出）
OPTIMIZED_DESCRIPTIONS = {
    "qwen-plus": "编程代码生成、算法实现、技术问答、数据分析、数学推理。擅长写代码、调试、SQL、系统设计。",
    "kimi-k2.6": "创意写作、文案生成、故事创作、诗歌、长文本理解、文档分析。擅长写文章、润色、总结、翻译。",
}

# 每个模型的典型用户请求示例（10条，用于计算平均向量）
MODEL_EXAMPLES = {
    "qwen-plus": [
        "用Python写一个快速排序算法",
        "帮我调试这段JavaScript代码，报错undefined",
        "写一个SQL查询，统计每个部门的平均工资",
        "React Hooks的useEffect怎么用？",
        "写一个正则表达式匹配邮箱地址",
        "如何用Python爬取网页数据？",
        "解释一下TCP三次握手过程",
        "设计一个高并发的秒杀系统架构",
        "帮我分析这份销售数据的趋势",
        "用Excel怎么做数据透视表？",
    ],
    "kimi-k2.6": [
        "写一篇关于秋天的散文，要意境优美",
        "帮我写一个产品发布会的开场白",
        "写一首关于月亮的现代诗",
        "给我想一个奶茶店的名字和slogan",
        "写一个科幻短篇小说的开头",
        "帮我润色这段营销文案，更有感染力",
        "你好，今天天气怎么样？",
        "推荐一本好看的小说",
        "怎么做好时间管理？",
        "帮我翻译这句话成英文：人工智能正在改变世界",
    ],
}


async def optimize():
    async with AsyncSessionLocal() as session:
        # 加载配置
        cfg = await PipelineConfig.load(session)
        embed_svc = EmbeddingService(cfg.router_config, db=session)

        # 更新每个模型
        for model_name, description in OPTIMIZED_DESCRIPTIONS.items():
            result = await session.execute(
                select(ModelCatalog).where(ModelCatalog.model_name == model_name)
            )
            model = result.scalar_one_or_none()
            if not model:
                print(f"模型 {model_name} 不存在，跳过")
                continue

            # 更新能力描述
            model.capability_description = description
            print(f"更新 {model_name} 能力描述: {description[:50]}...")

            # 计算多示例平均向量
            examples = MODEL_EXAMPLES.get(model_name, [])
            if examples:
                vectors = []
                for example in examples:
                    vec = await embed_svc.embed(example)
                    if vec:
                        vectors.append(vec)

                if vectors:
                    # 计算平均向量
                    dim = len(vectors[0])
                    avg_vector = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
                    model.embedding_vector = avg_vector
                    print(f"  计算多示例平均向量: {len(vectors)} 条示例, {dim} 维")

        await session.commit()
        print("\n优化完成！")


if __name__ == "__main__":
    asyncio.run(optimize())
