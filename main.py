import argparse
import asyncio
import csv
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from ragas.llms import llm_factory
from ragas.embeddings.base import embedding_factory

from ragas_test import faithfulness, answer_relevancy, context_precision

load_dotenv()

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

CONTEXT_SEPARATOR = "||"


def setup_scorers():
    client = AsyncOpenAI()
    llm = llm_factory("gpt-4o-mini", client=client, max_tokens=16384)
    embeddings = embedding_factory("openai", model="text-embedding-3-small", client=client)

    return {
        "faithfulness": faithfulness.create_scorer(llm),
        "answer_relevancy": answer_relevancy.create_scorer(llm, embeddings),
        "context_precision": context_precision.create_scorer(llm),
    }


async def evaluate_row(scorers, question: str, answer: str, contexts: list[str]) -> dict:
    return {
        "faithfulness": await faithfulness.score(
            scorers["faithfulness"], question, answer, contexts
        ),
        "answer_relevancy": await answer_relevancy.score(
            scorers["answer_relevancy"], question, answer
        ),
        "context_precision": await context_precision.score(
            scorers["context_precision"], question, answer, contexts
        ),
    }


def parse_contexts(raw: str) -> list[str]:
    return [c.strip() for c in raw.split(CONTEXT_SEPARATOR) if c.strip()]


async def process_csv(input_file: str):
    input_path = INPUT_DIR / input_file
    if not input_path.exists():
        print(f"Error: {input_path} not found")
        return

    scorers = setup_scorers()
    rows = []

    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    results = []
    for i, row in enumerate(rows):
        question = row["Question"]
        answer = row["Answer"]
        contexts = parse_contexts(row["Retrieve Context"])

        print(f"Evaluating row {i + 1}/{len(rows)}: {question[:50]}...")
        scores = await evaluate_row(scorers, question, answer, contexts)
        results.append({
            "Question": question,
            "Answer": answer,
            "Retrieve Context": row["Retrieve Context"],
            **scores,
        })

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = Path(input_file).stem
    output_path = OUTPUT_DIR / f"{stem}_results_{timestamp}.csv"

    fieldnames = ["Question", "Answer", "Retrieve Context", "faithfulness", "answer_relevancy", "context_precision"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"Results saved to {output_path}")


def run_api(host: str = "0.0.0.0", port: int = 8000):
    try:
        import uvicorn
        from fastapi import FastAPI
        from pydantic import BaseModel
    except ImportError:
        print("API mode requires fastapi and uvicorn.")
        print("Install with: pip install fastapi uvicorn")
        return

    app = FastAPI(title="Ragas Evaluator")
    scorers = setup_scorers()

    class EvalRequest(BaseModel):
        question: str
        answer: str
        retrieve_context: list[str]

    class EvalResponse(BaseModel):
        question: str
        answer: str
        faithfulness: float
        answer_relevancy: float
        context_precision: float

    @app.post("/evaluate", response_model=EvalResponse)
    async def evaluate(req: EvalRequest):
        scores = await evaluate_row(scorers, req.question, req.answer, req.retrieve_context)
        return EvalResponse(
            question=req.question,
            answer=req.answer,
            **scores,
        )

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ragas Evaluation Tool")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    csv_parser = subparsers.add_parser("csv", help="Evaluate from a CSV file in input/")
    csv_parser.add_argument("file", help="CSV filename in the input/ directory")

    api_parser = subparsers.add_parser("api", help="Run as a REST API server")
    api_parser.add_argument("--host", default="0.0.0.0")
    api_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()

    if args.mode == "csv":
        asyncio.run(process_csv(args.file))
    elif args.mode == "api":
        run_api(args.host, args.port)
