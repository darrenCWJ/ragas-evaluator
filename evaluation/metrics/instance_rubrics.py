from ragas.metrics import InstanceRubrics


def create_scorer(llm):
    return InstanceRubrics(llm=llm)


async def score(scorer, question: str, answer: str, rubrics: dict = None, contexts: list[str] = None) -> float:
    from ragas.dataset_schema import SingleTurnSample

    sample = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts or [],
        rubrics=rubrics or {},
    )
    result = await scorer.single_turn_ascore(sample)
    return result
