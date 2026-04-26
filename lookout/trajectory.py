"""Capture wrapper around browser-use's Agent. Records per-step (intent, action,
before/after screenshots, URL, DOM diff context) and writes a TaskRun JSON.

The two browser-use hooks we use:

    register_new_step_callback(state, agent_output, step_n)
        Fires AFTER the agent has decided what to do this step but BEFORE the
        action executes. `state.screenshot` is the BEFORE screenshot for step_n.
        `agent_output.next_goal` is the agent's stated intent. `agent_output.action`
        is what's about to execute.

    on_step_end(agent)  (passed to Agent.run)
        Fires AFTER the action executes. We grab a fresh screenshot via
        agent.browser_session.take_screenshot() — that's the AFTER screenshot.
        Note: for the final step (when agent calls `done`), the browser may
        already be tearing down, so the after screenshot can be small/blank.
        That's an acceptable degradation; the verifier still sees "agent called
        done" and we don't need a perfect after for the final step.
"""
from __future__ import annotations

import asyncio
import base64
import time
from datetime import datetime, timezone
from pathlib import Path

from browser_use import Agent
from browser_use.llm import ChatAnthropic
from browser_use.llm.base import BaseChatModel

from .data_models import Action, Mode_, Step, StepContext, TaskRun
from .diffs import pixel_diff_pct
from .tasks.registry import Task


