from ragas.metrics.collections import ContextEntityRecall


def create_scorer(llm):
    return ContextEntityRecall(llm=llm)


async def score(scorer, reference: str, contexts: list[str]) -> float:
    result = await scorer.ascore(
        reference=reference,
        retrieved_contexts=contexts,
    )
    return result.value
