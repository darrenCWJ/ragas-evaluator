from ragas.metrics import RubricsScore


DEFAULT_RUBRICS = {
    "score1_description": "The response is completely incorrect or irrelevant.",
    "score2_description": "The response is partially correct but has significant errors.",
    "score3_description": "The response is mostly correct but could be improved.",
    "score4_description": "The response is correct and well-structured.",
    "score5_description": "The response is excellent, accurate, and comprehensive.",
}


def create_scorer(llm, rubrics=None):
    return RubricsScore(llm=llm, rubrics=rubrics or DEFAULT_RUBRICS)


async def score(scorer, question: str, answer: str, contexts: list[str] = None) -> float:
    from ragas.dataset_schema import SingleTurnSample

    sample = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts or [],
    )
    result = await scorer.single_turn_ascore(sample)
    # Normalize from 1-5 to 0-1
    return (result - 1) / 4
