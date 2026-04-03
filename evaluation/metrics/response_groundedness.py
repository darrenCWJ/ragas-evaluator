from ragas.metrics.collections import ResponseGroundedness


def create_scorer(llm):
    return ResponseGroundedness(llm=llm)


async def score(scorer, answer: str, contexts: list[str]) -> float:
    result = await scorer.ascore(
        response=answer,
        retrieved_contexts=contexts,
    )
    return result.value
