from ragas.metrics.collections import DataCompyScore


def create_scorer(mode="row", metric="f1"):
    return DataCompyScore(mode=mode, metric=metric)


async def score(scorer, response_data: str, reference_data: str) -> float:
    result = await scorer.ascore(
        response=response_data,
        reference=reference_data,
    )
    return result.value
