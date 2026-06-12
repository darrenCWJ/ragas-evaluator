"""Interactive skill dry-runs — an agent loop that pauses for real user input.

The playground's one-shot dry run answers the model's ask_user calls with
scripted replies or an LLM user-simulator. In interactive mode the loop
SUSPENDS instead: when the model asks a question and no scripted reply
remains, the session state is parked in memory and the question is returned
to the UI. POST /continue feeds the human's answer back and the loop resumes
exactly where it stopped. Nothing is persisted to the database.
"""

import asyncio
import logging
import time
import uuid

from pipeline.llm import chat_completion

logger = logging.getLogger(__name__)

_MAX_ROUNDS = 16
_SESSION_TTL_SECONDS = 30 * 60
_MAX_SESSIONS = 50

_sessions: dict[str, dict] = {}


def _evict_stale() -> None:
    now = time.monotonic()
    expired = [
        rid for rid, s in _sessions.items() if now - s["touched"] > _SESSION_TTL_SECONDS
    ]
    for rid in expired:
        _sessions.pop(rid, None)
    # Hard cap as a backstop — drop the least-recently-touched sessions.
    while len(_sessions) > _MAX_SESSIONS:
        oldest = min(_sessions, key=lambda rid: _sessions[rid]["touched"])
        _sessions.pop(oldest, None)


def _build_tools(skill_files: dict[str, str]) -> list[dict]:
    tools: list[dict] = [{
        "name": "ask_user",
        "description": "Ask the user a clarifying question and receive their reply.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "Question for the user"}},
            "required": ["question"],
        },
    }]
    if skill_files:
        tools.append({
            "name": "read_file",
            "description": (
                "Read one of the skill's reference files by path. Available: "
                + ", ".join(sorted(skill_files))
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path to read"}},
                "required": ["path"],
            },
        })
    return tools


def start_session(
    project_id: int,
    skill_content: str,
    skill_files: dict[str, str],
    stages: list[dict],
    model: str,
    prompt: str,
    scripted: list[str],
) -> str:
    """Create an interactive dry-run session and return its run id."""
    _evict_stale()
    run_id = uuid.uuid4().hex
    conversation: list[dict] = []
    if skill_content:
        conversation.append({"role": "system", "content": skill_content})
    conversation.append({"role": "user", "content": prompt})
    _sessions[run_id] = {
        "project_id": project_id,
        "model": model,
        "conversation": conversation,
        "tools": _build_tools(skill_files),
        "skill_files": skill_files,
        "stages": stages,
        "scripted": list(scripted),
        "queue": [],           # unexecuted tool calls of the current round
        "awaiting": None,      # the ask_user call we paused on, if any
        "turns": [],
        "exchanges": 0,
        "rounds": 0,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        "status": "running",
        "answer": "",
        "started": time.monotonic(),
        "touched": time.monotonic(),
        "lock": asyncio.Lock(),
    }
    return run_id


def get_session(run_id: str, project_id: int) -> dict | None:
    session = _sessions.get(run_id)
    if session is None or session["project_id"] != project_id:
        return None
    return session


def _record_step(session: dict, tool: str, arguments: dict, result: str, *, from_user: bool = False) -> None:
    step = {
        "tool": tool,
        "arguments": arguments,
        "result": str(result)[:4000],
        "error": None,
        "from_user": from_user,
    }
    if session["turns"]:
        session["turns"][-1]["steps"].append(step)


def _read_file(session: dict, path: str) -> str:
    path = path.strip().lstrip("./")
    for file_path, content in session["skill_files"].items():
        if file_path == path or file_path.endswith("/" + path):
            return content
    available = ", ".join(sorted(session["skill_files"])) or "(none)"
    return f"File '{path}' not found. Available: {available}"


def _append_tool_result(session: dict, tc: dict, result: str) -> None:
    session["conversation"].append({
        "role": "tool",
        "tool_call_id": tc["id"],
        "name": tc["name"],
        "content": str(result)[:8000],
    })


