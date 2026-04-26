"""M8: render a single-file HTML report from results + trajectories.

Reads:
    data/results/headline.json     (canonical numbers)
    data/results/baseline.json     (eval-level baseline)
    data/results/verified.json     (eval-level verified)
    data/trajectories/{task}/{mode}/{run}/run.json + screenshots/

Writes:
    dashboard/index.html           (self-contained HTML; loads screenshots from dashboard/data/)
    dashboard/data/                (screenshots copied here so file:// loads work)

Design notes:
- One file. Jinja2 template inlined in this module. Inline CSS, no JS.
- For each (task, mode), shows ONE drill-down (run 0 by default), not all 3 runs.
  60 runs × ~5 steps × 2 screenshots is too noisy for a demo; surface the best contrast.
- "Flagship" tasks (where verified rate > baseline rate) are highlighted at the top.
- Color: green/red/amber for pass/fail/uncertain. Otherwise greyscale.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Template


REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "data" / "results"
TRAJ_DIR = REPO_ROOT / "data" / "trajectories"
DASHBOARD_DIR = REPO_ROOT / "dashboard"
DASHBOARD_DATA_DIR = DASHBOARD_DIR / "data"


# --- Template -----------------------------------------------------------------

TEMPLATE = Template(r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Project Lookout — Results</title>
<style>
  :root {
    --bg: #0f0f10;
    --bg-card: #18181b;
    --fg: #f5f5f5;
    --fg-dim: #a1a1aa;
    --border: #27272a;
    --pass: #22c55e;
    --fail: #ef4444;
    --uncertain: #f59e0b;
    --accent: #60a5fa;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--fg);
    line-height: 1.45;
  }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 32px 24px; }
  h1 { font-size: 28px; margin: 0 0 4px; }
  h2 { font-size: 20px; margin: 48px 0 16px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
  h3 { font-size: 15px; margin: 24px 0 8px; color: var(--fg-dim); font-weight: 500; }
  .subtitle { color: var(--fg-dim); margin: 0 0 32px; }

  /* Hero stat strip */
  .hero {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1fr;
    gap: 16px;
    margin: 24px 0;
  }
  .stat {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px 24px;
  }
  .stat .label { color: var(--fg-dim); font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
  .stat .value { font-size: 36px; font-weight: 600; line-height: 1.1; margin-top: 6px; font-variant-numeric: tabular-nums; }
  .stat .sub { color: var(--fg-dim); font-size: 12px; margin-top: 4px; }
  .stat.headline .value { font-size: 48px; }
  .stat.headline.positive .value { color: var(--pass); }
  .stat.headline.negative .value { color: var(--fail); }
  .stat.headline.zero    .value { color: var(--fg-dim); }

  /* Per-task summary table */
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }
  th { color: var(--fg-dim); font-weight: 500; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; }
  td.num { text-align: right; }
  td.delta-pos { color: var(--pass); font-weight: 600; }
  td.delta-neg { color: var(--fail); font-weight: 600; }
  td.delta-zero { color: var(--fg-dim); }
  .task-id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--accent); }

  /* Run drilldowns */
  .run {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    margin: 16px 0;
  }
  .run-header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 4px; }
  .run-header .id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 14px; color: var(--accent); }
  .run-header .mode { font-size: 11px; padding: 2px 8px; border-radius: 4px; background: var(--border); color: var(--fg-dim); text-transform: uppercase; letter-spacing: 0.05em; }
  .run-header .status { font-size: 11px; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; letter-spacing: 0.05em; }
  .status.success { background: rgba(34, 197, 94, 0.15); color: var(--pass); }
  .status.failure { background: rgba(239, 68, 68, 0.15); color: var(--fail); }
  .status.error, .status.timeout { background: rgba(245, 158, 11, 0.15); color: var(--uncertain); }
  .run-task { color: var(--fg-dim); font-size: 13px; margin: 2px 0 16px; }

  .step {
    border-top: 1px solid var(--border);
    padding: 16px 0;
  }
  .step:first-child { border-top: none; padding-top: 0; }
  .step-meta { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
  .step-num { font-weight: 600; font-size: 14px; }
  .step-intent { color: var(--fg); font-size: 13px; flex: 1; min-width: 0; }
  .verdict {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .verdict.pass { background: rgba(34, 197, 94, 0.15); color: var(--pass); }
  .verdict.fail { background: rgba(239, 68, 68, 0.15); color: var(--fail); }
  .verdict.uncertain { background: rgba(245, 158, 11, 0.15); color: var(--uncertain); }
  .verdict.none { background: var(--border); color: var(--fg-dim); }
  .verdict-reason { color: var(--fg-dim); font-size: 12px; margin: 4px 0 8px; }
  .verdict-recommend { color: var(--uncertain); font-size: 12px; font-style: italic; margin: 0 0 8px; }

  .shots { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .shot { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
  .shot .label { font-size: 10px; padding: 6px 10px; color: var(--fg-dim); text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid var(--border); }
  .shot img { display: block; width: 100%; height: auto; }
  .shot.missing { padding: 32px; text-align: center; color: var(--fg-dim); font-size: 12px; }

  .footer { margin-top: 64px; padding-top: 24px; border-top: 1px solid var(--border); color: var(--fg-dim); font-size: 12px; }
  .footer code { background: var(--bg-card); padding: 1px 6px; border-radius: 3px; }
</style>
</head>
<body>
<div class="wrap">

  <h1>Project Lookout</h1>
  <p class="subtitle">A grounded verifier for browser-use agents. {{ summary_line }}</p>

  <!-- Hero stat strip -->
  <div class="hero">
    <div class="stat headline {{ delta_class }}">
      <div class="label">Δ success rate (verified − baseline)</div>
      <div class="value">{{ delta_pp_str }}</div>
      <div class="sub">{{ n_baseline }} baseline runs vs {{ n_verified }} verified runs across {{ n_tasks }} tasks</div>
    </div>
    <div class="stat">
      <div class="label">Baseline</div>
      <div class="value">{{ baseline_rate_pct }}</div>
      <div class="sub">vanilla browser-use</div>
    </div>
    <div class="stat">
      <div class="label">Verified</div>
      <div class="value">{{ verified_rate_pct }}</div>
      <div class="sub">verifier in loop</div>
    </div>
    <div class="stat">
      <div class="label">Verifier accuracy{% if has_offline %}{% else %} (offline){% endif %}</div>
      <div class="value">{{ precision_str }}</div>
      <div class="sub">{{ precision_sub }}</div>
    </div>
  </div>

  <!-- Per-task table -->
  <h2>Per-task breakdown</h2>
  <table>
    <thead>
      <tr>
        <th>Task</th>
        <th>Description</th>
        <th class="num">Baseline</th>
        <th class="num">Verified</th>
        <th class="num">Δ pp</th>
      </tr>
    </thead>
    <tbody>
      {% for row in per_task_rows %}
      <tr>
        <td><span class="task-id">{{ row.task_id }}</span></td>
        <td>{{ row.description }}</td>
        <td class="num">{{ row.baseline_str }}</td>
        <td class="num">{{ row.verified_str }}</td>
        <td class="num {{ row.delta_class }}">{{ row.delta_str }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <!-- Trajectory drilldowns -->
  <h2>Trajectory drilldowns (run 0 of each task)</h2>
  <p class="subtitle">For each task, one baseline run and one verified run shown side by side. Verifier verdicts visible on each step.</p>

  {% for task in task_drilldowns %}
    <h3><span class="task-id">{{ task.task_id }}</span> — {{ task.description }}</h3>

    {% for run in task.runs %}
    <div class="run">
      <div class="run-header">
        <span class="id">{{ run.task_id }} / {{ run.mode }} / run {{ run.run_index }}</span>
        <span class="mode">{{ run.mode }}</span>
        <span class="status {{ run.final_status }}">{{ run.final_status }}</span>
      </div>
      <div class="run-task">{{ run.steps|length }} steps · {{ run.elapsed_str }}</div>

      {% for step in run.steps %}
      <div class="step">
        <div class="step-meta">
          <span class="step-num">step {{ step.step_id }}</span>
          <span class="step-intent">{{ step.intent }}</span>
          {% if step.verifier_verdict %}
            <span class="verdict {{ step.verifier_verdict.verdict }}">{{ step.verifier_verdict.verdict }} · {{ "%.2f"|format(step.verifier_verdict.confidence) }}</span>
          {% else %}
            <span class="verdict none">no verdict</span>
          {% endif %}
        </div>
        {% if step.verifier_verdict and step.verifier_verdict.reason %}
        <div class="verdict-reason">{{ step.verifier_verdict.reason }}</div>
        {% endif %}
        {% if step.verifier_verdict and step.verifier_verdict.recommend %}
        <div class="verdict-recommend">↪ recommend: {{ step.verifier_verdict.recommend }}</div>
        {% endif %}
        <div class="shots">
          {% if step.before_url %}
          <div class="shot"><div class="label">before</div><img src="{{ step.before_url }}" loading="lazy" alt="before step {{ step.step_id }}"/></div>
          {% else %}
          <div class="shot missing">no before screenshot</div>
          {% endif %}
          {% if step.after_url %}
          <div class="shot"><div class="label">after</div><img src="{{ step.after_url }}" loading="lazy" alt="after step {{ step.step_id }}"/></div>
          {% else %}
          <div class="shot missing">no after screenshot</div>
          {% endif %}
        </div>
      </div>
      {% endfor %}

      {% if not run.steps %}
      <p class="subtitle">No steps captured.</p>
      {% endif %}
    </div>
    {% endfor %}
  {% endfor %}

  <div class="footer">
    Generated from <code>data/results/headline.json</code> + <code>data/trajectories/</code>.
    Verifier model: <code>{{ verifier_model }}</code>. Built for LA Hacks 2026.
  </div>

</div>
</body>
</html>""")


