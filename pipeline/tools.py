"""Tool registry: specs and execution for agentic experiments.

Three execution modes per tool definition:

- ``mock``      — fixture responses matched against the call arguments. The
                  default and cheapest: evaluation usually only needs to check
                  *that* the right call was made with the right arguments.
- ``simulated`` — an LLM plays the tool and invents a plausible response.
- ``builtin``   — real, allowlisted implementations shipped with Tribunal:
                  ``search_documents``, ``read_file``, ``calculator``.

No arbitrary HTTP or code execution — keep it that way.
"""

from __future__ import annotations

import ast
import json
import logging
import operator

logger = logging.getLogger(__name__)

VALID_TOOL_MODES = {"mock", "simulated", "builtin"}

# Bot connector types whose models are routed through pipeline.llm and can
# therefore run the tool-calling agent loop.
AGENT_CAPABLE_CONNECTORS = {"openai", "claude", "gemini"}

BUILTIN_TOOLS = {
    "search_documents": {
        "description": "Search the project's uploaded documents for a query string. Returns the most relevant passages.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
    },
    "read_file": {
        "description": "Read a file by name. Returns its full text content.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File name or path to read"}},
            "required": ["path"],
        },
    },
    "calculator": {
        "description": "Evaluate an arithmetic expression (numbers, + - * / // % **, parentheses).",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "Arithmetic expression"}},
            "required": ["expression"],
        },
    },
}


def build_tool_specs(tool_rows: list[dict]) -> list[dict]:
    """Tool definition rows → canonical specs for chat_completion(tools=...)."""
    specs = []
    for row in tool_rows:
        if row["mode"] == "builtin" and row.get("builtin_name") in BUILTIN_TOOLS:
            builtin = BUILTIN_TOOLS[row["builtin_name"]]
            specs.append({
                "name": row["name"],
                "description": row["description"] or builtin["description"],
                "parameters": builtin["parameters"],
            })
        else:
            try:
                parameters = json.loads(row["parameters_json"]) if row.get("parameters_json") else {}
            except ValueError:
                parameters = {}
            if not parameters:
                parameters = {"type": "object", "properties": {}}
            specs.append({
                "name": row["name"],
                "description": row["description"],
                "parameters": parameters,
            })
    return specs


# ---------------------------------------------------------------------------
# Builtin implementations
# ---------------------------------------------------------------------------

_CALC_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_CALC_MAX_POW = 1000


def _calc_eval(node: ast.AST):
    if isinstance(node, ast.Expression):
        return _calc_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
        left, right = _calc_eval(node.left), _calc_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _CALC_MAX_POW:
            raise ValueError("exponent too large")
        return _CALC_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_calc_eval(node.operand))
    raise ValueError(f"unsupported expression element: {ast.dump(node)[:60]}")


def calculator(expression: str) -> str:
    """Safe arithmetic evaluation (AST whitelist, no names/calls)."""
    try:
        tree = ast.parse(expression, mode="eval")
        return str(_calc_eval(tree))
    except ZeroDivisionError:
        return "Error: division by zero"
    except (ValueError, SyntaxError) as e:
        return f"Error: invalid expression ({e})"


_SEARCH_SNIPPET_CHARS = 600
_SEARCH_MAX_RESULTS = 3


def search_documents(conn, project_id: int, query: str) -> str:
    """Keyword search over the project's document contents."""
    terms = [t for t in query.lower().split() if len(t) >= 3][:6]
    if not terms:
        return "No usable search terms in query."
    rows = conn.execute(
        "SELECT filename, content FROM documents WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    scored: list[tuple[int, str, str]] = []
    for row in rows:
        content_lower = row["content"].lower()
        score = sum(content_lower.count(t) for t in terms)
        if score > 0:
            # Snippet around the first matching term
            first_pos = min(
                (content_lower.find(t) for t in terms if t in content_lower), default=0
            )
            start = max(0, first_pos - 100)
            snippet = row["content"][start : start + _SEARCH_SNIPPET_CHARS]
            scored.append((score, row["filename"], snippet))
    if not scored:
        return f"No documents matched '{query}'."
    scored.sort(reverse=True)
    return "\n\n".join(
        f"[{filename}]\n{snippet}" for _, filename, snippet in scored[:_SEARCH_MAX_RESULTS]
    )


def read_file(conn, project_id: int, path: str, extra_files: dict[str, str] | None = None) -> str:
    """Read a project document (or an extra in-memory file, e.g. skill references)."""
    name = path.strip().lstrip("./")
    if extra_files:
        for file_path, content in extra_files.items():
            if file_path == name or file_path.endswith("/" + name):
                return content
    row = conn.execute(
        "SELECT content FROM documents WHERE project_id = ? AND filename = ?",
        (project_id, name),
    ).fetchone()
    if row is None:
        available = [r["filename"] for r in conn.execute(
            "SELECT filename FROM documents WHERE project_id = ? LIMIT 20", (project_id,)
        ).fetchall()]
        if extra_files:
            available = list(extra_files) + available
        return f"File '{name}' not found. Available files: {', '.join(available) or '(none)'}"
    return row["content"]


# ---------------------------------------------------------------------------
# Mock + simulated execution
# ---------------------------------------------------------------------------


def _mock_response(fixtures: dict, arguments: dict) -> str:
    """Resolve a mock tool response: first case whose `when` pairs all match."""
    for case in fixtures.get("cases", []):
        when = case.get("when") or {}
        if all(str(arguments.get(k)) == str(v) for k, v in when.items()):
            response = case.get("response", "")
            return response if isinstance(response, str) else json.dumps(response)
    default = fixtures.get("default", "OK")
    return default if isinstance(default, str) else json.dumps(default)


async def _simulated_response(tool_name: str, description: str, arguments: dict) -> str:
    from config import DEFAULT_EVAL_MODEL
    from pipeline.llm import chat_completion

    prompt = (
        f"You are simulating the tool '{tool_name}' ({description}). "
        f"It was called with arguments: {json.dumps(arguments)}. "
        "Return a realistic, concise tool output ONLY — no commentary, no markdown fences."
    )
    response = await chat_completion(
        DEFAULT_EVAL_MODEL,
        [{"role": "user", "content": prompt}],
        {"temperature": 0.3, "max_tokens": 600},
    )
    return response["content"]


def make_executor(
    tool_rows: list[dict],
    conn,
    project_id: int,
    extra_files: dict[str, str] | None = None,
):
    """Build the async executor used by the agent loop for these tools."""
    by_name = {row["name"]: row for row in tool_rows}

    async def execute(name: str, arguments: dict) -> str:
        row = by_name.get(name)
        if row is None:
            return f"Error: unknown tool '{name}'"
        mode = row["mode"]
        if mode == "mock":
            try:
                fixtures = json.loads(row["fixtures_json"]) if row.get("fixtures_json") else {}
            except ValueError:
                fixtures = {}
            return _mock_response(fixtures, arguments)
        if mode == "simulated":
            return await _simulated_response(name, row["description"], arguments)
        if mode == "builtin":
            builtin = row.get("builtin_name")
            if builtin == "calculator":
                return calculator(str(arguments.get("expression", "")))
            if builtin == "search_documents":
                return search_documents(conn, project_id, str(arguments.get("query", "")))
            if builtin == "read_file":
                return read_file(conn, project_id, str(arguments.get("path", "")), extra_files)
            return f"Error: unknown builtin '{builtin}'"
        return f"Error: unknown tool mode '{mode}'"

    return execute
