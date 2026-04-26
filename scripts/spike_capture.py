"""Spike: confirm browser-use's hooks give us per-step (intent, action,
before/after screenshots, URL) for trajectory capture.

Acceptance (PRD §Trajectory capture acceptance test on T01):
- run.json with len(steps) > 0  (target >= 5)
- every step has both screenshot files on disk
- every step has a non-empty intent
- final_status is one of {success, failure, timeout, error}

Run:
    .venv/bin/python scripts/spike_capture.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent  # noqa: E402
from browser_use.llm import ChatAnthropic  # noqa: E402


OUT_DIR = Path("data/trajectories/T01_spike/baseline/0")
SHOTS_DIR = OUT_DIR / "screenshots"
RUN_JSON = OUT_DIR / "run.json"

T01_TASK = (
    "Go to https://github.com/browser-use/browser-use and report the star count "
    "shown on the repository's main page. Stop after you have read the number."
)

records: list[dict] = []
started_at: str | None = None


def _decode_and_save(b64: str | None, path: Path) -> bool:
    if not b64:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(b64))
    return True


async def on_new_step(state, output, step_num: int) -> None:
    """Fires after agent decides next action. state is the BEFORE state."""
    global started_at
    if started_at is None:
        started_at = datetime.now(timezone.utc).isoformat()

    shot_rel = f"screenshots/step_{step_num:03d}_before.png"
    saved = _decode_and_save(state.screenshot, OUT_DIR / shot_rel)

    intent = (output.next_goal or "").strip()
    if not intent:
        thinking = (output.thinking or "").strip()
        intent = thinking.split(".")[0][:200] if thinking else f"step_{step_num}_intent_unknown"

    actions_serial = []
    for act in (output.action or []):
        try:
            actions_serial.append(act.model_dump(exclude_none=True))
        except Exception:
            actions_serial.append({"raw": repr(act)})

    records.append({
        "step": step_num,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "url_before": getattr(state, "url", "") or "",
        "title_before": getattr(state, "title", "") or "",
        "intent": intent,
        "thinking": output.thinking or "",
        "evaluation_previous_goal": output.evaluation_previous_goal or "",
        "actions": actions_serial,
        "before_screenshot": shot_rel if saved else None,
        "after_screenshot": None,
    })


async def on_step_end(agent) -> None:
    """Fires after the action executes. Capture AFTER screenshot for the most recent step."""
    if not records:
        return
    last = records[-1]
    step_num = last["step"]
    shot_rel = f"screenshots/step_{step_num:03d}_after.png"
    try:
        b64 = await agent.browser_session.take_screenshot()
        if isinstance(b64, (bytes, bytearray)):
            (OUT_DIR / shot_rel).parent.mkdir(parents=True, exist_ok=True)
            (OUT_DIR / shot_rel).write_bytes(bytes(b64))
            last["after_screenshot"] = shot_rel
        elif _decode_and_save(b64, OUT_DIR / shot_rel):
            last["after_screenshot"] = shot_rel
    except Exception as e:
        last["after_screenshot_error"] = repr(e)


async def on_done(history) -> None:
    final_status = "failure"
    try:
        if history.has_errors():
            final_status = "error"
        elif history.is_done():
            final_status = "success" if history.is_successful() else "failure"
    except Exception as e:
        final_status = "error"
        print(f"[on_done] error reading history: {e!r}", file=sys.stderr)

    run = {
        "task_id": "T01_spike",
        "task_description": T01_TASK,
        "mode": "baseline",
        "run_index": 0,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "final_status": final_status,
        "step_count": len(records),
        "steps": records,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUN_JSON.write_text(json.dumps(run, indent=2, default=str))
    print(f"\n[done] wrote {RUN_JSON} | steps={len(records)} | status={final_status}")


async def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set. export it and re-run.", file=sys.stderr)
        return 2

    SHOTS_DIR.mkdir(parents=True, exist_ok=True)

    llm = ChatAnthropic(model="claude-sonnet-4-6")

    agent = Agent(
        task=T01_TASK,
        llm=llm,
        register_new_step_callback=on_new_step,
        register_done_callback=on_done,
        use_vision=True,
        use_judge=False,
        enable_planning=False,
        max_actions_per_step=1,
    )

    t0 = time.time()
    await agent.run(max_steps=15, on_step_end=on_step_end)
    print(f"[spike] total wall_time={time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
