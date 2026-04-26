"""M5: offline verifier evaluation.

Reads:
    data/ground_truth/labels.jsonl   (human labels: pass/fail/uncertain per step)
    data/trajectories/.../run.json    (the captured trajectories)

Runs the verifier on each labeled step and writes:
    data/results/offline_verifier.json
        - per-step predictions vs ground truth
        - confusion matrix (3x3: pass/fail/uncertain)
        - precision, recall, accuracy (treating the FAIL class as positive,
          since "did the verifier catch a failure the agent missed?" is the
          load-bearing question)
        - per-task breakdown

Usage:
    .venv/bin/python scripts/run_offline_verifier.py
    .venv/bin/python scripts/run_offline_verifier.py --limit 10  # smoke
    .venv/bin/python scripts/run_offline_verifier.py --skip-cached  # don't re-run already-evaluated steps
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from lookout.data_models import Action, StepContext  # noqa: E402
from lookout.diffs import pixel_diff_pct  # noqa: E402
from lookout.verifier import Verifier  # noqa: E402


LABELS_PATH = Path("data/ground_truth/labels.jsonl")
RESULTS_PATH = Path("data/results/offline_verifier.json")
TRAJ_DIR = Path("data/trajectories")


def load_labels() -> list[dict]:
    if not LABELS_PATH.exists():
        return []
    rows = []
    for line in LABELS_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def find_step_in_trajectory(label: dict) -> dict | None:
    """Locate the step record + run.json for a labeled (task, mode, run, step)."""
    run_json = TRAJ_DIR / label["task_id"] / label["mode"] / str(label["run_index"]) / "run.json"
    if not run_json.exists():
        return None
    try:
        run = json.loads(run_json.read_text())
    except Exception:
        return None
    for s in run.get("steps", []):
        if s.get("step_id") == label["step"]:
            return {"run": run, "step": s, "run_dir": run_json.parent}
    return None


def already_predicted(predictions: list[dict], label: dict) -> bool:
    key = (label["task_id"], label["mode"], label["run_index"], label["step"])
    for p in predictions:
        if (p["task_id"], p["mode"], p["run_index"], p["step"]) == key:
            return True
    return False


def confusion_matrix(rows: list[dict]) -> dict:
    """3x3 matrix: rows are ground truth, columns are predicted."""
    classes = ["pass", "fail", "uncertain"]
    m = {gt: {pred: 0 for pred in classes} for gt in classes}
    for r in rows:
        gt = r["ground_truth_label"]
        pred = r["predicted_verdict"]
        if gt in classes and pred in classes:
            m[gt][pred] += 1
    return m


def metrics_for_class(matrix: dict, positive: str) -> dict:
    """Treat `positive` as the positive class; everything else as negative."""
    classes = ["pass", "fail", "uncertain"]
    tp = matrix[positive][positive]
    fp = sum(matrix[gt][positive] for gt in classes if gt != positive)
    fn = sum(matrix[positive][pred] for pred in classes if pred != positive)
    tn = sum(matrix[gt][pred] for gt in classes for pred in classes if gt != positive and pred != positive)

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision,
        "recall": recall,
    }


def overall_accuracy(matrix: dict) -> float | None:
    classes = ["pass", "fail", "uncertain"]
    total = sum(matrix[gt][pred] for gt in classes for pred in classes)
    if total == 0:
        return None
    correct = sum(matrix[c][c] for c in classes)
    return correct / total


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Cap how many labeled steps to verify")
    parser.add_argument("--skip-cached", action="store_true", help="Skip steps already in offline_verifier.json")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    args = parser.parse_args(argv)

    labels = load_labels()
    if not labels:
        print(f"[offline] no labels in {LABELS_PATH}. Run scripts/label_steps.py first.", file=sys.stderr)
        return 2

    # Load existing predictions if --skip-cached
    cached_predictions: list[dict] = []
    if args.skip_cached and RESULTS_PATH.exists():
        try:
            cached = json.loads(RESULTS_PATH.read_text())
            cached_predictions = cached.get("predictions", [])
            print(f"[offline] loaded {len(cached_predictions)} cached predictions")
        except Exception:
            pass

    verifier = Verifier(model=args.model)
    predictions: list[dict] = list(cached_predictions)
    n_to_run = args.limit if args.limit else len(labels)
    t_start = time.time()

    todo = []
    for label in labels:
        if args.skip_cached and already_predicted(cached_predictions, label):
            continue
        todo.append(label)
        if len(todo) >= n_to_run:
            break

    print(f"[offline] {len(todo)} labels to evaluate ({len(labels)} total, {len(cached_predictions)} cached)")

    for i, label in enumerate(todo, 1):
        found = find_step_in_trajectory(label)
        if not found:
            print(f"  [{i}/{len(todo)}] [skip] no trajectory for {label['task_id']}/{label['mode']}/{label['run_index']}/step{label['step']}")
            continue

        run = found["run"]
        step = found["step"]
        run_dir = found["run_dir"]

        before_path = run_dir / step["before_screenshot"] if step.get("before_screenshot") else None
        after_path = run_dir / step["after_screenshot"] if step.get("after_screenshot") else None
        if not before_path or not after_path or not before_path.exists() or not after_path.exists():
            print(f"  [{i}/{len(todo)}] [skip] missing screenshots for {label['task_id']}/step{label['step']}")
            continue

        try:
            action = Action.model_validate(step["action"])
            ctx = StepContext.model_validate(step["context"])
        except Exception as e:
            print(f"  [{i}/{len(todo)}] [skip] invalid schema: {e!r}")
            continue

        # Recompute pixel diff for safety (in case it was stale)
        ctx.pixel_diff_pct = pixel_diff_pct(before_path, after_path)

        try:
            verdict = verifier.verify(
                intent=step.get("intent", ""),
                action=action,
                before_screenshot_path=before_path,
                after_screenshot_path=after_path,
                context=ctx,
                agent_plan=step.get("agent_plan"),
            )
        except Exception as e:
            print(f"  [{i}/{len(todo)}] [error] verifier raised: {e!r}")
            continue

        match = verdict.verdict == label["ground_truth_label"]
        elapsed = time.time() - t_start
        print(f"  [{i}/{len(todo)}] {label['task_id']}/step{label['step']}: gt={label['ground_truth_label']} pred={verdict.verdict} ({verdict.confidence:.2f}) {'✓' if match else '✗'} | elapsed={elapsed:.0f}s")

        predictions.append({
            "task_id": label["task_id"],
            "mode": label["mode"],
            "run_index": label["run_index"],
            "step": label["step"],
            "ground_truth_label": label["ground_truth_label"],
            "predicted_verdict": verdict.verdict,
            "predicted_confidence": verdict.confidence,
            "predicted_reason": verdict.reason,
            "predicted_recommend": verdict.recommend,
            "latency_ms": verdict.latency_ms,
            "model": verdict.model,
            "match": match,
        })

    # Compute metrics
    matrix = confusion_matrix(predictions)
    acc = overall_accuracy(matrix)
    fail_metrics = metrics_for_class(matrix, "fail")
    pass_metrics = metrics_for_class(matrix, "pass")

    out = {
        "n_labels_total": len(labels),
        "n_predictions": len(predictions),
        "model": args.model,
        # Headline numbers (mirror the names compute_metrics.py expects)
        "verifier_accuracy": acc,
        "verifier_precision": fail_metrics["precision"],   # precision on the FAIL class
        "verifier_recall": fail_metrics["recall"],         # recall on the FAIL class
        "n_offline_labels": len(predictions),
        # Detail
        "metrics_by_class": {
            "fail": fail_metrics,
            "pass": pass_metrics,
        },
        "confusion_matrix": matrix,
        "predictions": predictions,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(out, indent=2))
    print(f"\n[offline] wrote {RESULTS_PATH}")
    print(f"  accuracy:           {acc:.2%}" if acc is not None else "  accuracy: n/a")
    print(f"  precision (fail):   {fail_metrics['precision']:.2%}" if fail_metrics["precision"] is not None else "  precision (fail): n/a")
    print(f"  recall    (fail):   {fail_metrics['recall']:.2%}" if fail_metrics["recall"] is not None else "  recall    (fail): n/a")
    print(f"  precision (pass):   {pass_metrics['precision']:.2%}" if pass_metrics["precision"] is not None else "  precision (pass): n/a")
    print(f"  recall    (pass):   {pass_metrics['recall']:.2%}" if pass_metrics["recall"] is not None else "  recall    (pass): n/a")
    print(f"  confusion matrix (rows=truth, cols=pred):")
    classes = ["pass", "fail", "uncertain"]
    print(f"           {''.join(c.rjust(12) for c in classes)}")
    for gt in classes:
        row = "".join(str(matrix[gt][p]).rjust(12) for p in classes)
        print(f"    {gt.rjust(8)}{row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
