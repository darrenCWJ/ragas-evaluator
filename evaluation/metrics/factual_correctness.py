from ragas.metrics.collections import FactualCorrectness


def create_scorer(llm):
    return FactualCorrectness(llm=llm, mode="f1")


async def score(scorer, answer: str, reference: str) -> float:
    result = await scorer.ascore(
        response=answer,
        reference=reference,
    )
    return result.value
