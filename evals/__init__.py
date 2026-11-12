"""Evaluation harness: deterministic scoring and the model sweep.

Tier-1 tests exercise the scorer with synthetic findings. The sweep
runner (`python -m evals.run_eval`) is local and manual only — no
model runs in CI.
"""

from evals.scorer import aggregate, score_scenario, select_default

__all__ = ["aggregate", "score_scenario", "select_default"]