# --- Helpers ------------------------------------------------------------------

def _load_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _delta_str(d: float | None) -> str:
    if d is None:
        return "—"
    sign = "+" if d > 0 else ("" if d == 0 else "")
    return f"{sign}{d:.1f}pp"


def _delta_class(d: float | None) -> str:
    if d is None or d == 0:
        return "delta-zero"
    return "delta-pos" if d > 0 else "delta-neg"


def _elapsed(started: str | None, finished: str | None) -> str:
    if not started or not finished:
        return ""
    from datetime import datetime
    try:
        s = datetime.fromisoformat(started)
        f = datetime.fromisoformat(finished)
        secs = int((f - s).total_seconds())
        return f"{secs}s"
    except Exception:
        return ""


def _copy_screenshots(task_id: str, mode: str, run_index: int) -> Path | None:
    """Copy screenshots for one run into dashboard/data/. Returns the dest run dir."""
    src = TRAJ_DIR / task_id / mode / str(run_index) / "screenshots"
    if not src.exists():
        return None
    dest = DASHBOARD_DATA_DIR / task_id / mode / str(run_index) / "screenshots"
    dest.mkdir(parents=True, exist_ok=True)
    for png in src.glob("*.png"):
        shutil.copy2(png, dest / png.name)
    return dest


