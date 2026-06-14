"""Staged skills: stage-plan extraction and trial stage-progression scoring."""

from app.services.skill_trials import _stage_metrics
from evaluation.skills.parser import extract_stages, referenced_paths

# A creating-apps-style staged skill: phase headings plus bold stage markers
# that load per-tier reference files.
STAGED_SKILL = """---
name: creating-apps
---

# Creating a New App

## Pre-Flight — Clarify First

Ask all questions in one message.

## Phase 0 — Discovery (read-only)

Run `make list-libs` and read docs.

## Phase 1 — Design Review

Present the design table and wait for confirmation.

## Phases 3–5 — Medallion Tiers

For each tier, read the tier file before asking questions.

**Phase 3 — Bronze / Ingest:** Load `tiers/bronze.md`

**Phase 4 — Silver / Transform:** Load `tiers/silver.md`

**Phase 5 — Gold / Serving:** Load `tiers/gold.md`

## Phase 6 — Register

Update the registry files.
"""


class TestBacktickReferences:
    def test_backtick_paths_detected(self):
        content = "Load `tiers/bronze.md` first, then `tiers/silver.md`."
        paths = referenced_paths(content)
        assert paths == ["tiers/bronze.md", "tiers/silver.md"]

    def test_backtick_commands_not_detected(self):
        # Shell commands in backticks are not file references
        assert referenced_paths("Run `make list-libs` and `git status`.") == []


class TestExtractStages:
    def test_unstaged_skill_has_no_stages(self):
        assert extract_stages("# Skill\nAlways answer in JSON.") == []

    def test_staged_skill_extracts_ordered_plan(self):
        stages = extract_stages(STAGED_SKILL)
        titles = [s["title"] for s in stages]
        assert any("Phase 0" in t for t in titles)
        assert any("Phase 6" in t for t in titles)
        # Phases appear in document order
        assert titles.index(next(t for t in titles if "Phase 0" in t)) < titles.index(
            next(t for t in titles if "Phase 6" in t)
        )

    def test_stage_files_associated_with_their_stage(self):
        stages = extract_stages(STAGED_SKILL)
        bronze = next(s for s in stages if "Bronze" in s["title"])
        assert bronze["files"] == ["tiers/bronze.md"]
        gold = next(s for s in stages if "Gold" in s["title"])
        assert gold["files"] == ["tiers/gold.md"]

    def test_stage_plan_files_in_tier_order(self):
        stages = extract_stages(STAGED_SKILL)
        ordered = [f for s in stages for f in s["files"]]
        assert ordered == ["tiers/bronze.md", "tiers/silver.md", "tiers/gold.md"]


class TestStageMetrics:
    STAGES = [
        {"id": "stage-1", "title": "Phase 3", "files": ["tiers/bronze.md"]},
        {"id": "stage-2", "title": "Phase 4", "files": ["tiers/silver.md"]},
        {"id": "stage-3", "title": "Phase 5", "files": ["tiers/gold.md"]},
    ]

    def test_no_stage_files_returns_none(self):
        assert _stage_metrics([{"id": "s1", "title": "Phase 1", "files": []}], []) is None

    def test_full_coverage_in_order(self):
        scores = _stage_metrics(
            self.STAGES, ["tiers/bronze.md", "tiers/silver.md", "tiers/gold.md"]
        )
        assert scores == {"stage_coverage": 1.0, "stage_order": 1.0, "stage_files_total": 3}

    def test_partial_coverage(self):
        scores = _stage_metrics(self.STAGES, ["tiers/bronze.md"])
        assert scores["stage_coverage"] == round(1 / 3, 4)
        assert scores["stage_order"] == 1.0

    def test_out_of_order_reads_penalized(self):
        scores = _stage_metrics(
            self.STAGES, ["tiers/gold.md", "tiers/silver.md", "tiers/bronze.md"]
        )
        assert scores["stage_coverage"] == 1.0
        assert scores["stage_order"] == 0.0

    def test_nothing_read(self):
        scores = _stage_metrics(self.STAGES, [])
        assert scores["stage_coverage"] == 0.0
        assert scores["stage_order"] == 0.0

    def test_suffix_path_matching(self):
        # Models sometimes pass a bare filename; suffix matches still count.
        scores = _stage_metrics(self.STAGES, ["bronze.md", "silver.md"])
        assert scores["stage_coverage"] == round(2 / 3, 4)
