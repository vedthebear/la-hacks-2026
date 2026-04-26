"""Run the verifier against a single captured step. M2 acceptance script.

Usage:
    .venv/bin/python scripts/verify_one.py
    .venv/bin/python scripts/verify_one.py --task T03 --step 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from lookout.data_models import Action, StepContext  # noqa: E402
from lookout.verifier import Verifier  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="T03")
    parser.add_argument("--mode", default="baseline")
    parser.add_argument("--run", type=int, default=0)
    parser.add_argument("--step", type=int, default=3, help="step_id to verify")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    args = parser.parse_args(argv)

    run_path = Path(f"data/trajectories/{args.task}/{args.mode}/{args.run}/run.json")
    if not run_path.exists():
        print(f"no trajectory at {run_path}; capture first", file=sys.stderr)
        return 2

    run = json.loads(run_path.read_text())
    step = next((s for s in run["steps"] if s["step_id"] == args.step), None)
    if step is None:
        print(f"step {args.step} not found in {run_path}", file=sys.stderr)
        return 2

    base = run_path.parent
    before = base / step["before_screenshot"]
    after = base / step["after_screenshot"]
    print(f"[verify] {args.task} step {args.step}")
    print(f"  intent: {step['intent']}")
    print(f"  action: {step['action']['type']} (raw: {step['action']['target'].get('raw_type')})")
    print(f"  before: {before}")
    print(f"  after:  {after}")

    action = Action.model_validate(step["action"])
    context = StepContext.model_validate(step["context"])

    v = Verifier(model=args.model)
    verdict = v.verify(step["intent"], action, before, after, context)
    print()
    print(f"[verdict] {verdict.verdict.upper()} | confidence={verdict.confidence:.2f} | latency={verdict.latency_ms}ms | model={verdict.model}")
    print(f"  reason: {verdict.reason}")
    if verdict.recommend:
        print(f"  recommend: {verdict.recommend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
