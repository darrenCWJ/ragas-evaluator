from ragas.metrics.collections import AnswerAccuracy


def create_scorer(llm):
    return AnswerAccuracy(llm=llm)


async def score(scorer, question: str, answer: str, reference: str) -> float:
    result = await scorer.ascore(
        user_input=question,
        response=answer,
        reference=reference,
    )
    return result.value
