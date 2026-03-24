import asyncio
import json
import os
import sys

from http.server import BaseHTTPRequestHandler

# Add project root to path so ragas_test package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AsyncOpenAI
from ragas.llms import llm_factory
from ragas.embeddings.base import embedding_factory

from ragas_test import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
    context_entities_recall,
    noise_sensitivity,
    factual_correctness,
    semantic_similarity,
    non_llm_string_similarity,
    bleu_score,
    rouge_score,
    chrf_score,
    exact_match,
    string_presence,
    summarization_score,
    aspect_critic,
    rubrics_score,
    answer_accuracy,
    context_relevance,
    response_groundedness,
)

ALL_METRICS = [
    "faithfulness", "answer_relevancy", "context_precision",
    "context_recall", "context_entities_recall", "noise_sensitivity",
    "factual_correctness", "semantic_similarity", "non_llm_string_similarity",
    "bleu_score", "rouge_score", "chrf_score", "exact_match", "string_presence",
    "summarization_score", "aspect_critic", "rubrics_score",
    "answer_accuracy", "context_relevance", "response_groundedness",
]


def _setup_scorers(selected):
    client = AsyncOpenAI()
    llm = llm_factory("gpt-4o-mini", client=client, max_tokens=16384)
    embeddings = embedding_factory("openai", model="text-embedding-3-small", client=client)

    scorers = {}
    for m in selected:
        if m == "faithfulness":
            scorers[m] = faithfulness.create_scorer(llm)
        elif m == "answer_relevancy":
            scorers[m] = answer_relevancy.create_scorer(llm, embeddings)
        elif m == "context_precision":
            scorers[m] = context_precision.create_scorer(llm)
        elif m == "context_recall":
            scorers[m] = context_recall.create_scorer(llm)
        elif m == "context_entities_recall":
            scorers[m] = context_entities_recall.create_scorer(llm)
        elif m == "noise_sensitivity":
            scorers[m] = noise_sensitivity.create_scorer(llm)
        elif m == "factual_correctness":
            scorers[m] = factual_correctness.create_scorer(llm)
        elif m == "semantic_similarity":
            scorers[m] = semantic_similarity.create_scorer(embeddings)
        elif m == "non_llm_string_similarity":
            scorers[m] = non_llm_string_similarity.create_scorer()
        elif m == "bleu_score":
            scorers[m] = bleu_score.create_scorer()
        elif m == "rouge_score":
            scorers[m] = rouge_score.create_scorer()
        elif m == "chrf_score":
            scorers[m] = chrf_score.create_scorer()
        elif m == "exact_match":
            scorers[m] = exact_match.create_scorer()
        elif m == "string_presence":
            scorers[m] = string_presence.create_scorer()
        elif m == "summarization_score":
            scorers[m] = summarization_score.create_scorer(llm)
        elif m == "aspect_critic":
            scorers[m] = aspect_critic.create_scorer(llm)
        elif m == "rubrics_score":
            scorers[m] = rubrics_score.create_scorer(llm)
        elif m == "answer_accuracy":
            scorers[m] = answer_accuracy.create_scorer(llm)
        elif m == "context_relevance":
            scorers[m] = context_relevance.create_scorer(llm)
        elif m == "response_groundedness":
            scorers[m] = response_groundedness.create_scorer(llm)
    return scorers


async def _evaluate(scorers, question, answer, contexts):
    results = {}
    for name, scorer in scorers.items():
        try:
            if name == "faithfulness":
                results[name] = await faithfulness.score(scorer, question, answer, contexts)
            elif name == "answer_relevancy":
                results[name] = await answer_relevancy.score(scorer, question, answer)
            elif name == "context_precision":
                results[name] = await context_precision.score(scorer, question, answer, contexts)
            elif name == "context_recall":
                results[name] = await context_recall.score(scorer, question, answer, contexts)
            elif name == "context_entities_recall":
                results[name] = await context_entities_recall.score(scorer, answer, contexts)
            elif name == "noise_sensitivity":
                results[name] = await noise_sensitivity.score(scorer, question, answer, answer, contexts)
            elif name == "factual_correctness":
                results[name] = await factual_correctness.score(scorer, answer, answer)
            elif name == "semantic_similarity":
                results[name] = await semantic_similarity.score(scorer, answer, answer)
            elif name == "non_llm_string_similarity":
                results[name] = await non_llm_string_similarity.score(scorer, answer, answer)
            elif name == "bleu_score":
                results[name] = await bleu_score.score(scorer, answer, answer)
            elif name == "rouge_score":
                results[name] = await rouge_score.score(scorer, answer, answer)
            elif name == "chrf_score":
                results[name] = await chrf_score.score(scorer, answer, answer)
            elif name == "exact_match":
                results[name] = await exact_match.score(scorer, answer, answer)
            elif name == "string_presence":
                results[name] = await string_presence.score(scorer, answer, answer)
            elif name == "summarization_score":
                results[name] = await summarization_score.score(scorer, answer, contexts)
            elif name == "aspect_critic":
                results[name] = await aspect_critic.score(scorer, question, answer, contexts)
            elif name == "rubrics_score":
                results[name] = await rubrics_score.score(scorer, question, answer, contexts)
            elif name == "answer_accuracy":
                results[name] = await answer_accuracy.score(scorer, question, answer, answer)
            elif name == "context_relevance":
                results[name] = await context_relevance.score(scorer, question, contexts)
            elif name == "response_groundedness":
                results[name] = await response_groundedness.score(scorer, answer, contexts)
        except Exception as e:
            results[name] = None
    return results


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
            question = data["question"]
            answer = data["answer"]
            contexts = data["retrieve_context"]
            metrics = data.get("metrics", ALL_METRICS)

            # Filter to valid metrics
            selected = [m for m in metrics if m in ALL_METRICS]
            if not selected:
                self._send_json(400, {"error": "No valid metrics selected"})
                return

            scorers = _setup_scorers(selected)
            results = asyncio.run(_evaluate(scorers, question, answer, contexts))

            self._send_json(200, {"question": question, "answer": answer, **results})

        except KeyError as e:
            self._send_json(400, {"error": f"Missing field: {e}"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def do_GET(self):
        self._send_json(200, {"metrics": ALL_METRICS})

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
