from ragas.metrics.collections import ContextRelevance


def create_scorer(llm):
    return ContextRelevance(llm=llm)


async def score(scorer, question: str, contexts: list[str]) -> float:
    result = await scorer.ascore(
        user_input=question,
        retrieved_contexts=contexts,
    )
    return result.value
