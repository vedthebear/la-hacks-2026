"""Capture a single VERIFIED task run. Mirror of capture_one.py for the verified path.

Usage:
    .venv/bin/python scripts/capture_verified_one.py --task T03 --run 0
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from lookout.loop import VerifiedTrajectoryCapture  # noqa: E402
from lookout.tasks import get  # noqa: E402
from lookout.verifier import Verifier  # noqa: E402


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="T03")
    parser.add_argument("--run", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--fail-threshold", type=float, default=0.7)
    parser.add_argument("--verifier-model", default="claude-sonnet-4-6")
    args = parser.parse_args(argv)

    task = get(args.task)
    verifier = Verifier(model=args.verifier_model)
    cap = VerifiedTrajectoryCapture(
        task=task,
        verifier=verifier,
        run_index=args.run,
        fail_threshold=args.fail_threshold,
        max_steps=args.max_steps,
    )
    print(f"[verified-capture] {task.task_id} run={args.run} fail_threshold={args.fail_threshold} verifier={args.verifier_model}")
    run = await cap.run()
    print(f"[verified-capture] done | status={run.final_status} | steps={len(run.steps)}")
    print(f"[verified-capture] artifacts: {cap.out_dir}")
    # Per-step verdict summary
    print()
    print("--- verdicts ---")
    for s in run.steps:
        v = s.verifier_verdict
        if v:
            print(f"  step {s.step_id}: {v.verdict.upper()} (conf={v.confidence:.2f}, latency={v.latency_ms}ms)")
            print(f"    reason: {v.reason[:100]}")
            if v.recommend:
                print(f"    recommend: {v.recommend[:100]}")
        else:
            print(f"  step {s.step_id}: <no verdict> (skipped or errored)")
    return 0 if run.final_status in ("success", "failure") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
