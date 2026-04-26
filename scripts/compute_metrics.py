"""M-Metrics: compute delta + headline number from baseline + verified results.

Reads:
  data/results/baseline.json   (an EvalResult)
  data/results/verified.json   (an EvalResult)
  data/results/offline_verifier.json (optional; if present, fold in precision/recall)

Writes:
  data/results/headline.json   (the canonical number for the dashboard + writeup)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


BASELINE_PATH = Path("data/results/baseline.json")
VERIFIED_PATH = Path("data/results/verified.json")
OFFLINE_PATH = Path("data/results/offline_verifier.json")
HEADLINE_PATH = Path("data/results/headline.json")


def main() -> int:
    if not BASELINE_PATH.exists():
        print(f"[compute_metrics] missing {BASELINE_PATH} — run scripts/run_baseline.py first", file=sys.stderr)
        return 2
    if not VERIFIED_PATH.exists():
        print(f"[compute_metrics] missing {VERIFIED_PATH} — run scripts/run_verified.py first", file=sys.stderr)
        return 2

    baseline = json.loads(BASELINE_PATH.read_text())
    verified = json.loads(VERIFIED_PATH.read_text())

    bsr = baseline.get("baseline_success_rate")
    vsr = verified.get("verified_success_rate")
    if bsr is None or vsr is None:
        print("[compute_metrics] one of the rates is null — re-run the suite", file=sys.stderr)
        return 2

    delta_pp = round((vsr - bsr) * 100, 2)

    # Per-task breakdown
    n_baseline = len(baseline.get("runs", []))
    n_verified = len(verified.get("runs", []))
    runs_by_task_b: dict[str, list[dict]] = {}
    runs_by_task_v: dict[str, list[dict]] = {}
    for r in baseline.get("runs", []):
        runs_by_task_b.setdefault(r["task_id"], []).append(r)
    for r in verified.get("runs", []):
        runs_by_task_v.setdefault(r["task_id"], []).append(r)

    per_task = []
    all_tasks = sorted(set(runs_by_task_b) | set(runs_by_task_v))
    for tid in all_tasks:
        br = runs_by_task_b.get(tid, [])
        vr = runs_by_task_v.get(tid, [])
        b_succ = sum(1 for r in br if r["final_status"] == "success")
        v_succ = sum(1 for r in vr if r["final_status"] == "success")
        per_task.append({
            "task_id": tid,
            "baseline_runs": len(br),
            "baseline_successes": b_succ,
            "baseline_rate": (b_succ / len(br)) if br else None,
            "verified_runs": len(vr),
            "verified_successes": v_succ,
            "verified_rate": (v_succ / len(vr)) if vr else None,
        })

    # Per-step verifier behavior on verified runs
    n_verified_steps = 0
    n_pass = 0
    n_fail = 0
    n_uncertain = 0
    n_replans = 0
    for r in verified.get("runs", []):
        for s in r.get("steps", []):
            v = s.get("verifier_verdict")
            if not v:
                continue
            n_verified_steps += 1
            if v["verdict"] == "pass":
                n_pass += 1
            elif v["verdict"] == "fail":
                n_fail += 1
            else:
                n_uncertain += 1
            if v.get("recommend"):
                pass  # informational; replan triggered by loop logic, not verdict alone

    headline = {
        "baseline_success_rate": round(bsr, 4),
        "verified_success_rate": round(vsr, 4),
        "delta_pp": delta_pp,
        "n_baseline_runs": n_baseline,
        "n_verified_runs": n_verified,
        "n_tasks": len(all_tasks),
        "verifier_steps_total": n_verified_steps,
        "verifier_pass": n_pass,
        "verifier_fail": n_fail,
        "verifier_uncertain": n_uncertain,
        "per_task": per_task,
    }

    # Fold in offline precision/recall if available
    if OFFLINE_PATH.exists():
        try:
            off = json.loads(OFFLINE_PATH.read_text())
            for k in ("verifier_precision", "verifier_recall", "verifier_accuracy"):
                if k in off:
                    headline[k] = off[k]
            if "confusion_matrix" in off:
                headline["confusion_matrix"] = off["confusion_matrix"]
        except Exception as e:
            print(f"[compute_metrics] couldn't merge offline: {e!r}", file=sys.stderr)

    HEADLINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEADLINE_PATH.write_text(json.dumps(headline, indent=2))
    print(f"\n[compute_metrics] wrote {HEADLINE_PATH}")
    print(f"  baseline:  {bsr:.2%}  ({n_baseline} runs)")
    print(f"  verified:  {vsr:.2%}  ({n_verified} runs)")
    print(f"  delta:     {delta_pp:+.2f} pp")
    if "verifier_precision" in headline:
        print(f"  precision: {headline['verifier_precision']:.2%}")
        print(f"  recall:    {headline['verifier_recall']:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
