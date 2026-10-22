"""Deterministic scoring against planted fixture ground truth.

Metric definitions (fixed before any sweep runs; changing them after
seeing results would invalidate the model-selection rule):

- A Finding *matches* a scenario when its taxonomy equals the planted
  taxonomy and its slice matches the planted slice (an empty planted
  slice matches any slice). At most one match counts per scenario;
  duplicate or non-matching findings count against precision.
- Failure-mode precision = matched scenarios / total findings,
  recall = matched scenarios / scenarios, F1 = their harmonic mean.
- Evidence precision = cited Evidence Examples that are real errors
  (FP/FN at the run threshold) in the planted slice, over all cited
  examples, across matched findings only.
- Action accuracy = matched findings carrying at least one acceptable
  action category, over matched findings.
- Structured-output success and budget compliance are measured by the
  runner from the produced FindingsDocument (see run_eval.py).
"""

from __future__ import annotations

from visiontriage.bundle import Bundle, is_predicted_anomaly
from visiontriage.profiler import _slice_value
from visiontriage.schemas import Finding

BASELINE_CANDIDATES = {"profiler", "fake"}


def _as_finding(raw) -> Finding:
    return raw if isinstance(raw, Finding) else Finding.model_validate(raw)


def _slice_matches(finding: Finding, expected_slice: dict) -> bool:
    if not expected_slice:
        return True
    return (finding.slice_dimension == expected_slice.get("dimension")
            and finding.slice_value == expected_slice.get("value"))


def _is_error(pred, threshold: float) -> bool:
    return pred.is_anomaly != is_predicted_anomaly(pred, threshold)


def _evidence_stats(finding: Finding, expected: dict, bundle: Bundle | None) -> tuple[int, int]:
    cited = finding.evidence_image_ids
    if bundle is None:
        return len(cited), len(cited)
    by_id = bundle.by_id()
    threshold = bundle.metadata.threshold
    expected_slice = expected.get("slice") or {}
    relevant = 0
    for image_id in cited:
        pred = by_id.get(image_id)
        if pred is None or not _is_error(pred, threshold):
            continue
        if expected_slice and _slice_value(pred, expected_slice["dimension"]) != expected_slice["value"]:
            continue
        relevant += 1
    return relevant, len(cited)


def score_scenario(expected: dict, findings: list, bundle: Bundle | None = None) -> dict:
    """Score one scenario's findings against its planted expectation."""
    parsed = [_as_finding(f) for f in findings]
    matched: Finding | None = None
    for finding in parsed:
        if finding.taxonomy == expected["taxonomy"] and _slice_matches(finding, expected.get("slice") or {}):
            matched = finding
            break
    relevant = cited = 0
    action_correct = False
    if matched is not None:
        relevant, cited = _evidence_stats(matched, expected, bundle)
        acceptable = set(expected.get("action_categories") or [])
        action_correct = any(a.category in acceptable for a in matched.actions)
    return {
        "matched": matched is not None,
        "matched_finding_id": matched.finding_id if matched else None,
        "total_findings": len(parsed),
        "evidence_relevant": relevant,
        "evidence_cited": cited,
        "action_correct": action_correct,
    }


def aggregate(rows: list[dict]) -> dict:
    """Aggregate per-scenario runner rows into candidate-level metrics."""
    scenarios = len(rows)
    matched = sum(1 for r in rows if r["matched"])
    total_findings = sum(r["total_findings"] for r in rows)
    cited = sum(r["evidence_cited"] for r in rows)
    relevant = sum(r["evidence_relevant"] for r in rows)
    precision = matched / total_findings if total_findings else 0.0
    recall = matched / scenarios if scenarios else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "scenarios": scenarios,
        "matched": matched,
        "total_findings": total_findings,
        "failure_mode_precision": round(precision, 4),
        "failure_mode_recall": round(recall, 4),
        "failure_mode_f1": round(f1, 4),
        "evidence_precision": round(relevant / cited, 4) if cited else 0.0,
        "action_accuracy": round(
            sum(1 for r in rows if r["action_correct"]) / matched, 4) if matched else 0.0,
        "structured_success": round(
            sum(1 for r in rows if r.get("structured_ok")) / scenarios, 4) if scenarios else 0.0,
        "budget_compliance": round(
            sum(1 for r in rows if r.get("budget_ok")) / scenarios, 4) if scenarios else 0.0,
        "fallback_runs": sum(1 for r in rows if r.get("used_fallback")),
        "mean_latency_s": round(sum(r.get("latency_s", 0.0) for r in rows) / scenarios, 2)
        if scenarios else 0.0,
    }


