from ragas.metrics.collections import TopicAdherence


def create_scorer(llm, mode="f1"):
    return TopicAdherence(llm=llm, mode=mode)


async def score(scorer, user_input: list, reference_topics: list[str]) -> float:
    result = await scorer.ascore(
        user_input=user_input,
        reference_topics=reference_topics,
    )
    return result.value
