# Lookout — convenience wrappers around the actual Python entry points.
# Real work lives in scripts/. This file just makes the README's commands work.

PY := .venv/bin/python
VENV := .venv

.PHONY: help setup smoke eval-baseline eval-verified eval-and-dashboard report clean clean-trajectories

help:
	@echo "make setup              — venv + deps + chromium (one-time)"
	@echo "make smoke              — 3 tasks × 1 run × both modes (~5 min, ~\$$1)"
	@echo "make eval-baseline      — 10 tasks × 3 vanilla runs"
	@echo "make eval-verified      — 10 tasks × 3 verified runs"
	@echo "make eval-and-dashboard — full eval + report"
	@echo "make report             — regenerate dashboard/index.html from data/results/"
	@echo "make clean              — remove .venv only"
	@echo "make clean-trajectories — remove data/trajectories/ (does NOT touch labels.jsonl)"

$(VENV)/bin/python:
	uv venv --python 3.13 $(VENV)
	uv pip install --python $(VENV)/bin/python -e ".[dev]"
	uv pip install --python $(VENV)/bin/python playwright

setup: $(VENV)/bin/python
	$(PY) -m playwright install chromium
	@echo "✓ setup complete. Make sure ANTHROPIC_API_KEY is in .env"

smoke:
	$(PY) scripts/run_baseline.py --tasks T01,T03,T05 --runs 1 --skip-existing
	$(PY) scripts/run_verified.py --tasks T01,T03,T05 --runs 1 --skip-existing
	$(PY) scripts/compute_metrics.py

eval-baseline:
	$(PY) scripts/run_baseline.py --runs 3 --skip-existing

eval-verified:
	$(PY) scripts/run_verified.py --runs 3 --skip-existing

eval-and-dashboard: eval-baseline eval-verified
	$(PY) scripts/compute_metrics.py
	@if [ -f scripts/build_report.py ]; then $(PY) scripts/build_report.py; \
	else echo "[note] M8 report not built yet; headline.json is in data/results/"; fi

report:
	@if [ -f scripts/build_report.py ]; then $(PY) scripts/build_report.py; \
	else echo "[note] M8 report not built yet"; exit 1; fi

clean:
	rm -rf $(VENV)

clean-trajectories:
	rm -rf data/trajectories
	rm -rf data/results