class TrajectoryCapture:
    """Run a Task with browser-use, capture every step, return a TaskRun.

    Usage:
        cap = TrajectoryCapture(task=get("T03"), mode="baseline", run_index=0)
        task_run = await cap.run()

    On-disk layout produced under data/trajectories/{task_id}/{mode}/{run_index}/:
        screenshots/step_NNN_before.png
        screenshots/step_NNN_after.png
        run.json     (the TaskRun, also returned in-memory)
    """

    def __init__(
        self,
        task: Task,
        mode: Mode_ = "baseline",
        run_index: int = 0,
        llm: BaseChatModel | None = None,
        max_steps: int | None = None,
        agent_kwargs: dict | None = None,
    ):
        self.task = task
        self.mode = mode
        self.run_index = run_index
        self.llm = llm or ChatAnthropic(model="claude-sonnet-4-6")
        self.max_steps = max_steps if max_steps is not None else task.timeout_steps
        self.agent_kwargs = agent_kwargs or {}

        self.out_dir = Path("data/trajectories") / task.task_id / mode / str(run_index)
        self.shots_dir = self.out_dir / "screenshots"
        self.shots_dir.mkdir(parents=True, exist_ok=True)

        # In-flight scratch
        self._records: list[dict] = []
        self._started_at: datetime | None = None
        self._finished_at: datetime | None = None
        self._final_status: str = "error"
        self._error_message: str | None = None

    # --- Hooks ---------------------------------------------------------------

    async def _on_new_step(self, state, output, step_num: int) -> None:
        if self._started_at is None:
            self._started_at = datetime.now(timezone.utc)

        before_rel = f"screenshots/step_{step_num:03d}_before.png"
        self._save_b64(state.screenshot, self.out_dir / before_rel)

        actions_serial: list[dict] = []
        for act in (output.action or []):
            try:
                actions_serial.append(act.model_dump(exclude_none=True))
            except Exception:
                actions_serial.append({"raw": repr(act)})

        # Per-PRD: intent is "what the agent intended THIS single action to do",
        # not the agent's broader plan. With max_actions_per_step=1, we synthesize
        # a per-action intent from the action payload. The agent's plan-level
        # goal is preserved separately as agent_plan for the verifier to use as context.
        agent_plan = (output.next_goal or "").strip()
        intent = _synthesize_action_intent(actions_serial[0] if actions_serial else None, agent_plan)

        self._records.append({
            "step": step_num,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url_before": getattr(state, "url", "") or "",
            "title_before": getattr(state, "title", "") or "",
            "intent": intent,
            "agent_plan": agent_plan,
            "thinking": output.thinking or "",
            "evaluation_previous_goal": output.evaluation_previous_goal or "",
            "actions": actions_serial,
            "before_screenshot": before_rel,
            "after_screenshot": None,
            "url_after": "",
        })

    async def _on_step_end(self, agent) -> None:
        if not self._records:
            return
        last = self._records[-1]
        step_num = last["step"]
        after_rel = f"screenshots/step_{step_num:03d}_after.png"
        try:
            shot = await agent.browser_session.take_screenshot()
            if self._save_image(shot, self.out_dir / after_rel):
                last["after_screenshot"] = after_rel
            # also capture URL after the action
            try:
                state = await agent.browser_session.get_browser_state_summary()
                last["url_after"] = getattr(state, "url", "") or ""
            except Exception:
                pass
        except Exception as e:
            last["after_screenshot_error"] = repr(e)

    async def _on_done(self, history) -> None:
        try:
            if history.has_errors():
                self._final_status = "error"
                self._error_message = "history reports errors"
            elif history.is_done():
                self._final_status = "success" if history.is_successful() else "failure"
            else:
                self._final_status = "failure"
        except Exception as e:
            self._final_status = "error"
            self._error_message = repr(e)

    # --- Public API ----------------------------------------------------------

    async def run(self) -> TaskRun:
        agent = Agent(
            task=self.task.description,
            llm=self.llm,
            register_new_step_callback=self._on_new_step,
            register_done_callback=self._on_done,
            use_vision=True,
            use_judge=False,        # we measure OUR verifier; don't confound with browser-use's judge
            enable_planning=False,  # keep agent behavior simple for clean delta measurement
            max_actions_per_step=1, # one action per step for clean per-step capture
            **self.agent_kwargs,
        )

        try:
            await agent.run(max_steps=self.max_steps, on_step_end=self._on_step_end)
        except asyncio.TimeoutError:
            self._final_status = "timeout"
            self._error_message = "asyncio TimeoutError during run"
        except Exception as e:
            self._final_status = "error"
            self._error_message = repr(e)

        self._finished_at = datetime.now(timezone.utc)
        task_run = self._build_task_run()
        self._write_run_json(task_run)
        return task_run

    # --- Internal helpers ----------------------------------------------------

    def _build_task_run(self) -> TaskRun:
        steps: list[Step] = []
        prev_url = ""
        for rec in self._records:
            actions = rec["actions"] or []
            action_payload = actions[0] if actions else {"unknown": {}}
            # browser-use serializes one action like {"click_element": {"index": 5}}
            atype, aparams = next(iter(action_payload.items()))
            mapped_type = _map_action_type(atype)
            action = Action(type=mapped_type, target={"raw_type": atype, "params": aparams or {}}, payload=None)

            url_before = rec["url_before"] or prev_url
            url_after = rec.get("url_after") or url_before

            before_path = self.out_dir / rec["before_screenshot"] if rec["before_screenshot"] else None
            after_path = self.out_dir / rec["after_screenshot"] if rec.get("after_screenshot") else None

            pixel_diff = (
                pixel_diff_pct(before_path, after_path)
                if before_path and after_path and before_path.exists() and after_path.exists()
                else 0.0
            )

            ctx = StepContext(
                url_before=url_before,
                url_after=url_after,
                pixel_diff_pct=pixel_diff,
                dom_nodes_added=0,    # TODO: real DOM diff in M1.5
                dom_nodes_removed=0,
                dom_nodes_changed=0,
            )

            steps.append(Step(
                step_id=rec["step"],
                timestamp=datetime.fromisoformat(rec["timestamp"]),
                intent=rec["intent"],
                action=action,
                before_screenshot=rec["before_screenshot"],
                after_screenshot=rec.get("after_screenshot") or rec["before_screenshot"],
                context=ctx,
                verifier_verdict=None,
                ground_truth_label=None,
            ))
            prev_url = url_after

        started = self._started_at or datetime.now(timezone.utc)
        finished = self._finished_at or datetime.now(timezone.utc)
        return TaskRun(
            task_id=self.task.task_id,
            task_description=self.task.description,
            mode=self.mode,
            run_index=self.run_index,
            steps=steps,
            final_status=self._final_status,  # type: ignore[arg-type]
            error_message=self._error_message,
            started_at=started,
            finished_at=finished,
        )

    def _write_run_json(self, run: TaskRun) -> None:
        (self.out_dir / "run.json").write_text(run.model_dump_json(indent=2))

    @staticmethod
    def _save_b64(b64: str | None, path: Path) -> bool:
        if not b64:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(b64))
        return True

    @staticmethod
    def _save_image(data: str | bytes | None, path: Path) -> bool:
        if not data:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, (bytes, bytearray)):
            path.write_bytes(bytes(data))
            return True
        try:
            path.write_bytes(base64.b64decode(data))
            return True
        except Exception:
            return False


