from ragas.metrics.collections import SemanticSimilarity


def create_scorer(embeddings):
    return SemanticSimilarity(embeddings=embeddings)


async def score(scorer, answer: str, reference: str) -> float:
    result = await scorer.ascore(
        response=answer,
        reference=reference,
    )
    return result.value