def _step_view(step: dict, task_id: str, mode: str, run_index: int) -> dict:
    base = f"data/{task_id}/{mode}/{run_index}"
    before_rel = step.get("before_screenshot")
    after_rel = step.get("after_screenshot")
    return {
        "step_id": step.get("step_id", "?"),
        "intent": step.get("intent", "(no intent)"),
        "verifier_verdict": step.get("verifier_verdict"),
        "before_url": f"{base}/{before_rel}" if before_rel else None,
        "after_url": f"{base}/{after_rel}" if after_rel else None,
    }


def _build_per_task_rows(headline: dict, task_descriptions: dict[str, str]) -> list[dict]:
    rows = []
    for entry in headline.get("per_task", []):
        tid = entry["task_id"]
        b_rate = entry.get("baseline_rate")
        v_rate = entry.get("verified_rate")
        delta = None
        if b_rate is not None and v_rate is not None:
            delta = (v_rate - b_rate) * 100
        rows.append({
            "task_id": tid,
            "description": task_descriptions.get(tid, "")[:80],
            "baseline_str": _pct(b_rate),
            "verified_str": _pct(v_rate),
            "delta_str": _delta_str(delta),
            "delta_class": _delta_class(delta),
        })
    # Sort: positive delta first (best wins), then zero, then negative
    def _sort_key(r):
        ds = r["delta_str"]
        if ds == "—": return (3, r["task_id"])
        v = float(ds.replace("pp", "").replace("+", ""))
        if v > 0: return (0, -v, r["task_id"])
        if v < 0: return (2, v, r["task_id"])
        return (1, 0, r["task_id"])
    rows.sort(key=_sort_key)
    return rows


