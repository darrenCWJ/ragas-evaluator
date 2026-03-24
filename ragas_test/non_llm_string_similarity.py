from ragas.metrics.collections import NonLLMStringSimilarity, DistanceMeasure


def create_scorer(distance_measure=DistanceMeasure.LEVENSHTEIN):
    return NonLLMStringSimilarity(distance_measure=distance_measure)


async def score(scorer, answer: str, reference: str) -> float:
    result = await scorer.ascore(
        response=answer,
        reference=reference,
    )
    return result.value
