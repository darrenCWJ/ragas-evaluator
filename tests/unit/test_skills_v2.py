"""Skills v2: multi-file zip ingestion, reference scanning, user simulation."""

import io
import json
import zipfile

import pytest
from fastapi import HTTPException

from app.routes.skills import _extract_skill_zip
from evaluation.skills.parser import detect_interaction, referenced_paths


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, data in files.items():
            zf.writestr(path, data)
    return buf.getvalue()


class TestReferencedPaths:
    def test_markdown_links_and_bare_references(self):
        content = (
            "# Skill\nSee [the format guide](references/format.md) first.\n"
            "Also consult references/edge-cases.md and scripts/check.py when needed.\n"
            "External: [docs](https://example.com/doc) and [anchor](#section)."
        )
        paths = referenced_paths(content)
        assert "references/format.md" in paths
        assert "references/edge-cases.md" in paths
        assert "scripts/check.py" in paths
        assert all("example.com" not in p for p in paths)
        assert all(not p.startswith("#") for p in paths)

    def test_no_references(self):
        assert referenced_paths("# Plain skill\nAlways be brief.") == []


class TestDetectInteraction:
    def test_detects_user_interaction_phrases(self):
        assert detect_interaction("First, ask the user which option they want.")
        assert detect_interaction("Use AskUserQuestion to clarify scope.")
        assert detect_interaction("Wait for user confirmation before deleting.")

    def test_plain_skill_not_flagged(self):
        assert not detect_interaction("Always respond in bullet points. Never use emoji.")


class TestZipExtraction:
    def test_root_level_skill(self):
        data = _make_zip({
            "SKILL.md": b"# My Skill\nRules here.",
            "references/extra.md": b"Extra rules.",
        })
        skill_md, files, skipped = _extract_skill_zip(data)
        assert skill_md.startswith("# My Skill")
        assert files == {"references/extra.md": "Extra rules."}
        assert skipped == []

    def test_single_top_dir_skill(self):
        data = _make_zip({
            "my-skill/SKILL.md": b"# Nested",
            "my-skill/references/a.md": b"A",
        })
        skill_md, files, _ = _extract_skill_zip(data)
        assert skill_md == "# Nested"
        assert files == {"references/a.md": "A"}

    def test_binary_files_skipped(self):
        data = _make_zip({
            "SKILL.md": b"# S",
            "assets/logo.png": b"\x89PNG\x00\xff\xfe binary",
        })
        _, files, skipped = _extract_skill_zip(data)
        assert files == {}
        assert "assets/logo.png" in skipped

    def test_missing_skill_md_rejected(self):
        data = _make_zip({"readme.md": b"not a skill"})
        with pytest.raises(HTTPException) as exc:
            _extract_skill_zip(data)
        assert exc.value.status_code == 422

    def test_path_traversal_rejected(self):
        data = _make_zip({"SKILL.md": b"# S", "../evil.md": b"x"})
        with pytest.raises(HTTPException) as exc:
            _extract_skill_zip(data)
        assert "Unsafe path" in exc.value.detail

    def test_not_a_zip_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _extract_skill_zip(b"plain text, not a zip")
        assert exc.value.status_code == 422


class TestAgenticSkillCell:
    @pytest.mark.asyncio
    async def test_reads_files_and_answers_scripted_user(self, monkeypatch):
        """The agentic cell exposes read_file + ask_user; scripted answers win."""
        captured: dict = {}

        async def fake_run_agent(model, messages, tools, executor, *, max_steps=8, params=None):
            captured["tools"] = [t["name"] for t in tools]
            file_content = await executor("read_file", {"path": "references/format.md"})
            user_reply = await executor("ask_user", {"question": "Which format?"})
            captured["file_content"] = file_content
            captured["user_reply"] = user_reply
            return {
                "answer": "done",
                "steps": [
                    {"tool": "read_file", "arguments": {"path": "references/format.md"},
                     "result": file_content, "latency_ms": 1, "error": None},
                    {"tool": "ask_user", "arguments": {"question": "Which format?"},
                     "result": user_reply, "latency_ms": 1, "error": None},
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
                "stop_reason": "answer",
            }

        monkeypatch.setattr("pipeline.agent_loop.run_agent", fake_run_agent)
        from app.services.skill_trials import _query_model_agentic

        q_row = {
            "id": 1,
            "question": "Summarize the report",
            "metadata_json": json.dumps({"user_inputs": ["Use markdown format"]}),
        }
        reply = await _query_model_agentic(
            {"kind": "llm", "model": "gpt-test"},
            q_row,
            "# Skill content",
            {"references/format.md": "Always use tables."},
        )

        assert set(captured["tools"]) == {"ask_user", "read_file"}
        assert captured["file_content"] == "Always use tables."
        assert captured["user_reply"] == "Use markdown format"  # scripted, no LLM
        assert reply["answer"] == "done"
        assert reply["files_read"] == ["references/format.md"]
        assert reply["user_exchanges"] == 1
