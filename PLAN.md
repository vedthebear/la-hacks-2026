# Project Lookout — PRD

A grounded verifier for browser-use agents. Hackathon scope, ~20 hours of focused work.

## How to use this doc with Claude Code

This is the single source of truth. Drop it at the repo root as `PRD.md` (or `CLAUDE.md`). Then feed Claude Code one milestone at a time from the **Build order** section. Each milestone has explicit acceptance criteria. Don't let it skip ahead.

---

## TL;DR

A second model judges every action a browser agent takes. Wrap [browser-use](https://github.com/browser-use/browser-use). After each step, send (intent, action, before-screenshot, after-screenshot) to a verifier that returns `{verdict, confidence, reason, recommend}`. On `fail`, the agent replans. Headline result: success rate with verifier minus success rate without, on a 10-task suite.

## Why this exists

Computer-use agents fail because they don't notice when an action did nothing. Errors compound silently. A grounded verifier closes the loop. The eval produces one number that demonstrates the effect; the dashboard gives a credible demo surface.

---

## Goals & non-goals

**Goals**
- Headline metric: $\Delta = \text{success}_{\text{verified}} - \text{success}_{\text{baseline}}$ on the 10-task suite, in percentage points.
- Secondary metric: verifier precision and recall on a 50-step hand-labeled set.
- Demo artifact: static dashboard showing per-step verifier judgments and the headline stat strip.

**Non-goals**
- Not training a model.
- Not building a new agent from scratch.
- Not integrating WebArena, OSWorld, or any benchmark harness.
- Not handling auth, captchas, or sites with serious bot detection.
- Not optimizing for latency or cost.

---

## Stack

- Python 3.11+
- `browser-use` (latest, pinned in `requirements.txt`)
- `anthropic` Python SDK for verifier calls
- `pydantic` v2 for data models
- `playwright` (transitive via browser-use) for screenshot/DOM access
- React + Vite + Tailwind for the dashboard
- JSON files in `data/` as the storage layer (no DB, no server)

---

## Repo layout

```
lookout/
├── PRD.md                         # this doc
├── README.md                      # how to run, headline number, demo gif
├── pyproject.toml
├── requirements.txt
├── lookout/                       # python package
│   ├── __init__.py
│   ├── data_models.py             # pydantic models
│   ├── trajectory.py              # capture wrapper around browser-use Agent
│   ├── verifier.py                # VLM verifier
│   ├── loop.py                    # online retry loop
│   ├── eval_runner.py             # run a suite, dump JSONs
│   └── tasks/
│       ├── __init__.py
│       ├── registry.py            # task registration helpers
│       └── definitions.py         # the 10 tasks
├── data/
│   ├── trajectories/              # per-task JSON + screenshots
│   ├── ground_truth/
│   │   └── labels.jsonl           # hand-labeled steps
│   └── results/                   # eval result JSONs
├── dashboard/                     # vite/react app
│   ├── package.json
│   ├── index.html
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── StatStrip.tsx
│   │   │   ├── TaskList.tsx
│   │   │   ├── TrajectoryView.tsx
│   │   │   └── VerdictCard.tsx
│   │   └── data.ts
│   └── public/
│       └── data/                  # symlink or copy of /data at build time
├── scripts/
│   ├── run_baseline.py            # phase A
│   ├── run_offline_verifier.py    # phase B
│   ├── run_verified.py            # phase C
│   ├── compute_metrics.py         # phase D
│   └── label_steps.py             # CLI for hand-labeling
└── tests/
```

---

## Data models

`lookout/data_models.py`. Pydantic v2. These are the contract for everything else.

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

class Action(BaseModel):
    type: Literal["click", "type", "scroll", "navigate", "wait", "extract", "select", "press_key"]
    target: dict           # selector, coords, role, etc.
    payload: dict | None = None  # text to type, URL, key name, etc.

class StepContext(BaseModel):
    url_before: str
    url_after: str
    pixel_diff_pct: float
    dom_nodes_added: int
    dom_nodes_removed: int
    dom_nodes_changed: int

class Verdict(BaseModel):
    verdict: Literal["pass", "fail", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    recommend: str | None = None
    latency_ms: int
    model: str

class Step(BaseModel):
    step_id: int
    timestamp: datetime
    intent: str            # agent's stated intent for this single action
    action: Action
    before_screenshot: str # path under data/trajectories/.../screenshots/
    after_screenshot: str
    context: StepContext
    verifier_verdict: Verdict | None = None
    ground_truth_label: Literal["pass", "fail", "uncertain"] | None = None

class TaskRun(BaseModel):
    task_id: str
    task_description: str
    mode: Literal["baseline", "verified"]
    run_index: int         # 0, 1, 2 for triplicate
    steps: list[Step]
    final_status: Literal["success", "failure", "timeout", "error"]
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime

class EvalResult(BaseModel):
    suite_name: str
    runs: list[TaskRun]
    baseline_success_rate: float | None = None
    verified_success_rate: float | None = None
    delta_pp: float | None = None
    verifier_precision: float | None = None
    verifier_recall: float | None = None
    verifier_accuracy: float | None = None
```

JSON serialization: `TaskRun.model_dump_json(indent=2)`. Files are the source of truth.

---

## The verifier

`lookout/verifier.py`. The interface:

```python
from anthropic import Anthropic

class Verifier:
    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.client = Anthropic()
        self.model = model

    def verify(
        self,
        intent: str,
        action: Action,
        before_screenshot_path: str,
        after_screenshot_path: str,
        context: StepContext,
    ) -> Verdict:
        ...
```

### Prompt

System message (verbatim, do not paraphrase):

```
You verify whether a single browser action accomplished its stated intent.

Inputs you receive:
1. Intent: what the agent intended this single action to do.
2. Action: the action executed (e.g. click on selector X).
3. Before screenshot: page state immediately before the action.
4. After screenshot: page state immediately after the action.
5. Context: URL change, pixel diff, DOM diff counts.

Output strict JSON only. No code fences. No prose. Schema:
{
  "verdict": "pass" | "fail" | "uncertain",
  "confidence": <float between 0 and 1>,
  "reason": "<1 to 2 sentences>",
  "recommend": "<1 sentence or null>"
}

Rules:
- "pass": the intended state change is clearly visible in the after screenshot.
- "fail": the page contradicts the intent. Examples: no visible change, error or validation message appeared, wrong page loaded, expected element absent.
- "uncertain": evidence is insufficient.
- "confidence" is how sure you are of your verdict, not how sure you are the action succeeded.
- "recommend" is non-null only when verdict is "fail" or "uncertain". One sentence describing what to try next.
- Be conservative. Prefer "uncertain" over a wrong "pass".
```

User message:
```
Intent: {intent}
Action: {action.model_dump_json()}
Context: {context.model_dump_json()}

[before screenshot attached]
[after screenshot attached]
```

Use Anthropic's image content block format. Both screenshots are sent as base64 PNG.

### Verifier acceptance test

Given the same recorded step run through `Verifier.verify()` 3 times in a row, verdicts must agree at least 2 of 3 times. If not, the prompt is unstable and needs revision.

---

## Trajectory capture

`lookout/trajectory.py`. The capture wrapper hooks into `browser-use`'s `Agent` lifecycle.

`browser-use` exposes step-level callbacks. The exact API may have shifted between versions. **Required behavior** regardless of API surface:

1. Before each action: capture screenshot, page URL, and serialized DOM snapshot. Save screenshot to `data/trajectories/{task_id}/{mode}/{run_index}/step_{n:03d}_before.png`.
2. After each action: capture the same. Save as `step_{n:03d}_after.png`.
3. Capture the agent's structured action and stated intent. (browser-use surfaces this in its action history; if the field is internal, monkey-patch the agent's `step()` method.)
4. Compute `StepContext` (pixel diff, DOM diff). Helpers go in `lookout/diffs.py`.
5. Append a `Step` to the in-memory `TaskRun`.
6. On task end: write `TaskRun.model_dump_json()` to `data/trajectories/{task_id}/{mode}/{run_index}/run.json`.

### Capture acceptance test

Run T01 (`browser-use repo star count`) end to end. Inspect `run.json`:
- `len(steps) > 0`
- Every step has both screenshot files on disk
- Every step has a non-empty `intent`
- `final_status` is one of the four enum values

---

## Online retry loop

`lookout/loop.py`.

```python
class VerifiedAgent:
    def __init__(
        self,
        agent,                # browser_use.Agent instance
        verifier: Verifier,
        max_retries_per_step: int = 1,
        fail_threshold: float = 0.7,
    ):
        ...

    async def run(self) -> TaskRun:
        ...
```

### Logic

For each agent step:
1. Run the action.
2. Capture trajectory data.
3. Call `verifier.verify(...)`.
4. If `verdict == "pass"` or `verdict == "uncertain"` (any confidence): proceed.
5. If `verdict == "fail"` and `confidence > fail_threshold`:
   - If retries remaining for this step: inject a system message into the agent's next turn and let the agent replan.
   - If no retries: proceed but flag in the `Step`.

### Replan injection format

```
VERIFIER FEEDBACK: Your previous action was judged to have failed.
Reason: {verdict.reason}
Suggested next action: {verdict.recommend}
Replan and try again.
```

### Caps
- Max retries per step: 1
- Max total steps per task: 30
- Hard timeout per task: 5 minutes wall clock

---

## Task suite

`lookout/tasks/definitions.py`. 10 tasks. Each task is:

```python
class Task(BaseModel):
    task_id: str
    description: str       # the prompt given to the agent
    starting_url: str
    success_check_name: str  # name of a function in tasks/checks.py
    timeout_steps: int = 30
```

`lookout/tasks/checks.py` contains pure functions:

```python
def check_T01_browser_use_stars(final_url: str, page_text: str) -> bool:
    # returns True if page_text contains a number on the browser-use repo page
```

### The 10 tasks

| ID | Description | Starting URL | Success check |
|----|-------------|--------------|----------------|
| T01 | Find the star count of the browser-use/browser-use repository on GitHub. | github.com | URL on github.com/browser-use/browser-use, page contains a number near the "Stars" label |
| T02 | Search Wikipedia for "photosynthesis" and return the first sentence of the article. | wikipedia.org | URL contains `/wiki/Photosynthesis` |
| T03 | On the-internet.herokuapp.com/login, log in with username `tomsmith` and password `SuperSecretPassword!`. | the-internet.herokuapp.com/login | URL ends with `/secure` |
| T04 | On saucedemo.com, log in as `standard_user` with password `secret_sauce`, add the "Sauce Labs Backpack" to the cart, then go to the cart. | saucedemo.com | URL ends with `/cart.html` and page contains "Sauce Labs Backpack" |
| T05 | On the-internet.herokuapp.com/dynamic_loading/2, click the Start button and wait for "Hello World!" to appear. | the-internet.herokuapp.com/dynamic_loading/2 | Page contains "Hello World!" |
| T06 | Return the title of the top story on Hacker News. | news.ycombinator.com | URL is `news.ycombinator.com`, agent returns a non-empty string |
| T07 | On the-internet.herokuapp.com/checkboxes, ensure both checkboxes are checked. | the-internet.herokuapp.com/checkboxes | Both `input[type=checkbox]` are checked |
| T08 | On the-internet.herokuapp.com/dropdown, select "Option 2". | the-internet.herokuapp.com/dropdown | Selected option is "Option 2" |
| T09 | On the-internet.herokuapp.com/javascript_alerts, click "Click for JS Confirm" and accept the dialog. | the-internet.herokuapp.com/javascript_alerts | `#result` text equals "You clicked: Ok" |
| T10 | Return the points (score) of the top story on Hacker News. | news.ycombinator.com | Agent returns a numeric value |

### Task suite acceptance test

Each task can be invoked individually:
```
python -m lookout.eval_runner --task T03 --mode baseline --run 0
```
And the resulting `run.json` either passes the success check or fails cleanly with a recorded reason.

---

## Eval methodology

Four phases. Each phase produces a JSON artifact under `data/results/`.

### Phase A: Baseline

`scripts/run_baseline.py`. For each task in {T01..T10}, run vanilla browser-use 3 times. Save trajectories.

Output: `data/results/baseline.json` (an `EvalResult` with `baseline_success_rate` populated).

Headline: $\text{success}_{\text{baseline}} = \frac{\text{successful runs}}{30}$.

### Phase B: Offline verifier eval

`scripts/run_offline_verifier.py` and `scripts/label_steps.py`.

1. Pool all steps from Phase A trajectories.
2. Sample 50 steps uniformly at random.
3. Hand-label each one (`scripts/label_steps.py` is a CLI that shows screenshots + intent and prompts y/n/u).
4. Run the verifier on each labeled step. Compare to ground truth.

Output: `data/results/offline_verifier.json` with `verifier_precision`, `verifier_recall`, `verifier_accuracy`, and a confusion matrix.

### Phase C: Online (in-loop) eval

`scripts/run_verified.py`. Same task suite, 3 runs each, but using `VerifiedAgent`.

Output: `data/results/verified.json` with `verified_success_rate`.

### Phase D: Compute metrics

`scripts/compute_metrics.py`. Reads phases A and C, computes $\Delta$, writes:

`data/results/headline.json`:
```json
{
  "baseline_success_rate": 0.47,
  "verified_success_rate": 0.73,
  "delta_pp": 26.0,
  "verifier_precision": 0.88,
  "verifier_recall": 0.81,
  "n_runs_per_task": 3,
  "n_tasks": 10
}
```

This file is the headline. The dashboard reads it directly.

---

## Build order

Each milestone has an explicit acceptance check. **Don't move on until the check passes.** Time budgets are hackathon estimates, not promises.

| # | Milestone | Acceptance | Time |
|---|-----------|------------|------|
| M0 | Repo skeleton, deps installed, browser-use can launch chromium | `python -c "from browser_use import Agent; print('ok')"` succeeds. `playwright install chromium` succeeds. | 30 min |
| M1 | Trajectory capture wrapper | Run T01 end to end. `data/trajectories/T01/baseline/0/run.json` exists with at least 5 steps, each with both screenshots on disk. | 2 hr |
| M2 | Verifier (offline only) | Hand-pick 5 captured steps, run `Verifier.verify()` on each, get back valid `Verdict` JSON. Verdict on a step where the action obviously worked must be `pass`. | 2 hr |
| M3 | All 10 tasks defined with success checks | `python -m lookout.tasks.definitions --list` prints all 10. Running T03 manually returns a clean `final_status`. | 2 hr |
| M4 | `run_baseline.py` | All 30 runs (10 tasks × 3) complete or fail cleanly. `data/results/baseline.json` exists. | 1 hr (mostly waits) |
| M5 | Offline verifier eval | 50 steps hand-labeled. Verifier run on all 50. `data/results/offline_verifier.json` reports precision and recall. | 3 hr |
| **CHECKPOINT** | **If M5 isn't done by Saturday night, ship M5 only and write up. Skip the rest.** | | |
| M6 | `VerifiedAgent` retry loop | Run T03 once. The trajectory shows at least one step where the verifier ran. If failures occur, replan injection appears in agent context. | 2 hr |
| M7 | `run_verified.py` and headline metric | All 30 verified runs complete. `data/results/headline.json` exists with non-null delta. | 1 hr (mostly waits) |
| M8 | Static dashboard | `cd dashboard && npm run build` produces a dist that, served, shows the stat strip and lets you click into any task and any step. | 4 hr |
| M9 | README, demo gif, Devpost submission | A stranger can clone, follow README, and reproduce headline number. | 2 hr |

Total budget: ~20 hours of focused work. The rest is buffer, breaks, debugging.

### Parallel-build hint

M1 (capture) and M2 (verifier prompt) are independent. Have one Claude Code session work on each in parallel.

---

## Stretch goals (only after M9)

- DOM-diff prefilter that skips verifier calls when `pixel_diff_pct < 0.5%` and DOM nodes changed = 0 (auto-`fail`) or when URL change is in an expected-success allowlist (auto-`pass`).
- Calibration plot: bin verifier predictions by confidence, plot empirical accuracy per bin.
- Latency / accuracy frontier: plot accuracy vs. average per-step verifier compute.
- Add 5 harder tasks (multi-step e-commerce flows, dynamic content).
- Swap verifier model from Sonnet 4.6 to Opus 4.7, compare.

None of these run before M9 ships. They are bonus content for the writeup.

---

## Out of scope

- Multi-tab handling.
- Sites requiring real auth (Gmail, Google, LinkedIn).
- Captcha-protected sites.
- Mobile viewports.
- File uploads.
- Long-form text generation tasks (writing emails, etc.).
- Any task that takes more than 30 steps.

---

## Conventions and read-me-first notes

- Pydantic models are the schema source of truth. JSON files conform to `model_dump()`.
- Trajectory directory structure is **never** edited by hand.
- Hand labels live in `data/ground_truth/labels.jsonl`. Append-only. Never deleted.
- All entry points are `python -m lookout.<module>` or `python scripts/<name>.py`.
- The dashboard reads from `data/` directly via fetch in dev. At build time, `data/` is copied into `dashboard/public/data/`.
- No `.env` checked in. `ANTHROPIC_API_KEY` set in shell.
- Use `claude-sonnet-4-6` for the verifier during development (cheap, fast). Re-run final eval with `claude-opus-4-7` if time permits.

---

## Known browser-use gotchas

- The exact callback API for step-level hooks varies by version. If `Agent` does not expose a usable hook, subclass it and override `step()` directly. Keep the override thin: capture before, call `super().step()`, capture after.
- `browser-use` defaults to `use_vision="auto"`. Force `use_vision=True` for trajectory capture so screenshots are always available.
- `news.ycombinator.com` occasionally rate limits aggressive runs. Add a 2-second delay between T06 and T10 if running back to back.
- The agent sometimes refuses to "extract and return" content as a final action. For tasks that require returning a value (T01, T02, T06, T10), accept any final state where the agent confirms the value is visible on screen.

---

## README.md acceptance test

The repo's README contains:
1. One-paragraph project description.
2. Headline number prominently (a figure or stat strip).
3. A 60-second demo gif of the dashboard.
4. A "How to run" section with three commands or fewer:
   ```
   git clone <repo>
   cd lookout && make setup
   make eval-and-dashboard
   ```
5. A "Limitations" section that names the small task suite, lack of multi-trial confidence intervals, and the verifier's model dependency.

If a stranger cannot reproduce the headline number from the README in 30 minutes, the README has failed.

---

## Appendix A: example task implementation

```python
# lookout/tasks/definitions.py

from .registry import register
from .checks import (
    check_T01_browser_use_stars,
    check_T03_login_secure,
    # ...
)

register(Task(
    task_id="T03",
    description=(
        "Open https://the-internet.herokuapp.com/login. "
        "Log in with the username 'tomsmith' and the password 'SuperSecretPassword!'. "
        "Stop when you have successfully logged in."
    ),
    starting_url="https://the-internet.herokuapp.com/login",
    success_check_name="check_T03_login_secure",
    timeout_steps=15,
))
```

```python
# lookout/tasks/checks.py

def check_T03_login_secure(final_url: str, page_text: str, **kwargs) -> bool:
    return final_url.rstrip("/").endswith("/secure")
```

---

## Appendix B: writeup structure (for after M9)

When the eval is done, write a 600-1000 word post:
1. Hook: the headline number, in one sentence.
2. Problem: agents fail silently. Concrete example.
3. Approach: verifier loop in 3 sentences. One diagram.
4. Results: stat strip, confusion matrix, two interesting failure cases caught.
5. Limitations: small suite, verifier model dependency, no multi-trial CI.
6. Open questions: DOM-diff prefilter, calibration, larger model verifiers.

This post goes on a personal site or as a long Devpost description, plus an X thread that summarizes the result with the dashboard gif.