# Anomalib run (external) — producing a Run Bundle from MVTec

VisionTriage never trains models. This runbook produces the one artefact
VisionTriage consumes from an external Anomalib/PatchCore run — a CSV of
image-level scores — in a **separate environment outside this repo**, then
converts it with `scripts/import_anomalib.py`. Tracked as the human-only
issue #6; the real bundle is a demo input and is never scored as an eval case.

## 0. Prerequisites

- MVTec AD extracted at `data/mvtec/` (gitignored), layout
  `data/mvtec/<category>/train/good/...`, `data/mvtec/<category>/test/<defect>/...`.
- Python 3.12 available. Record everything in step 4 as you go.

## 1. Separate Anomalib environment (do not add to this repo)

```bash
uv venv --python 3.12 ~/.venvs/anomalib
source ~/.venvs/anomalib/bin/activate
uv pip install anomalib
anomalib install -v   # pulls the matching torch stack
python -c "import torch, anomalib; print(torch.__version__, torch.cuda.is_available(), anomalib.__version__)"
```

RTX 50-series (Blackwell) note: `torch.cuda.is_available()` must be true and
the torch build must support your GPU's compute capability; if not, install a
cu128 torch build into the venv first, then re-check before training.

## 2. Train + predict with PatchCore, dump scores

PatchCore in Anomalib is per-category. Start with one category (`bottle`)
for the demo; add categories by re-running with a different `CATEGORY`.
Save this as `dump_scores.py` **in the Anomalib workspace, not in this repo**:

```python
import csv, os
from anomalib.data import MVTec
from anomalib.engine import Engine
from anomalib.models import Patchcore

CATEGORY = os.environ.get("CATEGORY", "bottle")
ROOT = "data/mvtec"  # adjust to your absolute MVTec path

datamodule = MVTec(root=ROOT, category=CATEGORY,
                   train_batch_size=32, eval_batch_size=32)
engine = Engine(max_epochs=1)
engine.fit(model=Patchcore(), datamodule=datamodule)
batches = engine.predict(model=Patchcore(), datamodule=datamodule)

def get(obj, *names):
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None:
            return value
    return None

rows = []
for batch in batches or []:
    paths = get(batch, "image_path", "image_paths") or []
    scores = get(batch, "pred_score", "pred_scores", "anomaly_score")
    labels = get(batch, "label", "true_label", "is_anomaly")
    scores = scores.tolist() if hasattr(scores, "tolist") else list(scores or [])
    labels = labels.tolist() if hasattr(labels, "tolist") else (labels or [])
    for i, path in enumerate(paths):
        row = {"image_path": path, "score": float(scores[i])}
        if labels:
            row["is_anomaly"] = bool(labels[i])
        rows.append(row)

with open(f"scores-{CATEGORY}.csv", "w", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=["image_path", "score", "is_anomaly"])
    writer.writeheader()
    writer.writerows(rows)
print(f"wrote {len(rows)} rows")
```

Anomalib's prediction objects vary slightly between versions; if a field
name differs, adjust `get(...)` — the CSV contract below is the fixed part.
If ground truth is omitted, the importer derives it from the MVTec path
(`test/good` = normal, any other `test/<defect>` = anomaly).

## 3. Import and analyse

Back in this repo (Anomalib venv deactivated):

```bash
uv run python scripts/import_anomalib.py scores-bottle.csv data/bundles/mvtec-patchcore \
    --images-root data/mvtec --model-name PatchCore \
    --model-version "anomalib <version>, PatchCore defaults, bottle" \
    --dataset-id mvtec --threshold <threshold>
uv run visiontriage analyse data/bundles/mvtec-patchcore --output-root analysis
```

PatchCore scores are distances, not probabilities: pass the threshold
Anomalib selected for the run via `--threshold`, or the default 0.5 will
mislabel the precision/recall figures (AUROC is threshold-free).

CSV contract accepted by the importer: header with a path column
(`image_path`/`path`/`image`), a score column
(`score`/`anomaly_score`/`pred_score`), optional `is_anomaly`/`label`,
optional `category`/`defect_type`. Images are copied into the bundle; the
output is validated with the Run Bundle loader before the importer returns.

## 4. Record for issue #6

Note in the issue: Anomalib version, torch version + CUDA availability,
category(ies) run, the threshold used, date, and where the CSV/bundle live
(`data/` is gitignored — nothing under it is committed).
