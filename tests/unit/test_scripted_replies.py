"""Keyword-matched scripted replies — order-independent answer pairing."""

from app.services.scripted_replies import ScriptedReplies


class TestScriptedReplies:
    def test_plain_lines_consumed_in_order(self):
        replies = ScriptedReplies(["first answer", "second answer"])
        assert replies.take("Anything?") == "first answer"
        assert replies.take("Anything else?") == "second answer"
        assert replies.take("More?") is None

    def test_keyed_lines_match_regardless_of_order(self):
        replies = ScriptedReplies([
            "name => fraud-alert-daily",
            "schedule => daily at 02:00",
        ])
        # Model asks schedule FIRST — keyword matching still pairs correctly
        assert replies.take("What schedule should the job run on?") == "daily at 02:00"
        assert replies.take("What is the app name?") == "fraud-alert-daily"

    def test_unasked_keyed_lines_are_simply_unused(self):
        replies = ScriptedReplies(["name => my-app", "schedule => hourly"])
        assert replies.take("What is the name?") == "my-app"
        # The model never asks about the schedule — no misfire on other questions
        assert replies.take("Which language do you prefer?") is None

    def test_keyed_match_wins_over_plain_fallback(self):
        replies = ScriptedReplies(["positional answer", "owner => platform-team"])
        assert replies.take("Who is the owner team?") == "platform-team"
        assert replies.take("Anything unmatched?") == "positional answer"

    def test_arrow_separator_and_case_insensitive(self):
        replies = ScriptedReplies(["Language -> Python"])
        assert replies.take("Which LANGUAGE should we use?") == "Python"

    def test_keyed_line_used_once(self):
        replies = ScriptedReplies(["name => my-app"])
        assert replies.take("Name?") == "my-app"
        assert replies.take("Name again?") is None

    def test_bool_reflects_remaining(self):
        replies = ScriptedReplies(["only one"])
        assert bool(replies) is True
        replies.take("q")
        assert bool(replies) is False

    def test_blank_lines_ignored(self):
        replies = ScriptedReplies(["", "   ", "real answer"])
        assert replies.take("q") == "real answer"
        assert replies.take("q2") is None
