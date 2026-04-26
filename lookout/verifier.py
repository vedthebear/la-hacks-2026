"""Verifier: a multimodal Claude judges whether a single action achieved its intent.

Conforms to PLAN.md §The verifier. The system prompt is verbatim from the PRD —
do not paraphrase.
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

from anthropic import Anthropic

from .data_models import Action, StepContext, Verdict


SYSTEM_PROMPT = """You verify whether a single browser action accomplished its stated intent.

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
- Be conservative. Prefer "uncertain" over a wrong "pass"."""


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _b64(path: str | Path) -> str:
    p = Path(path)
    return base64.b64encode(p.read_bytes()).decode("ascii")


def _parse_verdict_json(text: str) -> dict:
    """Pull the first JSON object out of the model output, even if it leaked prose."""
    text = text.strip()
    # Strip code fences if model ignored "no code fences" rule
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(text)
        if not match:
            raise ValueError(f"Verifier returned no JSON: {text[:200]!r}")
        return json.loads(match.group(0))


class Verifier:
    """Stateless verifier. One Anthropic client per instance.

    Usage:
        v = Verifier(model="claude-sonnet-4-6")
        verdict = v.verify(intent, action, "before.png", "after.png", context)
    """

    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 1024):
        self.client = Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def verify(
        self,
        intent: str,
        action: Action,
        before_screenshot_path: str | Path,
        after_screenshot_path: str | Path,
        context: StepContext,
        agent_plan: str | None = None,
    ) -> Verdict:
        before_b64 = _b64(before_screenshot_path)
        after_b64 = _b64(after_screenshot_path)

        plan_line = f"Plan context (for orientation, do NOT grade against this): {agent_plan}\n" if agent_plan else ""
        user_text = (
            f"Intent: {intent}\n"
            f"Action: {action.model_dump_json()}\n"
            f"Context: {context.model_dump_json()}\n"
            f"{plan_line}"
            "\n"
            "[before screenshot attached]\n"
            "[after screenshot attached]"
        )

        t0 = time.monotonic()
        message = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": before_b64,
                            },
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": after_b64,
                            },
                        },
                    ],
                }
            ],
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        # Pull the text out of the response
        text_parts = [b.text for b in message.content if getattr(b, "type", None) == "text"]
        raw = "".join(text_parts).strip()
        parsed = _parse_verdict_json(raw)

        # Coerce + validate via Pydantic
        return Verdict(
            verdict=parsed["verdict"],
            confidence=float(parsed["confidence"]),
            reason=str(parsed["reason"]),
            recommend=parsed.get("recommend"),
            latency_ms=latency_ms,
            model=self.model,
        )
