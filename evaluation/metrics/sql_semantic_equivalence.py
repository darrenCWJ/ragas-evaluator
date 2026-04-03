from ragas.metrics.collections import SQLSemanticEquivalence


def create_scorer(llm):
    return SQLSemanticEquivalence(llm=llm)


async def score(scorer, response_sql: str, reference_sql: str, schema_contexts: list[str] = None) -> float:
    result = await scorer.ascore(
        response=response_sql,
        reference=reference_sql,
        reference_contexts=schema_contexts or [],
    )
    return result.value
