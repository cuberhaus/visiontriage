"""Findings, actions and inspections: the analyst's output contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Taxonomy = Literal[
    "threshold_miscalibration", "score_overlap", "slice_weakness",
    "quality_confound", "label_noise", "leakage", "unclassified",
]


class RecommendedAction(BaseModel):
    action_id: str
    category: str = Field(description="Machine-scorable category, e.g. 'recalibrate_threshold'")
    title: str
    body: str


class VisualClaim(BaseModel):
    text: str
    inspection_id: str


class Finding(BaseModel):
    finding_id: str
    title: str
    taxonomy: Taxonomy
    summary: str
    slice_dimension: str | None = None
    slice_value: str | None = None
    evidence_image_ids: list[str] = []
    metric_name: str = ""
    metric_value: float | None = None
    visual_claims: list[VisualClaim] = []
    actions: list[RecommendedAction] = []


class Inspection(BaseModel):
    inspection_id: str
    image_ids: list[str]
    observations: list[dict] = []


class FindingsDocument(BaseModel):
    run_id: str
    model: str
    prompt_versions: dict[str, str] = {}
    git_sha: str | None = None
    investigation_complete: bool = True
    findings: list[Finding] = []
    tool_calls: list[dict] = []
