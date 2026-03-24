from ragas.metrics.collections import ToolCallAccuracy


def create_scorer(strict_order=True):
    return ToolCallAccuracy(strict_order=strict_order)


async def score(scorer, user_input: list, reference_tool_calls: list) -> float:
    result = await scorer.ascore(
        user_input=user_input,
        reference_tool_calls=reference_tool_calls,
    )
    return result.value
