from ragas.metrics.collections import AnswerRelevancy


def create_scorer(llm, embeddings):
    return AnswerRelevancy(llm=llm, embeddings=embeddings)


async def score(scorer, question: str, answer: str, **kwargs) -> float:
    result = await scorer.ascore(
        user_input=question,
        response=answer,
    )
    return result.value