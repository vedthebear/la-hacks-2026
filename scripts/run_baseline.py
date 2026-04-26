"""M4: run vanilla browser-use against the 10-task suite, N times each.

For every (task, run_index), capture a TaskRun via TrajectoryCapture and write
run.json + screenshots to data/trajectories/{task}/baseline/{run}/.

After all runs finish, aggregate into data/results/baseline.json (an EvalResult).

Usage:
    .venv/bin/python scripts/run_baseline.py                # all 10 tasks x 3 runs
    .venv/bin/python scripts/run_baseline.py --runs 1       # 10 tasks x 1 run (smoke)
    .venv/bin/python scripts/run_baseline.py --tasks T01,T03,T05 --runs 2
    .venv/bin/python scripts/run_baseline.py --skip-existing  # don't re-run tasks already on disk
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from lookout.data_models import EvalResult, TaskRun  # noqa: E402
from lookout.tasks import all_tasks, get  # noqa: E402
from lookout.tasks.checks import CHECKS  # noqa: E402
from lookout.trajectory import TrajectoryCapture  # noqa: E402


RESULTS_PATH = Path("data/results/baseline.json")


async def run_one(task_id: str, run_idx: int) -> TaskRun:
    task = get(task_id)
    cap = TrajectoryCapture(task=task, mode="baseline", run_index=run_idx)
    return await cap.run()


def already_captured(task_id: str, run_idx: int) -> bool:
    return Path(f"data/trajectories/{task_id}/baseline/{run_idx}/run.json").exists()


def load_existing(task_id: str, run_idx: int) -> TaskRun | None:
    p = Path(f"data/trajectories/{task_id}/baseline/{run_idx}/run.json")
    if not p.exists():
        return None
    try:
        return TaskRun.model_validate_json(p.read_text())
    except Exception as e:
        print(f"  [warn] could not load {p}: {e!r}", file=sys.stderr)
        return None


def evaluate_success(run: TaskRun) -> bool:
    """Run the task's success_check on the final state of the captured run.

    For now we only have access to the agent's final reported text + the last
    URL. M4 success metric is the binary: did the agent's run end with
    final_status=success AND does the success_check pass on whatever evidence
    we have? For deterministic tasks this is enough; for content tasks (T06,
    T10) we trust agent's final answer text.
    """
    if run.final_status != "success":
        return False
    task = get(run.task_id)
    check = CHECKS[task.success_check_name]

    # Pull final URL + final agent text + a dump of the last steps' page content
    final_url = run.steps[-1].context.url_after if run.steps else ""
    # Reconstruct page text: union of intent + thinking from final 3 steps
    last_steps = run.steps[-3:] if len(run.steps) >= 3 else run.steps
    page_text_blob = "\n".join((s.intent + " " + (getattr(s, "thinking", "") or "")) for s in last_steps)
    # Pull "done" text from final action if present
    final_action = run.steps[-1].action if run.steps else None
    done_text = ""
    if final_action and final_action.target.get("raw_type") == "done":
        params = final_action.target.get("params") or {}
        done_text = params.get("text", "") or ""

    # Combine for free-text checks (T01 stars, T06 title, T10 points)
    page_text = f"{page_text_blob}\n{done_text}"

    try:
        return bool(check(final_url, page_text, agent_return=done_text))
    except Exception as e:
        print(f"  [warn] success_check raised for {run.task_id}: {e!r}", file=sys.stderr)
        return False


def write_eval_result(runs: list[TaskRun]) -> EvalResult:
    n_total = len(runs) or 1
    n_success = sum(1 for r in runs if evaluate_success(r))
    rate = n_success / n_total

    res = EvalResult(
        suite_name="baseline",
        runs=runs,
        baseline_success_rate=rate,
        verified_success_rate=None,
        delta_pp=None,
        verifier_precision=None,
        verifier_recall=None,
        verifier_accuracy=None,
    )
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(res.model_dump_json(indent=2))
    return res


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3, help="Runs per task")
    parser.add_argument("--tasks", default=None, help="Comma-separated task IDs (default: all 10)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip (task,run) pairs already on disk")
    parser.add_argument("--continue-on-error", action="store_true", default=True)
    args = parser.parse_args(argv)

    if args.tasks:
        task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
        for tid in task_ids:
            get(tid)  # validate
    else:
        task_ids = [t.task_id for t in all_tasks()]

    print(f"[run_baseline] tasks={task_ids} | runs_per_task={args.runs} | skip_existing={args.skip_existing}")
    n_total = len(task_ids) * args.runs
    print(f"[run_baseline] total runs to perform: {n_total}")

    all_runs: list[TaskRun] = []
    completed = 0
    failed = 0
    t_start = time.time()

    for tid in task_ids:
        for run_idx in range(args.runs):
            label = f"{tid}/baseline/{run_idx}"
            if args.skip_existing and already_captured(tid, run_idx):
                existing = load_existing(tid, run_idx)
                if existing:
                    all_runs.append(existing)
                    completed += 1
                    elapsed = time.time() - t_start
                    print(f"[{completed:>2}/{n_total}] [skip-existing] {label} status={existing.final_status} | elapsed={elapsed:.0f}s")
                    continue
            try:
                run = await run_one(tid, run_idx)
                all_runs.append(run)
                completed += 1
                elapsed = time.time() - t_start
                print(f"[{completed:>2}/{n_total}] [done] {label} status={run.final_status} steps={len(run.steps)} | elapsed={elapsed:.0f}s")
            except Exception as e:
                failed += 1
                print(f"[{completed:>2}/{n_total}] [FAIL] {label} {e!r}", file=sys.stderr)
                if not args.continue_on_error:
                    raise

    res = write_eval_result(all_runs)
    elapsed = time.time() - t_start
    print(f"\n[run_baseline] complete | elapsed={elapsed:.0f}s | runs={len(all_runs)} | failed={failed}")
    print(f"[run_baseline] baseline_success_rate = {res.baseline_success_rate:.2%}")
    print(f"[run_baseline] result: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
