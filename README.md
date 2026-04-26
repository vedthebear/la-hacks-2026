# Project Lookout

A grounded verifier for browser-use agents. A second model judges every action a browser agent takes; on failure, the agent replans. Headline result: success rate with verifier minus success rate without, on a 10-task suite.

LA Hacks 2026.

---

## Why

Computer-use agents fail because they don't notice when an action did nothing. Errors compound silently. Lookout closes the loop: after each step, a multimodal Claude looks at the before/after screenshots and asks "did that work?" If no, it tells the agent to try something else.

The whole project is one number, defended by one chart, with one demo video.

---

## Headline

```
[ filled in after the full eval runs ]

  baseline:  XX.X% success on 10 tasks × 3 runs each
  verified:  XX.X% success on 10 tasks × 3 runs each
  delta:     +X.X percentage points

  verifier precision (offline, 50 hand-labeled steps):  XX%
  verifier recall:                                       XX%
```

The live numbers live at `data/results/headline.json` once `make eval-and-dashboard` runs.

---

## Quickstart

You need Python 3.11–3.13, `uv`, and an `ANTHROPIC_API_KEY`.

```bash
git clone <repo> && cd la-hacks-2026
make setup                                # venv + deps + chromium
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
make eval-and-dashboard                   # full eval + HTML report (M8 not built yet)
open dashboard/index.html
```

Want to feel it out first instead of running the full eval (~30 min, ~$15 in API)?

```bash
make smoke                                # 3 tasks × 1 run, both modes, ~5 min, ~$1
```

Or run any single piece:

```bash
.venv/bin/python -m lookout.tasks.definitions --list

.venv/bin/python scripts/capture_one.py --task T03            # one baseline run
.venv/bin/python scripts/capture_verified_one.py --task T03   # one verified run
.venv/bin/python scripts/verify_one.py --task T03 --step 3    # judge a single step
```

---

## How it works

```
You run scripts/run_verified.py
        │
        ▼
loop.py:VerifiedTrajectoryCapture
        │  starts a browser-use Agent on a task
        │
        │  per step:
        │    agent decides action      ──► trajectory.py records (intent, action, before-screenshot)
        │    agent executes action     ──► trajectory.py captures (after-screenshot, after-url, pixel-diff)
        │    loop.py asks verifier.py  ──► Verdict {pass | fail | uncertain, confidence, reason, recommend}
        │    if confident fail         ──► agent.add_new_task("VERIFIER FEEDBACK: ...") so next step replans
        │
        │  on done: writes data/trajectories/{task}/verified/{run}/run.json
        ▼
run_verified.py aggregates → data/results/verified.json
compute_metrics.py combines baseline + verified → data/results/headline.json
report.py renders headline + per-step screenshots → dashboard/index.html
```

Two key choices:

- **`browser-use 0.12.6` exposes `register_new_step_callback` and `Agent.run(on_step_end=...)`.** Clean hooks, no monkey-patching. We pair them: the new-step callback gives us the agent's intent + action + before-state; `on_step_end` lets us grab a fresh after-screenshot via `agent.browser_session.take_screenshot()`.
- **Replan via `agent.add_new_task(msg)`.** browser-use exposes a first-class API for adding instructions to a running agent. Our spike (`scripts/spike_replan.py`) confirmed: 3/3 trials, the agent's next action honored injected feedback. So the loop is a real loop, not a placebo.

---

## Repo map

```
lookout/                # the library
  data_models.py        # pydantic shapes: Action, Step, Verdict, TaskRun, EvalResult
  tasks/
    definitions.py      # the 10 tasks (URLs + prompts + success-check name)
    checks.py           # one success-check function per task
    registry.py         # Task class + register helper
  trajectory.py         # CAPTURE: wrap browser-use, record per-step (intent/action/screenshots/url/diff)
  verifier.py           # JUDGE: send screenshots + intent + action to Claude, parse Verdict JSON
  loop.py               # CAPTURE + JUDGE + REPLAN: stamp verdict per step, inject feedback on fail
  diffs.py              # pixel diff helper

scripts/                # entry points (you run these)
  spike_capture.py      # ✅ proved browser-use's hooks give us per-step data
  spike_replan.py       # ✅ proved feedback injection makes the agent change behavior
  capture_one.py        # one baseline run for one task
  capture_verified_one.py  # one verified run for one task
  verify_one.py         # run the verifier against one captured step
  run_baseline.py       # M4: 10 tasks × N runs, vanilla browser-use → baseline.json
  run_verified.py       # M7: 10 tasks × N runs, with verifier-in-loop → verified.json
  compute_metrics.py    # combine baseline + verified → headline.json
  label_steps.py        # CLI for hand-labeling steps for the M5 ground-truth set

data/                   # generated; mostly gitignored
  trajectories/{task_id}/{baseline|verified}/{run_idx}/
    run.json            # all steps + verdicts for one run
    screenshots/        # step_001_before.png, step_001_after.png, ...
  ground_truth/labels.jsonl   # human-labeled (task, mode, run, step) → pass/fail/uncertain
  results/
    baseline.json       # EvalResult for vanilla browser-use
    verified.json       # EvalResult for verifier-in-loop
    offline_verifier.json  # precision/recall/confusion matrix from M5
    headline.json       # the canonical number for the dashboard + writeup

dashboard/              # output of report.py (M8 not built yet)
PLAN.md                 # the full PRD
```

