"""M8: build the static HTML report. Writes dashboard/index.html.

Usage:
    .venv/bin/python scripts/build_report.py
"""
from __future__ import annotations

import sys

from lookout.report import render_report


def main() -> int:
    out = render_report()
    print(f"[report] wrote {out}")
    print(f"[report] open with: open {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
