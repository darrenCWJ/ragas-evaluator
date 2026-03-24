from ragas.metrics.collections import ToolCallF1


def create_scorer():
    return ToolCallF1()


async def score(scorer, user_input: list, reference_tool_calls: list) -> float:
    result = await scorer.ascore(
        user_input=user_input,
        reference_tool_calls=reference_tool_calls,
    )
    return result.value
