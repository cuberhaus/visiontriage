"""Run Bundle loading and validation.

A Run Bundle is the portable representation of one Evaluation Run:
``predictions.jsonl`` + ``run.json`` + images referenced by relative path.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = 1


class BundleError(ValueError):
    """Raised when a Run Bundle is malformed or unsafe."""


class Prediction(BaseModel):
    image_id: str
    path: str
    score: float
    is_anomaly: bool
    category: str | None = None
    defect_type: str | None = None
    split: str | None = None
    brightness: float | None = Field(default=None, ge=0.0, le=1.0)
    blur: float | None = Field(default=None, ge=0.0)
    embedding: list[float] | None = None

    @field_validator("path")
    @classmethod
    def _path_must_stay_inside_bundle(cls, value: str) -> str:
        p = PurePosixPath(value)
        if p.is_absolute() or ".." in p.parts:
            raise BundleError(f"image path escapes the bundle: {value!r}")
        return value

    @property
    def predicted_anomaly(self) -> bool:
        # Set by load_bundle once the run threshold is known.
        return getattr(self, "_predicted", self.score >= 0.5)


class RunMetadata(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    model_name: str
    model_version: str
    threshold: float
    dataset_id: str
    dataset_version: str
    git_sha: str | None = None
    baseline_run_id: str | None = None

    @field_validator("schema_version")
    @classmethod
    def _supported_version(cls, value: int) -> int:
        if value != SCHEMA_VERSION:
            raise BundleError(f"unsupported bundle schema_version: {value}")
        return value


class Bundle(BaseModel):
    root: Path
    metadata: RunMetadata
    predictions: list[Prediction]

    model_config = {"arbitrary_types_allowed": True}

    def image_path(self, prediction: Prediction) -> Path:
        full = (self.root / prediction.path).resolve()
        if self.root.resolve() not in full.parents and full != self.root.resolve():
            raise BundleError(f"image path escapes the bundle: {prediction.path!r}")
        return full

    def by_id(self) -> dict[str, Prediction]:
        return {p.image_id: p for p in self.predictions}


def load_bundle(root: str | Path) -> Bundle:
    root = Path(root)
    meta_file = root / "run.json"
    pred_file = root / "predictions.jsonl"
    if not meta_file.is_file():
        raise BundleError(f"missing run.json in bundle {root}")
    if not pred_file.is_file():
        raise BundleError(f"missing predictions.jsonl in bundle {root}")
    try:
        metadata = RunMetadata.model_validate_json(meta_file.read_text())
    except Exception as exc:
        raise BundleError(f"invalid run.json: {exc}") from exc

    predictions: list[Prediction] = []
    seen: set[str] = set()
    for lineno, line in enumerate(pred_file.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            pred = Prediction.model_validate_json(line)
        except Exception as exc:
            raise BundleError(f"invalid predictions.jsonl line {lineno}: {exc}") from exc
        if pred.image_id in seen:
            raise BundleError(f"duplicate image_id {pred.image_id!r} at line {lineno}")
        seen.add(pred.image_id)
        object.__setattr__(pred, "_predicted", pred.score >= metadata.threshold)
        predictions.append(pred)
    if not predictions:
        raise BundleError("bundle contains no predictions")
    return Bundle(root=root, metadata=metadata, predictions=predictions)


def is_predicted_anomaly(pred: Prediction, threshold: float) -> bool:
    return pred.score >= threshold
