from ragas.metrics.collections import Faithfulness


def create_scorer(llm):
    return Faithfulness(llm=llm)


async def score(scorer, question: str, answer: str, contexts: list[str]) -> float:
    result = await scorer.ascore(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts,
    )
    return result.value