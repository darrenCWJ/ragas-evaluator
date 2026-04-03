from ragas.metrics.collections import AgentGoalAccuracyWithReference, AgentGoalAccuracyWithoutReference


def create_scorer_with_reference(llm):
    return AgentGoalAccuracyWithReference(llm=llm)


def create_scorer_without_reference(llm):
    return AgentGoalAccuracyWithoutReference(llm=llm)


async def score_with_reference(scorer, user_input: list, reference: str) -> float:
    result = await scorer.ascore(
        user_input=user_input,
        reference=reference,
    )
    return result.value


async def score_without_reference(scorer, user_input: list) -> float:
    result = await scorer.ascore(
        user_input=user_input,
    )
    return result.value
