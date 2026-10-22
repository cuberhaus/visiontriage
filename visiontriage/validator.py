"""Deterministic evidence gate for Findings. No LLM text passes unchecked."""

from __future__ import annotations

import re

from visiontriage.bundle import Bundle
from visiontriage.schemas import Finding, Inspection

VISUAL_WORDS = re.compile(
    r"\b(looks?|appears?|visible|visually|dark|bright|blur|contrast|scratch|crack|stain|spot|colour|color)\b",
    re.IGNORECASE,
)

TAXONOMY = {
    "threshold_miscalibration", "score_overlap", "slice_weakness",
    "quality_confound", "label_noise", "leakage", "unclassified",
}


def validate_findings(findings: list[Finding], bundle: Bundle,
                      inspections: list[Inspection]) -> tuple[list[Finding], list[str]]:
    """Return (valid findings, rejection reasons)."""
    known_ids = set(bundle.by_id())
    inspected = {i.inspection_id: set(i.image_ids) for i in inspections}
    valid: list[Finding] = []
    errors: list[str] = []
    for finding in findings:
        problems: list[str] = []
        if finding.taxonomy not in TAXONOMY:
            problems.append(f"{finding.finding_id}: unknown taxonomy {finding.taxonomy!r}")
        evidence = [e for e in finding.evidence_image_ids if e in known_ids]
        if len(evidence) < 2:
            problems.append(f"{finding.finding_id}: needs >=2 evidence examples in the bundle")
        if not finding.metric_name or finding.metric_value is None:
            problems.append(f"{finding.finding_id}: needs a supporting metric name and value")
        if not finding.actions:
            problems.append(f"{finding.finding_id}: needs at least one Recommended Action")
        claim_text = finding.summary + " " + " ".join(c.text for c in finding.visual_claims)
        has_visual_language = bool(VISUAL_WORDS.search(claim_text))
        cited = {c.inspection_id for c in finding.visual_claims}
        if has_visual_language and not cited:
            problems.append(f"{finding.finding_id}: visual claim without an inspection citation")
        for claim in finding.visual_claims:
            if claim.inspection_id not in inspected:
                problems.append(f"{finding.finding_id}: unknown inspection {claim.inspection_id!r}")
            elif not set(finding.evidence_image_ids) & inspected[claim.inspection_id]:
                problems.append(f"{finding.finding_id}: inspection {claim.inspection_id} does not cover its evidence")
        if problems:
            errors.extend(problems)
        else:
            valid.append(finding)
    return valid, errors