# --- Visual benchmark -------------------------------------------------------

VISUAL_SYNONYMS = {
    "crack": ("crack", "scratch", "fracture", "line", "break"),
    "contamination": ("contamination", "spot", "stain", "smudge", "blob", "dirty", "dark patch"),
    "dark": ("dark", "underexposed", "low light", "dim", "black"),
    "blur": ("blur", "out of focus", "soft focus", "unsharp", "gradient"),
    "clean": ("clean", "normal", "no defect", "no abnormal", "nothing abnormal",
              "uniform", "plain", "intact"),
}
# Specific defect words only: the generic word "defect" also appears in
# correct clean observations ("no defect visible").
_DEFECT_WORDS = ("crack", "scratch", "spot", "stain", "contamination", "broken")


def visual_case_correct(expected_attribute: str, observed_text: str) -> bool:
    text = observed_text.lower()
    if expected_attribute == "clean":
        return (any(word in text for word in VISUAL_SYNONYMS["clean"])
                and not any(word in text for word in _DEFECT_WORDS))
    return any(word in text for word in VISUAL_SYNONYMS.get(expected_attribute, ()))


def score_visual(cases: list[dict]) -> dict:
    """Cases: {"attributes": [kind], "observed_text": str}."""
    correct = sum(1 for c in cases
                  if c["attributes"] and visual_case_correct(c["attributes"][0],
                                                            c.get("observed_text", "")))
    return {"cases": len(cases), "correct": correct,
            "accuracy": round(correct / len(cases), 4) if cases else 0.0}


# --- Pre-registered selection rule ------------------------------------------


def select_default(summaries: dict[str, dict]) -> dict:
    """Pick the default analyst by the pre-registered rule.

    Eliminate LLM candidates on structured-output success < 100% or
    any budget violation. Rank survivors by failure-mode F1, then
    evidence precision, then action accuracy, then blind human
    usefulness (when every candidate has a rating), then latency.
    If no LLM strictly beats the profiler baseline on F1, the default
    is profiler-only with the LLM optional. Visual accuracy < 80%
    labels a candidate's visual claims unverified (not elimination).
    """
    profiler_f1 = summaries.get("profiler", {}).get("failure_mode_f1", 0.0)
    survivors: dict[str, dict] = {}
    eliminated: dict[str, str] = {}
    for name, summary in summaries.items():
        if name in BASELINE_CANDIDATES:
            continue
        if summary.get("structured_success", 0.0) < 1.0:
            eliminated[name] = "structured-output success < 100%"
        elif summary.get("budget_compliance", 0.0) < 1.0:
            eliminated[name] = "budget violation"
        else:
            survivors[name] = summary

    def visual_status(summary: dict) -> str:
        accuracy = summary.get("visual_accuracy")
        if accuracy is None:
            return "not measured"
        return "verified" if accuracy >= 0.8 else "unverified"

    if not survivors:
        return {"default": "profiler", "eliminated": eliminated,
                "reason": "no LLM candidate survived the elimination gates",
                "visual_status": {n: visual_status(s) for n, s in summaries.items()}}
    blind_complete = all(s.get("blind_rating") is not None for s in survivors.values())

    def rank_key(item):
        _name, s = item
        return (-s["failure_mode_f1"], -s["evidence_precision"], -s["action_accuracy"],
                -(s["blind_rating"] or 0) if blind_complete else 0,
                s["mean_latency_s"])

    best_name, best = sorted(survivors.items(), key=rank_key)[0]
    if best["failure_mode_f1"] <= profiler_f1:
        return {"default": "profiler", "eliminated": eliminated,
                "reason": (f"best LLM {best_name} F1 {best['failure_mode_f1']} does not "
                           f"beat profiler baseline F1 {profiler_f1}; profiler-only "
                           "ships as default, LLM optional"),
                "visual_status": {n: visual_status(s) for n, s in summaries.items()}}
    return {"default": best_name, "eliminated": eliminated,
            "reason": (f"{best_name} beats profiler baseline F1 {profiler_f1} with "
                       f"F1 {best['failure_mode_f1']} and passed all gates"),
            "visual_status": {n: visual_status(s) for n, s in summaries.items()}}
