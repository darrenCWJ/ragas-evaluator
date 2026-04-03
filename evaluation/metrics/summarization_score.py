from ragas.metrics.collections import SummaryScore


def create_scorer(llm):
    return SummaryScore(llm=llm)


async def score(scorer, answer: str, contexts: list[str]) -> float:
    result = await scorer.ascore(
        response=answer,
        reference_contexts=contexts,
    )
    return result.value
