from ragas.metrics.collections import ContextPrecision


def create_scorer(llm):
    return ContextPrecision(llm=llm)


async def score(scorer, question: str, answer: str, contexts: list[str]) -> float:
    result = await scorer.ascore(
        user_input=question,
        reference=answer,
        retrieved_contexts=contexts,
    )
    return result.value