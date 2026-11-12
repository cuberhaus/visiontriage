"""Deterministic investigation tools over one Run Bundle.

These functions back the MCP tool server; they are also directly testable.
All inputs are structured and allowlisted. The LLM never supplies code.
"""

from __future__ import annotations

import base64
import math

from visiontriage.bundle import Bundle, Prediction, is_predicted_anomaly
from visiontriage.profiler import _slice_value, metrics_for, slice_names

OUTCOMES = ("fp", "fn", "tp", "tn", "all")


def _outcome(pred: Prediction, threshold: float) -> str:
    predicted = is_predicted_anomaly(pred, threshold)
    if pred.is_anomaly and predicted:
        return "tp"
    if not pred.is_anomaly and predicted:
        return "fp"
    if pred.is_anomaly and not predicted:
        return "fn"
    return "tn"


def _filter(bundle: Bundle, dimension: str | None, value: str | None) -> list[Prediction]:
    if dimension is None:
        return list(bundle.predictions)
    if dimension not in slice_names(bundle) and dimension not in ("category", "defect_type", "split", "quality_band"):
        raise ValueError(f"unknown slice dimension: {dimension}")
    return [p for p in bundle.predictions if _slice_value(p, dimension) == value]


def slice_metrics(bundle: Bundle, dimension: str, value: str) -> dict:
    preds = _filter(bundle, dimension, value)
    return {"dimension": dimension, "value": value,
            **metrics_for(preds, bundle.metadata.threshold)}


def list_examples(bundle: Bundle, outcome: str = "fn", dimension: str | None = None,
                  value: str | None = None, limit: int = 10) -> dict:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")
    limit = max(1, min(limit, 50))
    threshold = bundle.metadata.threshold
    preds = [p for p in _filter(bundle, dimension, value)
             if outcome == "all" or _outcome(p, threshold) == outcome]
    # Worst mistakes first: FNs by lowest score, FPs by highest score.
    if outcome == "fn":
        preds.sort(key=lambda p: p.score)
    else:
        preds.sort(key=lambda p: -p.score)
    return {
        "outcome": outcome, "dimension": dimension, "value": value,
        "count": len(preds),
        "examples": [
            {"image_id": p.image_id, "path": p.path, "score": p.score,
             "is_anomaly": p.is_anomaly, "category": p.category,
             "defect_type": p.defect_type, "split": p.split,
             "brightness": p.brightness, "blur": p.blur}
            for p in preds[:limit]
        ],
    }


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def cluster_failures(bundle: Bundle, outcome: str = "fn", similarity: float = 0.9) -> dict:
    if outcome not in ("fp", "fn"):
        raise ValueError("cluster_failures outcome must be 'fp' or 'fn'")
    threshold = bundle.metadata.threshold
    preds = [p for p in bundle.predictions
             if _outcome(p, threshold) == outcome and p.embedding]
    if not preds:
        return {"outcome": outcome, "clusters": [], "note": "no embedded examples for this outcome"}
    clusters: list[list[Prediction]] = []
    for pred in preds:
        for cluster in clusters:
            if _cosine(pred.embedding, cluster[0].embedding) >= similarity:
                cluster.append(pred)
                break
        else:
            clusters.append([pred])
    out = []
    for i, cluster in enumerate(sorted(clusters, key=len, reverse=True)):
        mean = [sum(p.embedding[j] for p in cluster) / len(cluster)
                for j in range(len(cluster[0].embedding))]
        rep = max(cluster, key=lambda p: _cosine(p.embedding, mean))
        out.append({
            "cluster_id": f"C{i + 1}", "size": len(cluster),
            "representative_image_id": rep.image_id,
            "image_ids": [p.image_id for p in cluster],
            "mean_score": round(sum(p.score for p in cluster) / len(cluster), 4),
        })
    return {"outcome": outcome, "clusters": out}


def duplicate_check(bundle: Bundle, similarity: float = 0.99) -> dict:
    """Near-duplicate embeddings shared across splits (leakage signal).

    shortcut: O(n^2) pair scan; fine for Run Bundles of hundreds of
    Predictions, revisit if bundles grow to tens of thousands.
    """
    preds = [p for p in bundle.predictions if p.embedding and p.split]
    pairs: list[dict] = []
    pair_count = 0
    image_ids: list[str] = []
    for i, a in enumerate(preds):
        for b in preds[i + 1:]:
            if a.split == b.split or _cosine(a.embedding, b.embedding) < similarity:
                continue
            pair_count += 1
            for p in (a, b):
                if p.image_id not in image_ids:
                    image_ids.append(p.image_id)
            if len(pairs) < 5:
                pairs.append({
                    "image_id_a": a.image_id, "split_a": a.split,
                    "image_id_b": b.image_id, "split_b": b.split,
                    "similarity": round(_cosine(a.embedding, b.embedding), 4),
                })
    return {"pair_count": pair_count, "pairs": pairs, "image_ids": image_ids[:10]}


def quality_breakdown(bundle: Bundle) -> dict:
    return slice_metrics(bundle, "quality_band", "dark") | {
        "bands": {
            band: metrics_for(
                [p for p in bundle.predictions if _slice_value(p, "quality_band") == band],
                bundle.metadata.threshold)
            for band in ("dark", "normal", "bright")
            if any(_slice_value(p, "quality_band") == band for p in bundle.predictions)
        }
    }


def score_distribution(bundle: Bundle, bins: int = 10) -> dict:
    bins = max(2, min(bins, 20))
    edges = [i / bins for i in range(bins + 1)]
    hist = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        in_bin = [p for p in bundle.predictions if lo <= p.score < hi or (i == bins - 1 and p.score == hi)]
        hist.append({
            "lo": lo, "hi": hi, "count": len(in_bin),
            "anomalies": sum(1 for p in in_bin if p.is_anomaly),
            "errors": sum(1 for p in in_bin
                          if p.is_anomaly != is_predicted_anomaly(p, bundle.metadata.threshold)),
        })
    return {"bins": hist, "threshold": bundle.metadata.threshold}


def get_images(bundle: Bundle, image_ids: list[str], max_images: int = 5) -> dict:
    """Supply image bytes (base64) for inspection; IDs must exist in the bundle."""
    if len(image_ids) > max_images:
        raise ValueError(f"at most {max_images} images per call")
    by_id = bundle.by_id()
    out = []
    for image_id in image_ids:
        if image_id not in by_id:
            raise ValueError(f"unknown image_id: {image_id}")
        path = bundle.image_path(by_id[image_id])
        data = path.read_bytes() if path.is_file() else b""
        out.append({"image_id": image_id, "path": by_id[image_id].path,
                    "image_base64": base64.b64encode(data).decode() if data else ""})
    return {"images": out}
