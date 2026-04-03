from ragas.metrics.collections import ExactMatch


def create_scorer():
    return ExactMatch()


async def score(scorer, answer: str, reference: str) -> float:
    result = await scorer.ascore(
        response=answer,
        reference=reference,
    )
    return result.value
