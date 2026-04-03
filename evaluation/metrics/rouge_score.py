from ragas.metrics.collections import RougeScore


def create_scorer(rouge_type="rougeL", mode="fmeasure"):
    return RougeScore(rouge_type=rouge_type, mode=mode)


async def score(scorer, answer: str, reference: str) -> float:
    result = await scorer.ascore(
        response=answer,
        reference=reference,
    )
    return result.value
