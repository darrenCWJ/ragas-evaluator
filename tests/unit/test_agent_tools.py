"""Agent loop, tool execution modes, and deterministic trace metrics."""

import pytest

from evaluation.metrics.agent_trace import (
    tool_call_accuracy_score,
    tool_call_f1_score,
    trace_stats,
)
from pipeline.tools import _mock_response, build_tool_specs, calculator

CALC_SPEC = {
    "name": "calc",
    "description": "calculator",
    "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}},
}


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_runs_tool_then_answers(self, monkeypatch):
        calls = []

        async def fake_completion(model, messages, params=None, tools=None):
            calls.append(list(messages))
            if len(calls) == 1:
                return {
                    "content": "",
                    "tool_calls": [{"id": "c1", "name": "calc", "arguments": {"expression": "2+2"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }
            return {
                "content": "The answer is 4.",
                "tool_calls": [],
                "usage": {"prompt_tokens": 20, "completion_tokens": 8},
            }

        monkeypatch.setattr("pipeline.agent_loop.chat_completion", fake_completion)
        from pipeline.agent_loop import run_agent

        async def executor(name, args):
            return calculator(args["expression"])

        result = await run_agent("gpt-test", [{"role": "user", "content": "what is 2+2?"}], [CALC_SPEC], executor)

        assert result["answer"] == "The answer is 4."
        assert result["stop_reason"] == "answer"
        assert len(result["steps"]) == 1
        assert result["steps"][0]["tool"] == "calc"
        assert result["steps"][0]["result"] == "4"
        assert result["usage"]["prompt_tokens"] == 30
        # Second LLM call must include the assistant tool-call turn + tool result
        roles = [m["role"] for m in calls[1]]
        assert roles == ["user", "assistant", "tool"]

    @pytest.mark.asyncio
    async def test_max_steps_forces_final_answer(self, monkeypatch):
        async def always_call(model, messages, params=None, tools=None):
            if tools is None:
                return {"content": "Forced answer.", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
            return {
                "content": "",
                "tool_calls": [{"id": "x", "name": "calc", "arguments": {"expression": "1+1"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

        monkeypatch.setattr("pipeline.agent_loop.chat_completion", always_call)
        from pipeline.agent_loop import run_agent

        async def executor(name, args):
            return "2"

        result = await run_agent(
            "gpt-test", [{"role": "user", "content": "loop"}], [CALC_SPEC], executor, max_steps=2
        )
        assert result["stop_reason"] == "max_steps"
        assert result["answer"] == "Forced answer."
        assert len(result["steps"]) == 2

    @pytest.mark.asyncio
    async def test_turns_capture_narrated_thinking(self, monkeypatch):
        responses = iter([
            {
                "content": "I should check the bronze tier first.",
                "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "tiers/bronze.md"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            {
                "content": "Bronze done — moving to silver.",
                "tool_calls": [{"id": "c2", "name": "read_file", "arguments": {"path": "tiers/silver.md"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            {"content": "All tiers designed.", "tool_calls": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        ])

        async def fake_completion(model, messages, params=None, tools=None):
            return next(responses)

        monkeypatch.setattr("pipeline.agent_loop.chat_completion", fake_completion)
        from pipeline.agent_loop import run_agent

        async def executor(name, args):
            return "file contents"

        result = await run_agent("m", [{"role": "user", "content": "build it"}], [CALC_SPEC], executor)

        assert result["answer"] == "All tiers designed."
        # One turn per tool-calling round, with the model's narrated reasoning
        assert [t["thought"] for t in result["turns"]] == [
            "I should check the bronze tier first.",
            "Bronze done — moving to silver.",
        ]
        assert result["turns"][0]["tool_calls"] == ["read_file"]
        # Steps stay flat for tool_call_f1 but link back to their turn
        assert [s["turn"] for s in result["steps"]] == [1, 2]
        assert result["turns"][1]["steps"][0]["arguments"]["path"] == "tiers/silver.md"

    @pytest.mark.asyncio
    async def test_tool_error_is_fed_back_not_raised(self, monkeypatch):
        responses = iter([
            {
                "content": "",
                "tool_calls": [{"id": "c1", "name": "calc", "arguments": {}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            {"content": "done", "tool_calls": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        ])

        async def fake_completion(model, messages, params=None, tools=None):
            return next(responses)

        monkeypatch.setattr("pipeline.agent_loop.chat_completion", fake_completion)
        from pipeline.agent_loop import run_agent

        async def executor(name, args):
            raise RuntimeError("boom")

        result = await run_agent("m", [{"role": "user", "content": "q"}], [CALC_SPEC], executor)
        assert result["steps"][0]["error"] == "boom"
        assert result["answer"] == "done"


class TestCalculator:
    def test_basic_arithmetic(self):
        assert calculator("2 + 3 * 4") == "14"
        assert calculator("(10 - 4) / 3") == "2.0"

    def test_rejects_code(self):
        assert calculator("__import__('os')").startswith("Error")
        assert calculator("max(1,2)").startswith("Error")

    def test_division_by_zero(self):
        assert calculator("1/0") == "Error: division by zero"

    def test_huge_exponent_rejected(self):
        assert calculator("9**999999").startswith("Error")


class TestMockResponses:
    def test_case_match_and_default(self):
        fixtures = {
            "default": "nothing found",
            "cases": [
                {"when": {"city": "Paris"}, "response": "18°C, sunny"},
                {"when": {"city": "London"}, "response": {"temp": 12}},
            ],
        }
        assert _mock_response(fixtures, {"city": "Paris"}) == "18°C, sunny"
        assert _mock_response(fixtures, {"city": "London"}) == '{"temp": 12}'
        assert _mock_response(fixtures, {"city": "Oslo"}) == "nothing found"

    def test_empty_fixtures_return_ok(self):
        assert _mock_response({}, {"x": 1}) == "OK"


class TestBuildToolSpecs:
    def test_builtin_inherits_schema(self):
        rows = [{
            "name": "search",
            "description": "",
            "parameters_json": None,
            "mode": "builtin",
            "builtin_name": "search_documents",
        }]
        specs = build_tool_specs(rows)
        assert specs[0]["parameters"]["required"] == ["query"]
        assert specs[0]["description"]  # falls back to builtin description

    def test_custom_tool_parses_schema(self):
        rows = [{
            "name": "weather",
            "description": "get weather",
            "parameters_json": '{"type": "object", "properties": {"city": {"type": "string"}}}',
            "mode": "mock",
            "builtin_name": None,
        }]
        specs = build_tool_specs(rows)
        assert specs[0]["parameters"]["properties"]["city"]["type"] == "string"


class TestToolCallF1:
    TRACE = [
        {"tool": "search", "arguments": {"query": "refund policy"}, "result": "...", "error": None},
        {"tool": "calc", "arguments": {"expression": "2+2"}, "result": "4", "error": None},
    ]

    def test_perfect_match(self):
        refs = [
            {"name": "search", "arguments": {"query": "refund policy"}},
            {"name": "calc"},
        ]
        assert tool_call_f1_score(self.TRACE, refs) == 1.0

    def test_partial_match(self):
        refs = [{"name": "search", "arguments": {"query": "refund policy"}}, {"name": "send_email"}]
        # 1 matched of 2 calls (precision 0.5) and 2 refs (recall 0.5)
        assert tool_call_f1_score(self.TRACE, refs) == 0.5

    def test_argument_mismatch_does_not_match(self):
        refs = [{"name": "search", "arguments": {"query": "shipping"}}]
        assert tool_call_f1_score(self.TRACE, refs) == 0.0

    def test_bare_string_references(self):
        assert tool_call_f1_score(self.TRACE, ["search", "calc"]) == 1.0

    def test_no_refs_no_calls_is_perfect(self):
        assert tool_call_f1_score([], []) == 1.0

    def test_calls_when_none_expected_is_zero(self):
        assert tool_call_f1_score(self.TRACE, []) == 0.0

    def test_trace_stats(self):
        steps = [
            {"tool": "a", "error": None},
            {"tool": "b", "error": "boom"},
        ]
        stats = trace_stats(steps)
        assert stats == {"agent_steps": 2, "tool_errors": 1, "tool_error_rate": 0.5}


class TestToolCallAccuracy:
    TRACE = [
        {"tool": "search", "arguments": {"query": "refund policy"}, "result": "...", "error": None},
        {"tool": "calc", "arguments": {"expression": "2+2"}, "result": "4", "error": None},
    ]

    def test_perfect_ordered_match(self):
        refs = [{"name": "search", "arguments": {"query": "refund policy"}}, {"name": "calc"}]
        assert tool_call_accuracy_score(self.TRACE, refs) == 1.0

    def test_order_matters_unlike_f1(self):
        # Same calls, reversed reference order: f1 forgives, accuracy doesn't.
        refs = [{"name": "calc"}, {"name": "search", "arguments": {"query": "refund policy"}}]
        assert tool_call_f1_score(self.TRACE, refs) == 1.0
        assert tool_call_accuracy_score(self.TRACE, refs) == 0.0

    def test_extra_calls_penalized(self):
        refs = [{"name": "search", "arguments": {"query": "refund policy"}}]
        # 1 aligned match / max(1 ref, 2 calls)
        assert tool_call_accuracy_score(self.TRACE, refs) == 0.5

    def test_no_refs_no_calls_is_perfect(self):
        assert tool_call_accuracy_score([], []) == 1.0

    def test_calls_when_none_expected_is_zero(self):
        assert tool_call_accuracy_score(self.TRACE, []) == 0.0


class TestJudgeAgentMetrics:
    @pytest.mark.asyncio
    async def test_agent_goal_accuracy_parses_verdict(self, monkeypatch):
        async def fake_completion(model, messages, params=None, tools=None):
            return {"content": '{"achieved": true, "reasoning": "outcome matches"}', "usage": {}}

        monkeypatch.setattr(
            "evaluation.metrics.agent_goal_accuracy.chat_completion", fake_completion
        )
        from evaluation.metrics.agent_goal_accuracy import agent_goal_accuracy_score

        score = await agent_goal_accuracy_score(
            "Book a table for two", "Booked at 7pm.", "A reservation is made.",
            [{"tool": "book_table", "arguments": {"people": 2}, "error": None}],
        )
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_agent_goal_accuracy_not_achieved(self, monkeypatch):
        async def fake_completion(model, messages, params=None, tools=None):
            return {"content": '{"achieved": false, "reasoning": "no booking made"}', "usage": {}}

        monkeypatch.setattr(
            "evaluation.metrics.agent_goal_accuracy.chat_completion", fake_completion
        )
        from evaluation.metrics.agent_goal_accuracy import agent_goal_accuracy_score

        assert await agent_goal_accuracy_score("goal", "answer", "ref", []) == 0.0

    @pytest.mark.asyncio
    async def test_topic_adherence_scores_verdicts(self, monkeypatch):
        replies = iter([
            '{"verdict": "adherent", "reasoning": "on topic"}',
            '{"verdict": "partial", "reasoning": "some drift"}',
            '{"verdict": "off_topic", "reasoning": "wrong domain"}',
        ])

        async def fake_completion(model, messages, params=None, tools=None):
            return {"content": next(replies), "usage": {}}

        monkeypatch.setattr(
            "evaluation.metrics.topic_adherence.chat_completion", fake_completion
        )
        from evaluation.metrics.topic_adherence import topic_adherence_score

        assert await topic_adherence_score("q", "a", ["billing"]) == 1.0
        assert await topic_adherence_score("q", "a", ["billing"]) == 0.5
        assert await topic_adherence_score("q", "a", ["billing"]) == 0.0
