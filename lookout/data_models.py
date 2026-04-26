"""Pydantic v2 schema. Source of truth for all on-disk JSON.

Conforms to PLAN.md §Data models.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ActionType = Literal[
    "click", "type", "scroll", "navigate", "wait", "extract", "select", "press_key"
]
Verdict_ = Literal["pass", "fail", "uncertain"]
Mode_ = Literal["baseline", "verified"]
FinalStatus_ = Literal["success", "failure", "timeout", "error"]


class Action(BaseModel):
    type: ActionType
    target: dict
    payload: dict | None = None


class StepContext(BaseModel):
    url_before: str
    url_after: str
    pixel_diff_pct: float = Field(ge=0, le=100)
    dom_nodes_added: int = Field(ge=0)
    dom_nodes_removed: int = Field(ge=0)
    dom_nodes_changed: int = Field(ge=0)


class Verdict(BaseModel):
    verdict: Verdict_
    confidence: float = Field(ge=0, le=1)
    reason: str
    recommend: str | None = None
    latency_ms: int = Field(ge=0)
    model: str


class Step(BaseModel):
    step_id: int = Field(ge=0)
    timestamp: datetime
    intent: str
    action: Action
    before_screenshot: str
    after_screenshot: str
    context: StepContext
    verifier_verdict: Verdict | None = None
    ground_truth_label: Verdict_ | None = None


class TaskRun(BaseModel):
    task_id: str
    task_description: str
    mode: Mode_
    run_index: int = Field(ge=0)
    steps: list[Step] = Field(default_factory=list)
    final_status: FinalStatus_
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime


class EvalResult(BaseModel):
    suite_name: str
    runs: list[TaskRun] = Field(default_factory=list)
    baseline_success_rate: float | None = Field(default=None, ge=0, le=1)
    verified_success_rate: float | None = Field(default=None, ge=0, le=1)
    delta_pp: float | None = None
    verifier_precision: float | None = Field(default=None, ge=0, le=1)
    verifier_recall: float | None = Field(default=None, ge=0, le=1)
    verifier_accuracy: float | None = Field(default=None, ge=0, le=1)
