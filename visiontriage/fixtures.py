"""Deterministic planted-failure fixture bundles and visual benchmark.

Fixtures are generated from compact scenario specs, never committed as blobs.
Each scenario plants one Failure Taxonomy mode and declares the expected
finding (taxonomy, slice, acceptable action categories) for eval scoring.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from visiontriage.pngutil import write_png

CATEGORIES = ("bottle", "tile", "screw")

EXPECTED: dict[str, dict] = {
    "threshold_miscalibration": {
        "taxonomy": "threshold_miscalibration",
        "slice": {},
        "action_categories": ["recalibrate_threshold", "evaluate_threshold"],
    },
    "score_overlap": {
        "taxonomy": "score_overlap",
        "slice": {},
        "action_categories": ["collect_data", "improve_model", "feature_engineering"],
    },
    "slice_weakness": {
        "taxonomy": "slice_weakness",
        "slice": {"dimension": "category", "value": "screw"},
        "action_categories": ["collect_data", "improve_model", "per_slice_threshold"],
    },
    "quality_confound": {
        "taxonomy": "quality_confound",
        "slice": {"dimension": "quality_band", "value": "dark"},
        "action_categories": ["fix_image_quality", "report_quality_slice", "collect_data"],
    },
    "label_noise": {
        "taxonomy": "label_noise",
        "slice": {"dimension": "defect_type", "value": "scratch"},
        "action_categories": ["fix_labels", "audit_labels"],
    },
    "leakage": {
        "taxonomy": "leakage",
        "slice": {"dimension": "split", "value": "test"},
        "action_categories": ["remove_duplicates", "rebuild_split", "audit_labels"],
    },
}

SCENARIOS = tuple(EXPECTED)


def _emb(seed_vec: list[float], rng: random.Random, jitter: float = 0.03) -> list[float]:
    return [round(v + rng.uniform(-jitter, jitter), 4) for v in seed_vec]


def build_fixture(scenario: str, out_dir: str | Path, seed: int = 7, per_category: int = 36) -> Path:
    if scenario not in EXPECTED:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")
    out = Path(out_dir)
    rng = random.Random(seed)
    rows: list[dict] = []

    def add(category: str, defect: str | None, is_anom: bool, score: float,
            brightness: float = 0.55, split: str = "test", vec: list[float] | None = None) -> None:
        idx = len(rows)
        image_id = f"{category}_{idx:04d}"
        rel = f"images/{image_id}.png"
        base = {"bottle": [1.0, 0.0, 0.0, 0.0], "tile": [0.0, 1.0, 0.0, 0.0],
                "screw": [0.0, 0.0, 1.0, 0.0]}[category]
        if vec is not None:
            base = vec
        rows.append({
            "image_id": image_id, "path": rel, "score": round(score, 4),
            "is_anomaly": is_anom, "category": category,
            "defect_type": defect, "split": split,
            "brightness": round(brightness, 3), "blur": 0.1,
            "embedding": _emb(base, rng),
        })

    for category in CATEGORIES:
        defect = {"bottle": "contamination", "tile": "crack", "screw": "thread"}[category]
        for i in range(per_category):
            is_anom = i % 2 == 1
            if scenario == "threshold_miscalibration":
                score = rng.uniform(0.40, 0.49) if is_anom else rng.uniform(0.05, 0.30)
            elif scenario == "score_overlap":
                score = rng.uniform(0.30, 0.70) if is_anom else rng.uniform(0.25, 0.65)
            elif scenario == "slice_weakness" and category == "screw":
                score = rng.uniform(0.15, 0.40) if is_anom else rng.uniform(0.05, 0.30)
            elif scenario == "quality_confound":
                bright = rng.uniform(0.45, 0.65)
                if not is_anom and i % 4 == 0:  # dark good images score high -> FP
                    add(category, None, False, rng.uniform(0.65, 0.9), brightness=0.10)
                    continue
                score = rng.uniform(0.70, 0.95) if is_anom else rng.uniform(0.05, 0.30)
                add(category, defect if is_anom else None, is_anom, score, brightness=bright)
                continue
            elif scenario == "label_noise" and category == "bottle" and i % 3 == 0:
                # Labelled good but looks exactly like a scratch anomaly (mislabelled).
                add(category, "scratch", False, rng.uniform(0.75, 0.95),
                    vec=[0.0, 0.0, 0.0, 1.0])
                continue
            elif scenario == "leakage":
                shared = [0.5, 0.5, 0.5, 0.5]
                split = "train" if i % 2 == 0 else "test"
                score = rng.uniform(0.80, 0.98) if is_anom else rng.uniform(0.02, 0.15)
                add(category, defect if is_anom else None, is_anom, score,
                    split=split, vec=shared)
                continue
            else:
                score = rng.uniform(0.70, 0.95) if is_anom else rng.uniform(0.05, 0.30)
            add(category, defect if is_anom else None, is_anom, score)

    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    (out / "run.json").write_text(json.dumps({
        "schema_version": 1, "run_id": f"fixture-{scenario}",
        "model_name": "fixture-model", "model_version": "1.0",
        "threshold": 0.5, "dataset_id": "fixture", "dataset_version": "1",
        "git_sha": None, "baseline_run_id": None,
    }, indent=2))
    (out / "expected.json").write_text(json.dumps(EXPECTED[scenario], indent=2))
    grey = [[(120, 120, 120)] * 8 for _ in range(8)]
    for row in rows:
        write_png(out / row["path"], grey)
    return out


# --- Visual benchmark -------------------------------------------------------

VISUAL_ATTRIBUTES = ("crack", "contamination", "dark", "blur", "clean")


def build_visual_benchmark(out_dir: str | Path, size: int = 48, per_kind: int = 5) -> list[dict]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []

    def base(v: int) -> list[list[tuple[int, int, int]]]:
        return [[(v, v, v)] * size for _ in range(size)]

    for kind in ("clean", "dark", "crack", "contamination", "blur"):
        for k in range(per_kind):
            pixels = base(40 if kind == "dark" else 170)
            if kind == "crack":
                for i in range(6, size - 6):
                    pixels[i][size // 2 + (i % 5) - 2] = (20, 20, 20)
            elif kind == "contamination":
                for y in range(size // 3, size // 3 + 10):
                    for x in range(size // 3, size // 3 + 14):
                        pixels[y][x] = (70, 50, 30)
            elif kind == "blur":
                pixels = [[(140 + (x * 60 // size),) * 3 for x in range(size)]
                          for _ in range(size)]
            name = f"{kind}_{k}.png"
            write_png(out / name, pixels)
            cases.append({"image": name, "attributes": [kind]})
    (out / "labels.json").write_text(json.dumps(cases, indent=2))
    return cases
