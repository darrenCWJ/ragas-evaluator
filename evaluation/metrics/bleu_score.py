from ragas.metrics.collections import BleuScore


def create_scorer():
    return BleuScore()


async def score(scorer, answer: str, reference: str) -> float:
    result = await scorer.ascore(
        response=answer,
        reference=reference,
    )
    return result.value