---

## The 10 tasks

All web-only, all on public sites, no auth headaches.

| ID  | What | Site |
|-----|------|------|
| T01 | Find the star count of the browser-use repo | github.com |
| T02 | Look up "photosynthesis" on Wikipedia | en.wikipedia.org |
| T03 | Log in as `tomsmith` / `SuperSecretPassword!` | the-internet.herokuapp.com/login |
| T04 | Log in to saucedemo, add Backpack, go to cart | saucedemo.com |
| T05 | Click Start, wait for "Hello World!" | the-internet.herokuapp.com/dynamic_loading/2 |
| T06 | Return the title of the top story | news.ycombinator.com |
| T07 | Make sure both checkboxes are checked | the-internet.herokuapp.com/checkboxes |
| T08 | Pick "Option 2" from the dropdown | the-internet.herokuapp.com/dropdown |
| T09 | Click "Click for JS Confirm" → OK | the-internet.herokuapp.com/javascript_alerts |
| T10 | Return the points of the top HN story | news.ycombinator.com |

Half come from `the-internet.herokuapp.com` because it was built for exactly this kind of testing.

---

## Status

| Milestone | What | State |
|-----------|------|-------|
| M0 | Repo + deps + Chromium | ✅ |
| M1 | Trajectory capture wrapper | ✅ |
| M2 | Verifier (offline) | ✅ first live call: PASS conf=0.99 on T03 step 3 |
| M3 | All 10 tasks defined | ✅ 10/10 with success checks |
| M4 | `run_baseline.py` (30 runs) | ⏳ script ready, full run not launched |
| M5 | Hand-labeled set + offline verifier eval | ⏳ `label_steps.py` ready; no labels yet; no `run_offline_verifier.py` |
| M6 | `VerifiedAgent` retry loop | ✅ wired end-to-end on T03; `add_new_task` injection 3/3 honored |
| M7 | `run_verified.py` (30 runs) | ⏳ script ready, full run not launched |
| M8 | Static HTML report | ⏳ stub `dashboard/` directory; `report.py` not built |
| M9 | README, demo video, devpost | 🟡 README done; video + devpost pending |

Smoke test (3 tasks × 1 run × both modes) green. Pipeline produces a real `headline.json`.

---

## Conventions

- Pydantic models in `lookout/data_models.py` are the schema source of truth. JSON files conform to `model_dump()`.
- Trajectory directory layout (`data/trajectories/{task_id}/{mode}/{run_index}/`) is never edited by hand.
- Hand labels in `data/ground_truth/labels.jsonl` are append-only; never deleted.
- Entry points are `python scripts/<name>.py` or `python -m lookout.<module>`.
- `ANTHROPIC_API_KEY` lives in `.env` (gitignored). Scripts auto-load via `python-dotenv`.
- Verifier model: `claude-sonnet-4-6` for dev. Re-run final eval with `claude-opus-4-7` if time permits.

---

## Limitations

Honest list, called out before someone else does.

- **Small suite, no confidence intervals.** 10 tasks × 3 runs = 30 trials. A 20pp delta could be noise. The writeup should say so.
- **Verifier model dependency.** Numbers depend on `claude-sonnet-4-6` specifically. Change the model and the precision/recall numbers move.
- **Verifier sees screenshots only.** No DOM diff signal yet (the StepContext fields exist but `dom_nodes_added/removed/changed` are stubbed at 0). For tasks where the relevant change is in invisible DOM (e.g. a hidden input getting filled), the verifier has nothing to look at.
- **`max_actions_per_step=1`** to keep capture clean. Browser-use can do multiple actions per step; we trade some efficiency for one screenshot pair per action.
- **No multi-tab support, no auth, no captchas, no file uploads.** All scoped out per the PRD.
- **The verifier's intent is action-derived, not goal-derived.** We synthesize "Type 'tomsmith' into field at index 8" from the action payload because the agent's `next_goal` describes the broader plan and the verifier needs per-action granularity. The agent's plan rides along as `agent_plan` context for the verifier, but the grade is on the action.

---

## Credits

Wraps [`browser-use`](https://github.com/browser-use/browser-use). Verifier is Claude Sonnet 4.6 via the Anthropic SDK. Built for LA Hacks 2026.
