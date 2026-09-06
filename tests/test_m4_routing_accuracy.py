"""
M4 路由准确率测试：20+ 场景覆盖
直接调用 VectorRouter 逻辑，测试不同用户请求的路由决策
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.models import AsyncSessionLocal
from app.models.database import ModelCatalog
from app.services.embedding import EmbeddingService
from app.services.model_catalog_service import ModelCatalogService
from app.pipeline.config import RouterConfig, PipelineConfig
from app.pipeline.router.vector import VectorRouter
from app.pipeline.context import PipelineContext
from sqlalchemy import select

# 20+ 测试场景
TEST_CASES = [
    # 编程相关（预期 qwen-plus，因为 qwen-plus 能力描述强调代码生成）
    ("用Python写一个快速排序算法", "code"),
    ("帮我调试这段JavaScript代码，报错undefined", "code"),
    ("写一个SQL查询，统计每个部门的平均工资", "code"),
    ("React Hooks的useEffect怎么用？", "code"),
    ("写一个正则表达式匹配邮箱地址", "code"),
    ("如何用Python爬取网页数据？", "code"),
    ("解释一下TCP三次握手过程", "code"),
    ("设计一个高并发的秒杀系统架构", "code"),

    # 创意写作（预期 kimi-k2.6，因为 kimi 能力描述强调创意写作）
    ("写一篇关于秋天的散文，要意境优美", "creative"),
    ("帮我写一个产品发布会的开场白", "creative"),
    ("写一首关于月亮的现代诗", "creative"),
    ("给我想一个奶茶店的名字和slogan", "creative"),
    ("写一个科幻短篇小说的开头", "creative"),
    ("帮我润色这段营销文案，更有感染力", "creative"),

    # 数据分析（预期 qwen-plus，因为 qwen-plus 强调数据分析）
    ("帮我分析这份销售数据的趋势", "data"),
    ("用Excel怎么做数据透视表？", "data"),
    ("解释一下什么是正态分布", "data"),
    ("帮我算一下这组数据的标准差", "data"),

    # 通用对话（两者都可能，看相似度）
    ("你好，今天天气怎么样？", "general"),
    ("推荐一本好看的小说", "general"),
    ("怎么做好时间管理？", "general"),
    ("解释一下什么是区块链", "general"),
    ("帮我翻译这句话成英文：人工智能正在改变世界", "general"),
    ("总结一下第二次世界大战的起因", "general"),
]


async def run_tests():
    async with AsyncSessionLocal() as session:
        # 加载配置
        cfg = await PipelineConfig.load(session)
        router_config = cfg.router_config

        # 初始化 embedding 服务
        embed_svc = EmbeddingService(router_config, db=session)

        # 加载模型
        result = await session.execute(
            select(ModelCatalog).where(ModelCatalog.is_active == True)  # noqa: E712
        )
        models = result.scalars().all()
        print(f"已加载 {len(models)} 个模型:")
        for m in models:
            print(f"  - {m.model_name} ({m.vendor})")
        print()

        # 初始化路由器
        router = VectorRouter(router_config, db=session)
        router._embedding_service = embed_svc

        # 运行测试
        results = []
        correct = 0
        total = len(TEST_CASES)

        print("=" * 80)
        print(f"{'#':<3} {'场景':<40} {'预期':<10} {'实际':<15} {'相似度':<8} {'结果'}")
        print("=" * 80)

        for i, (text, expected_category) in enumerate(TEST_CASES, 1):
            # 构建上下文
            ctx = PipelineContext(
                request_id=f"test-{i}",
                client_ip="127.0.0.1",
                stream=False,
                original_messages=[{"role": "user", "content": text}],
                requested_model="chat",
                kwargs={},
                estimated_tokens=100,
                session_id=f"test-session-{i}",
            )

            # 执行路由
            await router.route(ctx)

            # 判断结果（简化：qwen-plus=code/data, kimi-k2.6=creative, 两者都可=general）
            actual_model = ctx.target_model
            confidence = getattr(ctx, "router_confidence", 0)

            # 预期映射
            if expected_category in ["code", "data"]:
                expected_model = "qwen-plus"
            elif expected_category == "creative":
                expected_model = "kimi-k2.6"
            else:
                expected_model = "任意"

            is_correct = (expected_model == "任意") or (actual_model == expected_model)
            if is_correct:
                correct += 1

            status = "✅" if is_correct else "❌"
            display_text = text[:38] + "..." if len(text) > 38 else text
            print(f"{i:<3} {display_text:<40} {expected_category:<10} {actual_model:<15} {confidence:<8.3f} {status}")
            results.append({
                "text": text,
                "expected": expected_category,
                "expected_model": expected_model,
                "actual": actual_model,
                "confidence": confidence,
                "correct": is_correct,
            })

        print("=" * 80)
        print(f"\n准确率: {correct}/{total} = {correct/total*100:.1f}%")

        # 按类别统计
        print("\n按类别统计:")
        categories = {}
        for r in results:
            cat = r["expected"]
            if cat not in categories:
                categories[cat] = {"total": 0, "correct": 0, "confidences": []}
            categories[cat]["total"] += 1
            if r["correct"]:
                categories[cat]["correct"] += 1
            categories[cat]["confidences"].append(r["confidence"])

        for cat, stats in categories.items():
            avg_conf = sum(stats["confidences"]) / len(stats["confidences"])
            print(f"  {cat:<10}: {stats['correct']}/{stats['total']} 准确率, 平均相似度 {avg_conf:.3f}")

        # 误判案例
        print("\n误判案例:")
        for r in results:
            if not r["correct"]:
                print(f"  ❌ {r['text']}")
                print(f"     预期: {r['expected_model']}, 实际: {r['actual']}, 相似度: {r['confidence']:.3f}")

        # 相似度分布
        print("\n相似度分布:")
        confidences = [r["confidence"] for r in results]
        print(f"  最低: {min(confidences):.3f}")
        print(f"  最高: {max(confidences):.3f}")
        print(f"  平均: {sum(confidences)/len(confidences):.3f}")
        low_conf = [r for r in results if r["confidence"] < 0.5]
        print(f"  低置信度(<0.5): {len(low_conf)}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(run_tests())