# --- Action-type mapping -----------------------------------------------------
# browser-use exposes many concrete action verbs (click_element, input_text,
# scroll_down, ...). Our schema (PRD §Data models) uses a small Literal set.
# Map the common ones; fall back to "click" + raw payload for the long tail.

_ACTION_TYPE_MAP = {
    "click": "click",
    "click_element": "click",
    "click_element_by_index": "click",
    "input_text": "type",
    "type_text": "type",
    "fill": "type",
    "scroll": "scroll",
    "scroll_down": "scroll",
    "scroll_up": "scroll",
    "go_to_url": "navigate",
    "navigate": "navigate",
    "open_tab": "navigate",
    "wait": "wait",
    "extract_content": "extract",
    "extract": "extract",
    "select_dropdown_option": "select",
    "select_option": "select",
    "select": "select",
    "press_key": "press_key",
    "send_keys": "press_key",
    "done": "extract",  # the agent's terminal action; treat as "extract result"
}


def _map_action_type(raw: str) -> str:
    return _ACTION_TYPE_MAP.get(raw, "click")


def _synthesize_action_intent(action_payload: dict | None, fallback_plan: str = "") -> str:
    """Build a one-sentence intent describing this single action's expected effect.

    The verifier needs intent at action granularity, not plan granularity. Examples:
        {"input": {"index": 8, "text": "tomsmith"}}  -> "Type 'tomsmith' into the field at index 8."
        {"click": {"index": 10}}                      -> "Click the element at index 10."
        {"go_to_url": {"url": "https://..."}}         -> "Navigate to https://..."
        {"done": {"text": "..."}}                     -> "Mark the task as complete with the final answer."
    """
    if not action_payload:
        return fallback_plan or "Take an unspecified action."
    atype, params = next(iter(action_payload.items()))
    params = params or {}

    def _q(s):  # quote a value if non-empty
        s = str(s)
        return f"'{s[:80]}'" + ("..." if len(s) > 80 else "")

    if atype in ("input", "input_text", "type_text", "fill"):
        text = params.get("text", "")
        idx = params.get("index", "?")
        return f"Type {_q(text)} into the field at index {idx}."
    if atype in ("click", "click_element", "click_element_by_index"):
        idx = params.get("index", "?")
        return f"Click the element at index {idx}."
    if atype in ("scroll", "scroll_down", "scroll_up"):
        amt = params.get("amount", "")
        direction = "down" if "down" in atype or (params.get("down") is True) else ("up" if "up" in atype else "")
        return f"Scroll {direction} {amt}".strip() + "."
    if atype in ("go_to_url", "navigate", "open_tab"):
        url = params.get("url", "?")
        return f"Navigate to {url}."
    if atype == "wait":
        secs = params.get("seconds", params.get("ms", "?"))
        return f"Wait {secs} for the page to update."
    if atype in ("extract_content", "extract"):
        return "Extract relevant content from the current page."
    if atype in ("select_dropdown_option", "select_option", "select"):
        opt = params.get("text") or params.get("option") or params.get("value", "?")
        return f"Select dropdown option {_q(opt)}."
    if atype in ("press_key", "send_keys"):
        key = params.get("key") or params.get("keys", "?")
        return f"Press the key {_q(key)}."
    if atype == "done":
        return "Declare the task complete and return the final answer."
    return f"Execute action '{atype}' with parameters {params}."
