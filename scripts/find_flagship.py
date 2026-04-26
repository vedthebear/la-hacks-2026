"""Scan completed runs and pick the best 'flagship' trajectory for the demo video.

A flagship is a (task, run) where:
  - baseline FAILED on this run, AND
  - verified SUCCEEDED on the same run index, AND
  - the verified run has at least one step where the verifier returned `fail`
    with high confidence and the agent then replanned (most visceral demo)

Falls back to:
  - any (task) where verified rate > baseline rate, even if not on the same run
  - or any verified run with at least one fail verdict (interesting verifier behavior)

Usage:
    .venv/bin/python scripts/find_flagship.py
    .venv/bin/python scripts/find_flagship.py --top 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


TRAJ = Path("data/trajectories")


def load(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def gather() -> dict[str, dict]:
    """Return {task_id: {baseline:[runs], verified:[runs]}}"""
    out: dict[str, dict] = {}
    for run_json in TRAJ.glob("*/*/*/run.json"):
        # path: data/trajectories/{task}/{mode}/{run_idx}/run.json
        task_id = run_json.parts[-4]
        if task_id.endswith("_spike"):
            continue
        mode = run_json.parts[-3]
        run = load(run_json)
        if not run:
            continue
        out.setdefault(task_id, {"baseline": [], "verified": []})
        out[task_id].setdefault(mode, []).append(run)
    return out


def has_fail_verdict(run: dict) -> tuple[bool, dict | None]:
    """True if any step has a fail verdict; return that step too."""
    for s in run.get("steps", []):
        v = s.get("verifier_verdict")
        if v and v.get("verdict") == "fail":
            return True, s
    return False, None


def replan_happened(run: dict) -> bool:
    for s in run.get("steps", []):
        if s.get("verifier_verdict") and s["verifier_verdict"].get("verdict") == "fail":
            return True
    return False


def score_candidate(task_id: str, baseline_runs: list, verified_runs: list) -> tuple[int, dict | None]:
    """Higher score = better demo material."""
    if not verified_runs:
        return 0, None
    score = 0
    chosen = verified_runs[0]
    # +10 if there's a verified run that succeeded AND a baseline run that failed at the same index
    for v in verified_runs:
        if v.get("final_status") != "success":
            continue
        idx = v.get("run_index")
        b_same = next((b for b in baseline_runs if b.get("run_index") == idx), None)
        if b_same and b_same.get("final_status") != "success":
            score += 10
            chosen = v
            break
    # +5 if any verified run had a fail verdict (verifier flexed)
    for v in verified_runs:
        if has_fail_verdict(v)[0]:
            score += 5
            if chosen.get("run_index") != v.get("run_index"):
                chosen = v
            break
    # +3 if any task-level lift (verified has more successes than baseline)
    b_succ = sum(1 for r in baseline_runs if r.get("final_status") == "success")
    v_succ = sum(1 for r in verified_runs if r.get("final_status") == "success")
    if v_succ > b_succ:
        score += 3
    return score, chosen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args()

    data = gather()
    if not data:
        print("[flagship] no trajectories found in data/trajectories", file=sys.stderr)
        return 2

    candidates = []
    for tid, modes in sorted(data.items()):
        score, chosen = score_candidate(tid, modes.get("baseline", []), modes.get("verified", []))
        candidates.append((score, tid, modes, chosen))

    candidates.sort(key=lambda x: -x[0])

    print(f"[flagship] {len(candidates)} task(s) scored. top {args.top}:\n")
    for rank, (score, tid, modes, chosen) in enumerate(candidates[:args.top], 1):
        b_runs = modes.get("baseline", [])
        v_runs = modes.get("verified", [])
        b_succ = sum(1 for r in b_runs if r.get("final_status") == "success")
        v_succ = sum(1 for r in v_runs if r.get("final_status") == "success")
        print(f"--- #{rank} {tid} (score={score}) ---")
        print(f"  baseline: {b_succ}/{len(b_runs)} success, verified: {v_succ}/{len(v_runs)} success")
        if chosen:
            had_fail, fail_step = has_fail_verdict(chosen)
            print(f"  recommended demo run: {tid}/verified/{chosen.get('run_index')} (status={chosen.get('final_status')}, steps={len(chosen.get('steps', []))})")
            if had_fail and fail_step:
                v = fail_step.get("verifier_verdict") or {}
                print(f"  killer step: step {fail_step.get('step_id')} — verifier said FAIL (conf {v.get('confidence', 0):.2f})")
                print(f"     intent: {fail_step.get('intent', '')[:80]}")
                print(f"     reason: {v.get('reason', '')[:80]}")
                print(f"     recommend: {(v.get('recommend') or '')[:80]}")
            else:
                print(f"  (no fail verdict in chosen run; verifier passed everything)")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
