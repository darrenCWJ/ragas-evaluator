"""Unit tests for multi-turn conversation support."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from evaluation.metrics import conversation_retention
from pipeline.bot_connectors.base import history_as_transcript

pytestmark = pytest.mark.unit


class TestHistoryTranscript:
    def test_renders_roles(self):
        history = [
            {"role": "user", "content": "I have the Pro plan."},
            {"role": "assistant", "content": "Noted!"},
        ]
        out = history_as_transcript(history)
        assert out == "User: I have the Pro plan.\nAssistant: Noted!"

    def test_empty(self):
        assert history_as_transcript(None) == ""
        assert history_as_transcript([]) == ""


class TestConversationRetention:
    TRANSCRIPT = [
        {"role": "user", "content": "I'm on the Pro plan, billed annually."},
        {"role": "assistant", "content": "Got it — Pro plan, annual billing."},
    ]

    async def test_single_turn_returns_none(self):
        assert await conversation_retention.score(None, "q", "a", {}) is None
        assert await conversation_retention.score(None, "q", "a", None) is None

    @pytest.mark.parametrize(
        ("verdict", "expected"),
        [("retained", 1.0), ("partial", 0.5), ("forgot", 0.0)],
    )
    async def test_verdict_scores(self, verdict, expected):
        reply = {"content": json.dumps({"verdict": verdict, "reasoning": "r"}), "usage": {}}
        with patch(
            "evaluation.metrics.conversation_retention.chat_completion",
            new=AsyncMock(return_value=reply),
        ):
            score = await conversation_retention.score(
                None,
                "What's my refund window?",
                "Annual Pro plans have a 30-day window.",
                {"_transcript": self.TRANSCRIPT},
            )
        assert score == expected

    async def test_empty_answer_scores_zero(self):
        score = await conversation_retention.score(
            None, "q", "", {"_transcript": self.TRANSCRIPT}
        )
        assert score == 0.0

    async def test_unparseable_returns_none(self):
        reply = {"content": "not json at all", "usage": {}}
        with patch(
            "evaluation.metrics.conversation_retention.chat_completion",
            new=AsyncMock(return_value=reply),
        ):
            score = await conversation_retention.score(
                None, "q", "a", {"_transcript": self.TRANSCRIPT}
            )
        assert score is None


class TestConnectorHistory:
    async def test_openai_connector_includes_history(self):
        from pipeline.bot_connectors.openai_bot import OpenAIBotConnector

        connector = OpenAIBotConnector(api_key="sk-test", model="gpt-test")
        captured = {}

        class FakeMsg:
            content = "answer"

        class FakeChoice:
            message = FakeMsg()

        class FakeResponse:
            id = "x"
            model = "gpt-test"
            usage = None
            choices = [FakeChoice()]

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return FakeResponse()

        connector._client.chat.completions.create = fake_create
        history = [
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "reply 1"},
        ]
        await connector.query("final question", history=history)
        roles = [m["role"] for m in captured["messages"]]
        assert roles == ["user", "assistant", "user"]
        assert captured["messages"][-1]["content"] == "final question"

    async def test_csv_connector_rejects_history(self):
        from pipeline.bot_connectors.base import ConversationUnsupported
        from pipeline.bot_connectors.csv_connector import CsvBotConnector

        connector = CsvBotConnector.__new__(CsvBotConnector)
        with pytest.raises(ConversationUnsupported):
            await connector.query("q", history=[{"role": "user", "content": "x"}])
