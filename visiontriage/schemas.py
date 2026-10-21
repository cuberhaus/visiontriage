"""Shared data shapes for VisionTriage.

These models are the contract between the MCP tools, the LangGraph state
machine and the API. Keep them boring and explicit: every field here shows
up in LangSmith traces and in the eval dataset.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Detection(BaseModel):
    """One anomaly detection produced by a CV tool."""

    label: str = Field(description="Defect class, e.g. 'scratch' or 'dent'")
    score: float = Field(ge=0.0, le=1.0, description="Anomaly confidence 0..1")
    bbox: tuple[int, int, int, int] | None = Field(
        default=None, description="(x, y, w, h) in pixels, if localised"
    )


class TriageReport(BaseModel):
    """The agent's final product: a verdict a human can approve or reject."""

    image_id: str
    verdict: Literal["anomaly", "normal", "uncertain"]
    detections: list[Detection] = []
    diagnosis: str = Field(description="Short human-readable explanation")
    citations: list[str] = Field(
        default=[], description="Manual sections the diagnosis relied on"
    )
    tool_calls: list[str] = Field(
        default=[], description="Names of tools invoked, in order"
    )
