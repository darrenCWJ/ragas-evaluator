from ragas.metrics.collections import StringPresence


def create_scorer():
    return StringPresence()


async def score(scorer, answer: str, reference: str) -> float:
    result = await scorer.ascore(
        response=answer,
        reference=reference,
    )
    return result.value
