"""Capture a single task run using the production TrajectoryCapture wrapper.

Usage:
    .venv/bin/python scripts/capture_one.py --task T03
    .venv/bin/python scripts/capture_one.py --task T05 --mode baseline --run 1
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from lookout.tasks import get  # noqa: E402
from lookout.trajectory import TrajectoryCapture  # noqa: E402


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="T03", help="Task ID (T01..T10)")
    parser.add_argument("--mode", default="baseline", choices=["baseline", "verified"])
    parser.add_argument("--run", type=int, default=0, help="Run index")
    parser.add_argument("--max-steps", type=int, default=None)
    args = parser.parse_args(argv)

    task = get(args.task)
    cap = TrajectoryCapture(
        task=task,
        mode=args.mode,  # type: ignore[arg-type]
        run_index=args.run,
        max_steps=args.max_steps,
    )
    print(f"[capture] {task.task_id} mode={args.mode} run={args.run} max_steps={cap.max_steps}")
    run = await cap.run()
    print(f"[capture] done | status={run.final_status} | steps={len(run.steps)}")
    print(f"[capture] artifacts: {cap.out_dir}")
    return 0 if run.final_status in ("success", "failure") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
