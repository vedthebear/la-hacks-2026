"""M6: VerifiedTrajectoryCapture — extends the base capture with a verifier-in-loop.

After each step's action executes, we:
  1. Build a Verdict via the Verifier (intent, action, before, after, context).
  2. Stamp that Verdict on the step record.
  3. If verdict is "fail" with confidence above fail_threshold, inject feedback
     into the agent via Agent.add_new_task() so the next step replans.

Caps (from PRD §Online retry loop):
  - max retries per step: 1
  - max total steps per task: 30 (already enforced by Task.timeout_steps)
  - hard timeout per task: 5 minutes wall clock (caller's responsibility)
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from .data_models import Action, StepContext, Verdict
from .diffs import pixel_diff_pct
from .tasks.registry import Task
from .trajectory import TrajectoryCapture, _map_action_type
from .verifier import Verifier


REPLAN_TEMPLATE = (
    "VERIFIER FEEDBACK: Your previous action was judged to have FAILED.\n"
    "Reason: {reason}\n"
    "Suggested next action: {recommend}\n"
    "Replan and try again. Do not repeat the previous action."
)


class VerifiedTrajectoryCapture(TrajectoryCapture):
    """Capture wrapper that runs the verifier after each step and injects feedback on fail."""

    def __init__(
        self,
        task: Task,
        verifier: Verifier,
        run_index: int = 0,
        fail_threshold: float = 0.7,
        max_retries_per_step: int = 1,
        injection_strategy: Literal["add_new_task", "task_reprompt"] = "add_new_task",
        **kwargs,
    ):
        super().__init__(task=task, mode="verified", run_index=run_index, **kwargs)
        self.verifier = verifier
        self.fail_threshold = fail_threshold
        self.max_retries_per_step = max_retries_per_step
        self.injection_strategy = injection_strategy

        # Per-step retry counter (keyed by step number)
        self._retries_used: dict[int, int] = {}

    async def _on_step_end(self, agent) -> None:
        # 1. Capture after-screenshot via base implementation
        await super()._on_step_end(agent)

        if not self._records:
            return
        last = self._records[-1]
        step_num = last["step"]

        # 2. Build Action + StepContext for this step
        before_path = self.out_dir / last["before_screenshot"] if last["before_screenshot"] else None
        after_path = self.out_dir / last["after_screenshot"] if last.get("after_screenshot") else None
        if not before_path or not after_path or not before_path.exists() or not after_path.exists():
            # Can't verify without both shots — record this gap and proceed
            last["verifier_skipped_reason"] = "missing screenshot(s)"
            return

        actions = last["actions"] or []
        action_payload = actions[0] if actions else {"unknown": {}}
        atype, aparams = next(iter(action_payload.items()))
        action = Action(
            type=_map_action_type(atype),
            target={"raw_type": atype, "params": aparams or {}},
            payload=None,
        )

        url_before = last["url_before"] or ""
        url_after = last.get("url_after") or url_before
        pixel_diff = pixel_diff_pct(before_path, after_path)
        ctx = StepContext(
            url_before=url_before,
            url_after=url_after,
            pixel_diff_pct=pixel_diff,
            dom_nodes_added=0,
            dom_nodes_removed=0,
            dom_nodes_changed=0,
        )

        # 3. Call verifier
        try:
            verdict: Verdict = self.verifier.verify(
                intent=last["intent"],
                action=action,
                before_screenshot_path=before_path,
                after_screenshot_path=after_path,
                context=ctx,
                agent_plan=last.get("agent_plan"),
            )
        except Exception as e:
            last["verifier_error"] = repr(e)
            return

        # 4. Stamp the verdict on the step record (will land in run.json after _build_task_run)
        last["verifier_verdict"] = verdict.model_dump()

        # 5. On confident fail, inject feedback for replan
        if verdict.verdict == "fail" and verdict.confidence >= self.fail_threshold:
            used = self._retries_used.get(step_num, 0)
            if used >= self.max_retries_per_step:
                last["replan_skipped_reason"] = "max_retries_per_step exceeded"
                return
            self._retries_used[step_num] = used + 1
            self._inject_feedback(agent, verdict)
            last["replan_injected"] = True
            last["replan_strategy"] = self.injection_strategy

    def _inject_feedback(self, agent, verdict: Verdict) -> None:
        msg = REPLAN_TEMPLATE.format(
            reason=verdict.reason,
            recommend=verdict.recommend or "Try a different element on the page.",
        )
        if self.injection_strategy == "add_new_task":
            agent.add_new_task(msg)
        else:
            # task_reprompt: rewrite agent's task; agent's next step picks up the
            # new task description on the next run loop iteration.
            agent.task = f"{self.task.description}\n\n{msg}"

    def _build_task_run(self):
        """Override to attach verifier_verdict from records."""
        run = super()._build_task_run()
        for step, rec in zip(run.steps, self._records):
            v = rec.get("verifier_verdict")
            if v:
                step.verifier_verdict = Verdict.model_validate(v)
        # Re-write run.json with verdict info now baked in
        return run
