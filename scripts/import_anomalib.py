#!/usr/bin/env python3
"""Convert an externally produced Anomalib result into a Run Bundle.

VisionTriage never trains models. This importer consumes the one
artefact an external Anomalib run must emit — a CSV of image-level
predictions — and writes a validated Run Bundle (see
`visiontriage/bundle.py`). See docs/anomalib-run.md for how to produce
the CSV with Anomalib (PatchCore) in a separate environment.

CSV contract (header row required, column aliases accepted):
  image_path | path | image          path to the evaluated image
  score | anomaly_score | pred_score image-level anomaly score
  is_anomaly | label | true_label    optional ground truth:
                                     true/false, 1/0, anomaly/normal
  category, defect_type              optional; derived from an MVTec
                                     layout (<category>/test/<defect>/)
                                     when omitted

Usage:
  uv run python scripts/import_anomalib.py results.csv out-bundle \
      --images-root data/mvtec --model-version "anomalib 2.x / PatchCore"
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PATH_COLUMNS = ("image_path", "path", "image")
SCORE_COLUMNS = ("score", "anomaly_score", "pred_score", "pred_scores")
LABEL_COLUMNS = ("is_anomaly", "label", "true_label", "is_anomalous")

TRUE_WORDS = {"true", "1", "yes", "anomaly", "anomalous", "defect", "abnormal"}
FALSE_WORDS = {"false", "0", "no", "normal", "good", "ok"}


def _pick(row: dict, columns: tuple[str, ...]) -> str | None:
    for column in columns:
        value = row.get(column)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _parse_label(raw: str | None, source_rel: Path) -> bool | None:
    if raw is not None:
        word = raw.strip().lower()
        if word in TRUE_WORDS:
            return True
        if word in FALSE_WORDS:
            return False
        raise ValueError(f"unrecognised ground-truth label: {raw!r}")
    # MVTec layout: <category>/test/<defect_type>/<file>; "good" is normal.
    parts = source_rel.parts
    if "test" in parts:
        idx = parts.index("test")
        if idx + 1 < len(parts) - 1:
            return parts[idx + 1].lower() != "good"
    return None


def _mvtec_fields(source_rel: Path) -> dict:
    parts = source_rel.parts
    fields: dict = {"split": "test"}
    if "test" in parts:
        idx = parts.index("test")
        if idx >= 1:
            fields["category"] = parts[idx - 1]
        if idx + 1 < len(parts) - 1 and parts[idx + 1].lower() != "good":
            fields["defect_type"] = parts[idx + 1]
    elif "train" in parts:
        idx = parts.index("train")
        fields["split"] = "train"
        if idx >= 1:
            fields["category"] = parts[idx - 1]
    return fields


def _image_id(source_rel: Path, used: set[str]) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", source_rel.with_suffix("").as_posix()).strip("_")
    image_id, counter = stem or "image", 2
    while image_id in used:
        image_id = f"{stem}_{counter}"
        counter += 1
    used.add(image_id)
    return image_id


def convert(csv_path: Path, output: Path, images_root: Path,
            run_id: str, model_name: str, model_version: str,
            threshold: float, dataset_id: str, dataset_version: str,
            git_sha: str | None) -> Path:
    rows = list(csv.DictReader(csv_path.open(newline="")))
    if not rows:
        raise ValueError(f"no prediction rows in {csv_path}")

    predictions: list[dict] = []
    used_ids: set[str] = set()
    for lineno, row in enumerate(rows, 2):  # line 1 is the header
        raw_path = _pick(row, PATH_COLUMNS)
        raw_score = _pick(row, SCORE_COLUMNS)
        if raw_path is None or raw_score is None:
            raise ValueError(
                f"{csv_path}:{lineno}: need an image path column {PATH_COLUMNS} "
                f"and a score column {SCORE_COLUMNS}")
        try:
            score = float(raw_score)
        except ValueError as exc:
            raise ValueError(f"{csv_path}:{lineno}: bad score {raw_score!r}") from exc

        source = Path(raw_path)
        candidates = [source] if source.is_absolute() else [
            images_root / source, csv_path.parent / source, Path.cwd() / source]
        source_file = next((c for c in candidates if c.is_file()), None)
        if source_file is None:
            raise ValueError(f"{csv_path}:{lineno}: image not found: {raw_path!r} "
                             f"(looked under {images_root})")
        try:
            source_rel = source_file.resolve().relative_to(images_root.resolve())
        except ValueError:
            source_rel = Path(source_file.name) \
                if source.is_absolute() else source

        is_anomaly = _parse_label(_pick(row, LABEL_COLUMNS), source_rel)
        if is_anomaly is None:
            raise ValueError(
                f"{csv_path}:{lineno}: no ground-truth label and the path "
                f"{raw_path!r} is not in MVTec <category>/test/<defect>/ layout")
        fields = _mvtec_fields(source_rel)
        category = _pick(row, ("category",)) or fields.get("category")
        defect = _pick(row, ("defect_type", "defect")) or fields.get("defect_type")

        image_id = _image_id(source_rel, used_ids)
        suffix = source_file.suffix.lower() or ".png"
        bundle_rel = f"images/{image_id}{suffix}"
        dest = output / bundle_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, dest)
        predictions.append({
            "image_id": image_id, "path": bundle_rel, "score": score,
            "is_anomaly": is_anomaly, "category": category,
            "defect_type": defect if is_anomaly else None,
            "split": fields["split"], "brightness": None, "blur": None,
            "embedding": None,
        })

    output.mkdir(parents=True, exist_ok=True)
    (output / "run.json").write_text(json.dumps({
        "schema_version": 1, "run_id": run_id, "model_name": model_name,
        "model_version": model_version, "threshold": threshold,
        "dataset_id": dataset_id, "dataset_version": dataset_version,
        "git_sha": git_sha, "baseline_run_id": None,
    }, indent=2))
    (output / "predictions.jsonl").write_text(
        "".join(json.dumps(p) + "\n" for p in predictions))

    from visiontriage.bundle import load_bundle
    load_bundle(output)  # never hand back an invalid bundle
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert an Anomalib predictions CSV into a Run Bundle")
    parser.add_argument("predictions_csv", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--images-root", type=Path, default=Path("data/mvtec"),
                        help="Base directory image paths are relative to")
    parser.add_argument("--run-id", default="mvtec-patchcore")
    parser.add_argument("--model-name", default="PatchCore")
    parser.add_argument("--model-version", default="unknown",
                        help="Anomalib version/config that produced the scores")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--dataset-id", default="mvtec")
    parser.add_argument("--dataset-version", default="1")
    parser.add_argument("--git-sha")
    args = parser.parse_args(argv)
    try:
        convert(args.predictions_csv, args.output, args.images_root,
                args.run_id, args.model_name, args.model_version,
                args.threshold, args.dataset_id, args.dataset_version,
                args.git_sha)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Run Bundle written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
