import json

import pytest

from visiontriage.bundle import BundleError, load_bundle
from visiontriage.profiler import compute_profile


def write_bundle(tmp_path, rows, threshold=0.5):
    (tmp_path / "run.json").write_text(json.dumps({
        "schema_version": 1, "run_id": "r1", "model_name": "m",
        "model_version": "1", "threshold": threshold,
        "dataset_id": "d", "dataset_version": "1",
    }))
    (tmp_path / "predictions.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    return tmp_path


def row(i, score, is_anom, category="bottle", brightness=0.5):
    return {"image_id": f"img_{i}", "path": f"images/img_{i}.png",
            "score": score, "is_anomaly": is_anom, "category": category,
            "defect_type": "crack" if is_anom else None, "split": "test",
            "brightness": brightness}


def test_profile_metrics_hand_computed(tmp_path):
    rows = [row(i, 0.9 if i % 2 else 0.1, i % 2 == 1) for i in range(20)]
    profile = compute_profile(load_bundle(write_bundle(tmp_path, rows)))
    assert profile["overall"]["f1"] == 1.0
    assert profile["overall"]["auroc"] == 1.0
    assert profile["candidates"]  # bottle slice has support 20


def test_bundle_rejects_escaping_path(tmp_path):
    bad = row(0, 0.1, False)
    bad["path"] = "../secret.png"
    with pytest.raises(BundleError):
        load_bundle(write_bundle(tmp_path, [bad]))


def test_min_support_suppresses_tiny_slices(tmp_path):
    rows = [row(i, 0.9 if i % 2 else 0.1, i % 2 == 1) for i in range(20)]
    rows += [row(100 + i, 0.9, False, category="rare") for i in range(2)]
    profile = compute_profile(load_bundle(write_bundle(tmp_path, rows)))
    assert all(c["value"] != "rare" for c in profile["candidates"])
