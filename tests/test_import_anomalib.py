"""Importer seam: Anomalib predictions CSV -> validated Run Bundle."""

import csv
import json
import subprocess
import sys
from pathlib import Path

from visiontriage.bundle import load_bundle
from visiontriage.pngutil import write_png
from visiontriage.profiler import compute_profile

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "import_anomalib.py"
GREY = [[(120, 120, 120)] * 4 for _ in range(4)]


def run_import(args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), *[str(a) for a in args]],
                          capture_output=True, text=True, timeout=60, cwd=cwd)


def write_csv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_import_mvtec_layout_derives_labels(tmp_path):
    root = tmp_path / "mvtec"
    for rel in ("bottle/test/good/000.png", "bottle/test/crack/001.png",
                "tile/test/good/000.png"):
        write_png(root / rel, GREY)
    csv_path = tmp_path / "results.csv"
    write_csv(csv_path, [
        {"image_path": "bottle/test/good/000.png", "score": "0.1"},
        {"image_path": "bottle/test/crack/001.png", "score": "0.9"},
        {"image_path": "tile/test/good/000.png", "score": "0.2"},
    ])
    out = tmp_path / "bundle"
    proc = run_import([csv_path, out, "--images-root", root], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr

    bundle = load_bundle(out)
    by_id = bundle.by_id()
    assert len(by_id) == 3
    crack = next(p for p in bundle.predictions if p.defect_type == "crack")
    assert crack.is_anomaly and crack.category == "bottle" and crack.split == "test"
    assert (out / crack.path).is_file()  # images copied into the bundle
    assert compute_profile(bundle)["overall"]["support"] == 3


def test_import_explicit_labels_and_alias_columns(tmp_path):
    root = tmp_path / "imgs"
    write_png(root / "a.png", GREY)
    write_png(root / "b.png", GREY)
    csv_path = tmp_path / "results.csv"
    write_csv(csv_path, [
        {"image": "a.png", "pred_score": "0.8", "label": "anomaly", "category": "widget"},
        {"image": "b.png", "pred_score": "0.1", "label": "normal", "category": "widget"},
    ])
    out = tmp_path / "bundle"
    proc = run_import([csv_path, out, "--images-root", root,
                       "--model-version", "anomalib-test"], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    bundle = load_bundle(out)
    assert {p.image_id: p.is_anomaly for p in bundle.predictions} == {"a": True, "b": False}
    assert bundle.metadata.model_version == "anomalib-test"
    doc = json.loads((out / "run.json").read_text())
    assert doc["schema_version"] == 1


def test_import_missing_image_fails_cleanly(tmp_path):
    csv_path = tmp_path / "results.csv"
    write_csv(csv_path, [{"image_path": "nope/test/crack/000.png", "score": "0.9"}])
    proc = run_import([csv_path, tmp_path / "bundle",
                       "--images-root", tmp_path], cwd=tmp_path)
    assert proc.returncode == 1
    assert "image not found" in proc.stderr
    assert "Traceback" not in proc.stderr
