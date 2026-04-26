"""Round-trip tests for pydantic schema. No I/O, no API."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from lookout.data_models import Action, EvalResult, Step, StepContext, TaskRun, Verdict


def test_action_roundtrip():
    a = Action(type="click", target={"selector": "#login"}, payload=None)
    j = a.model_dump_json()
    a2 = Action.model_validate_json(j)
    assert a2 == a


def test_action_invalid_type_rejected():
    with pytest.raises(ValidationError):
        Action(type="not_a_real_verb", target={})  # type: ignore[arg-type]


def test_step_context_validates_ranges():
    StepContext(url_before="a", url_after="b", pixel_diff_pct=0.0,
                dom_nodes_added=0, dom_nodes_removed=0, dom_nodes_changed=0)
    StepContext(url_before="a", url_after="b", pixel_diff_pct=100.0,
                dom_nodes_added=0, dom_nodes_removed=0, dom_nodes_changed=0)
    with pytest.raises(ValidationError):
        StepContext(url_before="a", url_after="b", pixel_diff_pct=101.0,
                    dom_nodes_added=0, dom_nodes_removed=0, dom_nodes_changed=0)
    with pytest.raises(ValidationError):
        StepContext(url_before="a", url_after="b", pixel_diff_pct=0.0,
                    dom_nodes_added=-1, dom_nodes_removed=0, dom_nodes_changed=0)


def test_verdict_confidence_range():
    Verdict(verdict="pass", confidence=0.0, reason="x", recommend=None, latency_ms=10, model="m")
    Verdict(verdict="pass", confidence=1.0, reason="x", recommend=None, latency_ms=10, model="m")
    with pytest.raises(ValidationError):
        Verdict(verdict="pass", confidence=1.1, reason="x", recommend=None, latency_ms=10, model="m")


def test_taskrun_minimal_serializes():
    ts = datetime.now(timezone.utc)
    tr = TaskRun(
        task_id="T01", task_description="Sample", mode="baseline", run_index=0,
        final_status="success", started_at=ts, finished_at=ts,
    )
    j = tr.model_dump_json()
    tr2 = TaskRun.model_validate_json(j)
    assert tr2.task_id == "T01"
    assert tr2.steps == []


def test_evalresult_optional_fields_default_none():
    res = EvalResult(suite_name="baseline", runs=[])
    assert res.delta_pp is None
    assert res.verifier_precision is None
    assert res.verifier_recall is None
