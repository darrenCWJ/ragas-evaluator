from ragas.metrics.collections import NoiseSensitivity


def create_scorer(llm):
    return NoiseSensitivity(llm=llm)


async def score(scorer, question: str, answer: str, reference: str, contexts: list[str]) -> float:
    result = await scorer.ascore(
        user_input=question,
        response=answer,
        reference=reference,
        retrieved_contexts=contexts,
    )
    return result.value
