from ragas.metrics.collections import CHRFScore


def create_scorer():
    return CHRFScore()


async def score(scorer, answer: str, reference: str) -> float:
    result = await scorer.ascore(
        response=answer,
        reference=reference,
    )
    return result.value
