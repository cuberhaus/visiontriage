"""Deterministic profiler: facts about an Evaluation Run, no LLM."""

from __future__ import annotations

from visiontriage.bundle import Bundle, Prediction, is_predicted_anomaly

MIN_SUPPORT = 10
SLICE_DIMENSIONS = ("category", "defect_type", "split", "quality_band")


def quality_band(pred: Prediction) -> str | None:
    if pred.brightness is None:
        return None
    if pred.brightness < 0.25:
        return "dark"
    if pred.brightness > 0.8:
        return "bright"
    return "normal"


def _auroc(preds: list[Prediction]) -> float | None:
    pos = [p.score for p in preds if p.is_anomaly]
    neg = [p.score for p in preds if not p.is_anomaly]
    if not pos or not neg:
        return None
    wins = sum(1.0 if s > t else 0.5 if s == t else 0.0 for s in pos for t in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[idx], 4)


def metrics_for(preds: list[Prediction], threshold: float) -> dict:
    tp = sum(1 for p in preds if p.is_anomaly and is_predicted_anomaly(p, threshold))
    fp = sum(1 for p in preds if not p.is_anomaly and is_predicted_anomaly(p, threshold))
    fn = sum(1 for p in preds if p.is_anomaly and not is_predicted_anomaly(p, threshold))
    tn = sum(1 for p in preds if not p.is_anomaly and not is_predicted_anomaly(p, threshold))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    anomaly_scores = [p.score for p in preds if p.is_anomaly]
    normal_scores = [p.score for p in preds if not p.is_anomaly]
    return {
        "support": len(preds),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "error_rate": round((fp + fn) / len(preds), 4) if preds else 0.0,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "auroc": _auroc(preds),
        "anomaly_score_quantiles": (
            {"p10": _quantile(anomaly_scores, 0.1), "p50": _quantile(anomaly_scores, 0.5),
             "p90": _quantile(anomaly_scores, 0.9)} if anomaly_scores else None
        ),
        "normal_score_quantiles": (
            {"p10": _quantile(normal_scores, 0.1), "p50": _quantile(normal_scores, 0.5),
             "p90": _quantile(normal_scores, 0.9)} if normal_scores else None
        ),
    }


def _slice_value(pred: Prediction, dimension: str) -> str | None:
    if dimension == "quality_band":
        return quality_band(pred)
    value = getattr(pred, dimension, None)
    return str(value) if value is not None else None


def slice_names(bundle: Bundle) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for dim in SLICE_DIMENSIONS:
        values = sorted({v for p in bundle.predictions if (v := _slice_value(p, dim)) is not None})
        if values:
            out[dim] = values
    return out


def compute_profile(bundle: Bundle) -> dict:
    threshold = bundle.metadata.threshold
    slices: dict[str, dict[str, dict]] = {}
    candidates: list[dict] = []
    for dim, values in slice_names(bundle).items():
        slices[dim] = {}
        for value in values:
            preds = [p for p in bundle.predictions if _slice_value(p, dim) == value]
            m = metrics_for(preds, threshold)
            slices[dim][value] = m
            if m["support"] >= MIN_SUPPORT:
                candidates.append({
                    "dimension": dim, "value": value,
                    "support": m["support"], "error_rate": m["error_rate"],
                    "errors": m["fp"] + m["fn"], "fp": m["fp"], "fn": m["fn"],
                    "rank_score": round(m["error_rate"] * m["support"], 4),
                })
    candidates.sort(key=lambda c: (-c["rank_score"], -c["error_rate"], c["dimension"], c["value"]))
    return {
        "run_id": bundle.metadata.run_id,
        "model": f"{bundle.metadata.model_name}@{bundle.metadata.model_version}",
        "dataset": f"{bundle.metadata.dataset_id}@{bundle.metadata.dataset_version}",
        "threshold": threshold,
        "overall": metrics_for(bundle.predictions, threshold),
        "slices": slices,
        "min_support": MIN_SUPPORT,
        "candidates": candidates,
    }