def _gather_drilldowns(headline: dict, task_descriptions: dict[str, str]) -> list[dict]:
    """For each task, load run 0 baseline + run 0 verified; copy their screenshots."""
    drilldowns = []
    for entry in headline.get("per_task", []):
        tid = entry["task_id"]
        runs_view = []
        for mode in ("baseline", "verified"):
            run_dir = TRAJ_DIR / tid / mode / "0"
            run_json_p = run_dir / "run.json"
            if not run_json_p.exists():
                continue
            run = _load_json(run_json_p)
            if not run:
                continue
            _copy_screenshots(tid, mode, 0)
            steps_view = [_step_view(s, tid, mode, 0) for s in run.get("steps", [])]
            runs_view.append({
                "task_id": tid,
                "mode": mode,
                "run_index": 0,
                "final_status": run.get("final_status", "error"),
                "steps": steps_view,
                "elapsed_str": _elapsed(run.get("started_at"), run.get("finished_at")),
            })
        if runs_view:
            drilldowns.append({
                "task_id": tid,
                "description": task_descriptions.get(tid, ""),
                "runs": runs_view,
            })
    return drilldowns


def render_report(verifier_model: str = "claude-sonnet-4-6") -> Path:
    """Build the HTML report. Returns the path to the generated file."""
    headline = _load_json(RESULTS_DIR / "headline.json")
    if not headline:
        # No headline yet — render an empty stub
        headline = {
            "baseline_success_rate": None,
            "verified_success_rate": None,
            "delta_pp": None,
            "n_baseline_runs": 0,
            "n_verified_runs": 0,
            "n_tasks": 0,
            "verifier_pass": 0,
            "verifier_fail": 0,
            "verifier_uncertain": 0,
            "per_task": [],
        }

    # Pull task descriptions from the registry
    from .tasks import all_tasks
    task_descriptions = {t.task_id: t.description for t in all_tasks()}

    delta = headline.get("delta_pp")
    if delta is None:
        delta_pp_str, delta_class = "—", "zero"
    elif delta > 0:
        delta_pp_str, delta_class = f"+{delta:.1f}pp", "positive"
    elif delta < 0:
        delta_pp_str, delta_class = f"{delta:.1f}pp", "negative"
    else:
        delta_pp_str, delta_class = "0.0pp", "zero"

    has_offline = "verifier_precision" in headline and headline["verifier_precision"] is not None
    if has_offline:
        precision_str = _pct(headline["verifier_precision"])
        recall = headline.get("verifier_recall")
        precision_sub = f"recall {_pct(recall)} on {headline.get('n_offline_labels', '?')} hand-labeled steps"
    else:
        # Show in-loop verdict distribution as a proxy
        n = headline.get("verifier_pass", 0) + headline.get("verifier_fail", 0) + headline.get("verifier_uncertain", 0)
        precision_str = "—"
        if n > 0:
            precision_str = f"{headline['verifier_pass']}/{n}"
            precision_sub = f"in-loop pass rate · offline eval pending (M5)"
        else:
            precision_sub = "no verifier calls yet"

    per_task_rows = _build_per_task_rows(headline, task_descriptions)
    task_drilldowns = _gather_drilldowns(headline, task_descriptions)

    summary_line = ""
    if delta is not None:
        if delta > 0:
            summary_line = f"Adding the verifier improved success rate by {delta:.1f} percentage points."
        elif delta < 0:
            summary_line = f"Adding the verifier reduced success rate by {abs(delta):.1f} percentage points."
        else:
            summary_line = f"On this task suite, the verifier neither helped nor hurt overall success rate."
    else:
        summary_line = "Eval not yet run — placeholder values shown."

    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    out = DASHBOARD_DIR / "index.html"
    out.write_text(TEMPLATE.render(
        summary_line=summary_line,
        delta_pp_str=delta_pp_str,
        delta_class=delta_class,
        baseline_rate_pct=_pct(headline.get("baseline_success_rate")),
        verified_rate_pct=_pct(headline.get("verified_success_rate")),
        n_baseline=headline.get("n_baseline_runs", 0),
        n_verified=headline.get("n_verified_runs", 0),
        n_tasks=headline.get("n_tasks", 0),
        precision_str=precision_str,
        precision_sub=precision_sub,
        has_offline=has_offline,
        per_task_rows=per_task_rows,
        task_drilldowns=task_drilldowns,
        verifier_model=verifier_model,
    ))
    return out
