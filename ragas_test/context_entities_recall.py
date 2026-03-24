from ragas.metrics.collections import ContextEntityRecall


def create_scorer(llm):
    return ContextEntityRecall(llm=llm)


async def score(scorer, answer: str, contexts: list[str]) -> float:
    result = await scorer.ascore(
        reference=answer,
        retrieved_contexts=contexts,
    )
    return result.value