async def advance(session: dict) -> None:
    """Run the loop until it completes or pauses on a question for the user."""
    session["touched"] = time.monotonic()
    while True:
        # Drain the current round's unexecuted tool calls first.
        while session["queue"]:
            tc = session["queue"][0]
            if tc["name"] == "ask_user":
                question = str(tc.get("arguments", {}).get("question", ""))
                if session["scripted"]:
                    reply = session["scripted"].pop(0)
                    session["exchanges"] += 1
                    _record_step(session, "ask_user", {"question": question}, reply, from_user=True)
                    _append_tool_result(session, tc, reply)
                else:
                    # Pause — the UI shows this question and /continue resumes.
                    session["awaiting"] = tc
                    session["queue"].pop(0)
                    session["status"] = "awaiting_input"
                    return
            elif tc["name"] == "read_file":
                result = _read_file(session, str(tc.get("arguments", {}).get("path", "")))
                _record_step(session, "read_file", tc.get("arguments", {}), result)
                _append_tool_result(session, tc, result)
            else:
                result = f"Error: unknown tool '{tc['name']}'"
                _record_step(session, tc["name"], tc.get("arguments", {}), result)
                _append_tool_result(session, tc, result)
            session["queue"].pop(0)

        # Round budget: force a final answer without tools.
        force_answer = session["rounds"] >= _MAX_ROUNDS
        if force_answer:
            session["conversation"].append({
                "role": "user",
                "content": "Tool budget exhausted. Answer now using the information you already have.",
            })

        t0 = time.monotonic()
        response = await chat_completion(
            session["model"],
            session["conversation"],
            {"max_tokens": 4096},
            tools=None if force_answer else session["tools"],
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        session["rounds"] += 1
        usage = response.get("usage") or {}
        session["usage"]["prompt_tokens"] += usage.get("prompt_tokens", 0)
        session["usage"]["completion_tokens"] += usage.get("completion_tokens", 0)

        tool_calls = response.get("tool_calls") or []
        if force_answer or not tool_calls:
            session["answer"] = response.get("content", "")
            session["status"] = "completed"
            return

        session["turns"].append({
            "thought": (response.get("content") or "").strip(),
            "tool_calls": [tc["name"] for tc in tool_calls],
            "latency_ms": latency_ms,
            "steps": [],
        })
        session["conversation"].append({
            "role": "assistant",
            "content": response.get("content") or None,
            "tool_calls": tool_calls,
        })
        session["queue"] = list(tool_calls)


async def resume_with_answer(session: dict, answer: str) -> None:
    """Feed the human's reply to the paused ask_user call and keep going."""
    tc = session["awaiting"]
    if tc is None:
        raise ValueError("Session is not waiting for input")
    session["awaiting"] = None
    session["status"] = "running"
    session["exchanges"] += 1
    question = str(tc.get("arguments", {}).get("question", ""))
    _record_step(session, "ask_user", {"question": question}, answer, from_user=True)
    _append_tool_result(session, tc, answer)
    await advance(session)


def session_payload(run_id: str, session: dict, stage_metrics_fn) -> dict:
    """Serializable snapshot of the run for the UI (full transcript each time)."""
    files_read = [
        str(step["arguments"].get("path", ""))
        for turn in session["turns"]
        for step in turn["steps"]
        if step["tool"] == "read_file"
    ]
    awaiting = session["awaiting"]
    stage_scores = None
    if session["status"] == "completed" and session["stages"]:
        stage_scores = stage_metrics_fn(session["stages"], files_read)
    return {
        "run_id": run_id,
        "status": session["status"],
        "question": (
            str(awaiting.get("arguments", {}).get("question", "")) if awaiting else None
        ),
        "answer": session["answer"],
        "turns": [
            {
                "thought": turn["thought"],
                "tool_calls": turn["tool_calls"],
                "latency_ms": turn["latency_ms"],
                "steps": [
                    {
                        "tool": s["tool"],
                        "arguments": s["arguments"],
                        "result": s["result"][:800],
                        "error": s["error"],
                        "from_user": s.get("from_user", False),
                    }
                    for s in turn["steps"]
                ],
            }
            for turn in session["turns"]
        ],
        "files_read": files_read,
        "user_exchanges": session["exchanges"],
        "stage_scores": stage_scores,
        "tokens_in": session["usage"]["prompt_tokens"],
        "tokens_out": session["usage"]["completion_tokens"],
        "latency_ms": int((time.monotonic() - session["started"]) * 1000),
    }


def drop_session(run_id: str) -> None:
    _sessions.pop(run_id, None)
