"""
更新模型 examples 并重新计算多示例平均向量
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.models import AsyncSessionLocal
from app.models.database import ModelCatalog
from app.services.embedding import EmbeddingService
from app.services.model_catalog_service import PRESET_MODEL_DESCRIPTIONS
from app.pipeline.config import PipelineConfig
from sqlalchemy import select


async def update():
    async with AsyncSessionLocal() as session:
        cfg = await PipelineConfig.load(session)
        embed_svc = EmbeddingService(cfg.router_config, db=session)

        for model_name, preset in PRESET_MODEL_DESCRIPTIONS.items():
            result = await session.execute(
                select(ModelCatalog).where(ModelCatalog.model_name == model_name)
            )
            model = result.scalar_one_or_none()
            if not model:
                continue

            # 更新 examples
            if preset.get("examples"):
                model.examples = preset["examples"]
                print(f"更新 {model_name}: {len(preset['examples'])} 条示例")

            # 更新能力描述
            if preset.get("capability_description"):
                model.capability_description = preset["capability_description"]

            # 重新计算多示例平均向量
            if model.examples:
                vectors = []
                for example in model.examples:
                    vec = await embed_svc.embed(example)
                    if vec:
                        vectors.append(vec)
                if vectors:
                    dim = len(vectors[0])
                    avg_vector = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
                    model.embedding_vector = avg_vector
                    print(f"  重新计算向量: {len(vectors)} 条, {dim} 维")

        await session.commit()
        print("\n更新完成！")


if __name__ == "__main__":
    asyncio.run(update())
