"""M7: run the VERIFIED variant of the suite — agent wrapped with verifier-in-loop.

For every (task, run_index), capture via VerifiedTrajectoryCapture. Aggregate into
data/results/verified.json (an EvalResult).

Usage:
    .venv/bin/python scripts/run_verified.py
    .venv/bin/python scripts/run_verified.py --tasks T03,T05 --runs 1
    .venv/bin/python scripts/run_verified.py --skip-existing
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from lookout.data_models import EvalResult, TaskRun  # noqa: E402
from lookout.loop import VerifiedTrajectoryCapture  # noqa: E402
from lookout.tasks import all_tasks, get  # noqa: E402
from lookout.verifier import Verifier  # noqa: E402

# Reuse the baseline scoring helpers
from scripts.run_baseline import evaluate_success  # noqa: E402


RESULTS_PATH = Path("data/results/verified.json")


def already_captured(task_id: str, run_idx: int) -> bool:
    return Path(f"data/trajectories/{task_id}/verified/{run_idx}/run.json").exists()


def load_existing(task_id: str, run_idx: int) -> TaskRun | None:
    p = Path(f"data/trajectories/{task_id}/verified/{run_idx}/run.json")
    if not p.exists():
        return None
    try:
        return TaskRun.model_validate_json(p.read_text())
    except Exception as e:
        print(f"  [warn] could not load {p}: {e!r}", file=sys.stderr)
        return None


async def run_one(task_id: str, run_idx: int, verifier: Verifier, fail_threshold: float) -> TaskRun:
    task = get(task_id)
    cap = VerifiedTrajectoryCapture(
        task=task,
        verifier=verifier,
        run_index=run_idx,
        fail_threshold=fail_threshold,
    )
    return await cap.run()


def write_eval_result(runs: list[TaskRun]) -> EvalResult:
    n_total = len(runs) or 1
    n_success = sum(1 for r in runs if evaluate_success(r))
    rate = n_success / n_total
    res = EvalResult(
        suite_name="verified",
        runs=runs,
        baseline_success_rate=None,
        verified_success_rate=rate,
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
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--tasks", default=None)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--fail-threshold", type=float, default=0.7)
    parser.add_argument("--verifier-model", default="claude-sonnet-4-6")
    parser.add_argument("--continue-on-error", action="store_true", default=True)
    args = parser.parse_args(argv)

    if args.tasks:
        task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
        for tid in task_ids:
            get(tid)
    else:
        task_ids = [t.task_id for t in all_tasks()]

    print(f"[run_verified] tasks={task_ids} | runs={args.runs} | fail_threshold={args.fail_threshold} | verifier={args.verifier_model}")
    n_total = len(task_ids) * args.runs
    print(f"[run_verified] total runs to perform: {n_total}")

    verifier = Verifier(model=args.verifier_model)
    all_runs: list[TaskRun] = []
    completed = 0
    failed = 0
    t_start = time.time()

    for tid in task_ids:
        for run_idx in range(args.runs):
            label = f"{tid}/verified/{run_idx}"
            if args.skip_existing and already_captured(tid, run_idx):
                existing = load_existing(tid, run_idx)
                if existing:
                    all_runs.append(existing)
                    completed += 1
                    elapsed = time.time() - t_start
                    print(f"[{completed:>2}/{n_total}] [skip-existing] {label} status={existing.final_status} | elapsed={elapsed:.0f}s")
                    continue
            try:
                run = await run_one(tid, run_idx, verifier, args.fail_threshold)
                all_runs.append(run)
                completed += 1
                # Count how many steps got verifier verdicts
                with_verdict = sum(1 for s in run.steps if s.verifier_verdict is not None)
                replans = sum(1 for s in run.steps if s.verifier_verdict and s.verifier_verdict.verdict == "fail")
                elapsed = time.time() - t_start
                print(f"[{completed:>2}/{n_total}] [done] {label} status={run.final_status} steps={len(run.steps)} verified_steps={with_verdict} fail_verdicts={replans} | elapsed={elapsed:.0f}s")
            except Exception as e:
                failed += 1
                print(f"[{completed:>2}/{n_total}] [FAIL] {label} {e!r}", file=sys.stderr)
                if not args.continue_on_error:
                    raise

    res = write_eval_result(all_runs)
    elapsed = time.time() - t_start
    print(f"\n[run_verified] complete | elapsed={elapsed:.0f}s | runs={len(all_runs)} | failed={failed}")
    print(f"[run_verified] verified_success_rate = {res.verified_success_rate:.2%}")
    print(f"[run_verified] result: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
