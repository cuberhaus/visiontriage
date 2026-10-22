"""Evaluation seam: scorer maths and a one-scenario sweep smoke run."""

import json

from evals.run_eval import run_sweep
from evals.scorer import aggregate, score_scenario, score_visual, select_default
from visiontriage.analysts import FakeAnalyst
from visiontriage.bundle import load_bundle
from visiontriage.fixtures import EXPECTED, build_fixture


def _finding(**overrides):
    base = {
        "finding_id": "F1", "title": "t", "taxonomy": "slice_weakness",
        "summary": "s", "slice_dimension": "category", "slice_value": "screw",
        "evidence_image_ids": [], "metric_name": "error_rate", "metric_value": 0.5,
        "visual_claims": [],
        "actions": [{"action_id": "A1", "category": "collect_data",
                     "title": "t", "body": "b"}],
    }
    base.update(overrides)
    return base


def _screw_fn_ids(bundle, count=2):
    return [p.image_id for p in bundle.predictions
            if p.category == "screw" and p.is_anomaly and p.score < 0.5][:count]


def test_score_scenario_matches_taxonomy_slice_evidence_action(tmp_path):
    bundle = load_bundle(build_fixture("slice_weakness", tmp_path / "fx"))
    finding = _finding(evidence_image_ids=_screw_fn_ids(bundle))
    row = score_scenario(EXPECTED["slice_weakness"], [finding], bundle)
    assert row["matched"] is True
    assert row["evidence_relevant"] == 2 and row["evidence_cited"] == 2
    assert row["action_correct"] is True


def test_score_scenario_slice_mismatch_and_bad_evidence(tmp_path):
    bundle = load_bundle(build_fixture("slice_weakness", tmp_path / "fx"))
    wrong_slice = _finding(slice_value="bottle",
                           evidence_image_ids=_screw_fn_ids(bundle))
    row = score_scenario(EXPECTED["slice_weakness"], [wrong_slice], bundle)
    assert row["matched"] is False

    bottle_errors = [p.image_id for p in bundle.predictions
                     if p.category == "bottle"][:2]
    wrong_evidence = _finding(evidence_image_ids=bottle_errors)
    row = score_scenario(EXPECTED["slice_weakness"], [wrong_evidence], bundle)
    assert row["matched"] is True
    assert row["evidence_relevant"] == 0  # bottle examples are not screw errors


def test_aggregate_hand_computed():
    rows = [
        {"matched": True, "total_findings": 1, "evidence_relevant": 2,
         "evidence_cited": 2, "action_correct": True, "structured_ok": True,
         "budget_ok": True, "used_fallback": False, "latency_s": 2.0},
        {"matched": False, "total_findings": 2, "evidence_relevant": 0,
         "evidence_cited": 0, "action_correct": False, "structured_ok": True,
         "budget_ok": True, "used_fallback": False, "latency_s": 4.0},
    ]
    summary = aggregate(rows)
    assert summary["failure_mode_precision"] == round(1 / 3, 4)
    assert summary["failure_mode_recall"] == 0.5
    assert summary["failure_mode_f1"] == 0.4
    assert summary["evidence_precision"] == 1.0
    assert summary["action_accuracy"] == 1.0
    assert summary["mean_latency_s"] == 3.0


def test_visual_scoring_keywords():
    result = score_visual([
        {"attributes": ["crack"], "observed_text": "A visible crack line across the surface"},
        {"attributes": ["clean"], "observed_text": "Clean uniform surface, no defect"},
        {"attributes": ["dark"], "observed_text": "Bright and sharp"},
    ])
    assert result == {"cases": 3, "correct": 2, "accuracy": round(2 / 3, 4)}


def test_selection_rule_eliminates_and_profiler_can_win():
    summaries = {
        "profiler": {"failure_mode_f1": 0.5, "evidence_precision": 0.9,
                     "action_accuracy": 0.5, "structured_success": 1.0,
                     "budget_compliance": 1.0, "mean_latency_s": 1.0},
        "weak-llm": {"failure_mode_f1": 0.4, "evidence_precision": 0.9,
                     "action_accuracy": 0.9, "structured_success": 1.0,
                     "budget_compliance": 1.0, "mean_latency_s": 5.0},
        "broken-llm": {"failure_mode_f1": 0.9, "evidence_precision": 0.9,
                       "action_accuracy": 0.9, "structured_success": 0.8,
                       "budget_compliance": 1.0, "mean_latency_s": 5.0},
    }
    decision = select_default(summaries)
    assert decision["default"] == "profiler"  # no LLM beats the baseline F1
    assert "broken-llm" in decision["eliminated"]


def test_selection_rule_picks_winning_llm():
    summaries = {
        "profiler": {"failure_mode_f1": 0.3, "evidence_precision": 0.9,
                     "action_accuracy": 0.5, "structured_success": 1.0,
                     "budget_compliance": 1.0, "mean_latency_s": 1.0},
        "good-llm": {"failure_mode_f1": 0.8, "evidence_precision": 0.8,
                     "action_accuracy": 0.7, "structured_success": 1.0,
                     "budget_compliance": 1.0, "mean_latency_s": 9.0,
                     "visual_accuracy": 0.6},
    }
    decision = select_default(summaries)
    assert decision["default"] == "good-llm"
    assert decision["visual_status"]["good-llm"] == "unverified"


def test_runner_smoke_one_scenario_fake(tmp_path):
    from visiontriage import tools

    def local_caller(bundle, tool, args):
        return getattr(tools, tool)(bundle, **args)

    out = tmp_path / "results"
    result = run_sweep(["fake"], out, scenarios=("slice_weakness",),
                       tool_caller=local_caller,
                       analyst_factory=lambda _name: FakeAnalyst())
    assert (out / "results.json").is_file()
    assert "fake" in (out / "RESULTS.md").read_text()
    assert result["summaries"]["fake"]["scenarios"] == 1
    row = json.loads((out / "results.json").read_text())["rows"][0]
    assert row["candidate"] == "fake" and row["scenario"] == "slice_weakness"
