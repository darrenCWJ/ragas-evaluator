"""Unit tests for schedule due-detection and metric-drop alerts."""

from datetime import datetime, timedelta

import pytest

from app.services.schedule_service import detect_drops, find_due_schedules

pytestmark = pytest.mark.unit

NOW = datetime(2026, 6, 12, 12, 0, 0)


@pytest.fixture
def schedule_db(sample_project):
    conn, pid = sample_project
    ts = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, 's')", (pid,)
    ).lastrowid
    bc = conn.execute(
        "INSERT INTO bot_configs (project_id, name, connector_type, config_json) VALUES (?, 'bot', 'custom', '{}')",
        (pid,),
    ).lastrowid
    conn.commit()

    def add_schedule(*, enabled=1, interval=60, last_run_at=None) -> int:
        sid = conn.execute(
            "INSERT INTO schedules (project_id, name, bot_config_id, test_set_id, metrics_json, interval_minutes, enabled, last_run_at) "
            "VALUES (?, 'sched', ?, ?, '[]', ?, ?, ?)",
            (pid, bc, ts, interval, enabled, last_run_at),
        ).lastrowid
        conn.commit()
        return sid

    return conn, add_schedule


class TestFindDueSchedules:
    def test_never_run_is_due(self, schedule_db):
        conn, add = schedule_db
        sid = add(last_run_at=None)
        assert [r["id"] for r in find_due_schedules(conn, NOW)] == [sid]

    def test_recent_run_not_due(self, schedule_db):
        conn, add = schedule_db
        add(interval=60, last_run_at=(NOW - timedelta(minutes=30)).isoformat())
        assert find_due_schedules(conn, NOW) == []

    def test_elapsed_interval_is_due(self, schedule_db):
        conn, add = schedule_db
        sid = add(interval=60, last_run_at=(NOW - timedelta(minutes=61)).isoformat())
        assert [r["id"] for r in find_due_schedules(conn, NOW)] == [sid]

    def test_disabled_never_due(self, schedule_db):
        conn, add = schedule_db
        add(enabled=0, last_run_at=None)
        assert find_due_schedules(conn, NOW) == []

    def test_malformed_timestamp_is_due(self, schedule_db):
        conn, add = schedule_db
        sid = add(last_run_at="not-a-date")
        assert [r["id"] for r in find_due_schedules(conn, NOW)] == [sid]


class TestDetectDrops:
    def test_flags_drop_above_threshold(self):
        drops = detect_drops({"bleu_score": 0.8}, {"bleu_score": 0.6}, threshold=0.1)
        assert drops == [
            {"metric": "bleu_score", "baseline": 0.8, "current": 0.6, "drop": 0.2}
        ]

    def test_ignores_small_drops_and_improvements(self):
        baseline = {"bleu_score": 0.8, "rouge_score": 0.5}
        current = {"bleu_score": 0.75, "rouge_score": 0.9}
        assert detect_drops(baseline, current, threshold=0.1) == []

    def test_skips_missing_and_null_metrics(self):
        baseline = {"a": 0.9, "b": None, "c": 0.9}
        current = {"a": None, "c": 0.1}
        drops = detect_drops(baseline, current, threshold=0.1)
        assert [d["metric"] for d in drops] == ["c"]
