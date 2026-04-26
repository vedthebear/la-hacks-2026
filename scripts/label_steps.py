"""Hand-label trajectory steps for the offline verifier eval (M5).

Sample 50 (or N) random steps from data/trajectories/, show the user (intent + before/after),
prompt for pass/fail/uncertain, append to data/ground_truth/labels.jsonl.

Append-only. Existing labels are never overwritten; running again skips already-labeled steps.

Usage:
    .venv/bin/python scripts/label_steps.py --n 50
    .venv/bin/python scripts/label_steps.py --n 10 --task T01     # filter to one task
    .venv/bin/python scripts/label_steps.py --resume               # show only un-labeled steps
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path
from typing import Iterator


TRAJ_DIR = Path("data/trajectories")
LABELS_PATH = Path("data/ground_truth/labels.jsonl")


def iter_steps(task_filter: str | None = None) -> Iterator[dict]:
    """Yield {task_id, mode, run_index, step, intent, before, after, source_run} per step."""
    if not TRAJ_DIR.exists():
        return
    for run_json in TRAJ_DIR.glob("*/*/*/run.json"):
        try:
            run = json.loads(run_json.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        task_id = run.get("task_id", "")
        if task_filter and task_id != task_filter:
            continue
        run_dir = run_json.parent
        for step in run.get("steps", []):
            before_rel = step.get("before_screenshot")
            after_rel = step.get("after_screenshot")
            if not before_rel or not after_rel:
                continue
            before_abs = run_dir / before_rel
            after_abs = run_dir / after_rel
            if not before_abs.exists() or not after_abs.exists():
                continue
            yield {
                "task_id": task_id,
                "mode": run.get("mode", "baseline"),
                "run_index": run.get("run_index", 0),
                "step": step.get("step", -1),
                "intent": step.get("intent", "") or "",
                "actions": step.get("actions", []),
                "url_before": step.get("url_before", ""),
                "before": str(before_abs),
                "after": str(after_abs),
                "source_run": str(run_json),
            }


def already_labeled() -> set[tuple]:
    """Set of (task_id, mode, run_index, step) tuples already in labels.jsonl."""
    if not LABELS_PATH.exists():
        return set()
    out = set()
    for line in LABELS_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            out.add((r["task_id"], r["mode"], r["run_index"], r["step"]))
        except (json.JSONDecodeError, KeyError):
            continue
    return out


def show(path: str) -> None:
    """Open the image in the default viewer (macOS: `open`, linux: `xdg-open`)."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", path], check=False)
        else:
            print(f"   (open manually: {path})")
    except Exception as e:
        print(f"   (couldn't open viewer: {e}; path={path})")


def prompt_label() -> tuple[str | None, str]:
    """Returns (label, note). label in {pass, fail, uncertain} or None to skip."""
    while True:
        ans = input("Verdict [p]ass / [f]ail / [u]ncertain / [s]kip / [q]uit: ").strip().lower()
        if ans in ("p", "pass"):
            note = input("Optional note (Enter to skip): ").strip()
            return "pass", note
        if ans in ("f", "fail"):
            note = input("Optional note (Enter to skip): ").strip()
            return "fail", note
        if ans in ("u", "uncertain"):
            note = input("Optional note (Enter to skip): ").strip()
            return "uncertain", note
        if ans in ("s", "skip"):
            return None, ""
        if ans in ("q", "quit"):
            print("Quitting. Existing labels preserved.")
            sys.exit(0)
        print("  enter p, f, u, s, or q")


def main() -> int:
    parser = argparse.ArgumentParser(description="Hand-label trajectory steps for offline verifier eval")
    parser.add_argument("--n", type=int, default=50, help="Target number of steps to label this session")
    parser.add_argument("--task", default=None, help="Filter to one task_id, e.g. T01")
    parser.add_argument("--resume", action="store_true", help="Only show un-labeled steps (default behavior)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for sampling")
    args = parser.parse_args()

    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)

    done = already_labeled()
    pool = [s for s in iter_steps(args.task) if (s["task_id"], s["mode"], s["run_index"], s["step"]) not in done]

    if not pool:
        print(f"No un-labeled steps found in {TRAJ_DIR}. Run baseline first.")
        return 1

    if args.seed is not None:
        random.seed(args.seed)
    random.shuffle(pool)

    target = min(args.n, len(pool))
    print(f"Labeling {target} steps. Already labeled: {len(done)}. Pool: {len(pool)}.")
    print(f"Labels appended to: {LABELS_PATH}")
    print()

    labeled_this_session = 0
    with LABELS_PATH.open("a") as f:
        for i, step in enumerate(pool[:target]):
            print(f"--- [{i + 1}/{target}] {step['task_id']} {step['mode']} run{step['run_index']} step {step['step']}")
            print(f"  intent: {step['intent'][:160]}")
            if step["actions"]:
                print(f"  action: {json.dumps(step['actions'][0])[:160]}")
            print(f"  url:    {step['url_before'][:160]}")
            print(f"  before: {step['before']}")
            print(f"  after:  {step['after']}")
            show(step["before"])
            show(step["after"])
            label, note = prompt_label()
            if label is None:
                print("  (skipped)")
                continue
            record = {
                "task_id": step["task_id"],
                "mode": step["mode"],
                "run_index": step["run_index"],
                "step": step["step"],
                "intent": step["intent"],
                "ground_truth_label": label,
                "note": note,
            }
            f.write(json.dumps(record) + "\n")
            f.flush()
            labeled_this_session += 1
            print(f"  -> {label}")

    print(f"\nDone. Labeled {labeled_this_session} this session.")
    print(f"Total labels in {LABELS_PATH}: {len(already_labeled())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
