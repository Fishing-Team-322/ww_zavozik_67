"""Calibration uses calibration companies only, never held-out fixtures."""
from __future__ import annotations

import numpy as np

from .model import softmax, sigmoid
from .novelty import fit_reference, ranks


def expected_calibration_error(probabilities: np.ndarray, labels: np.ndarray, bins: int = 15) -> float:
    if not len(labels):
        raise ValueError("calibration requires observations")
    conf = probabilities.max(axis=1)
    correct = probabilities.argmax(axis=1) == labels
    out = 0.0
    for i in range(bins):
        mask = (conf >= i / bins) & ((conf < (i + 1) / bins) if i + 1 < bins else (conf <= 1))
        if mask.any():
            out += float(mask.mean() * abs(conf[mask].mean() - correct[mask].mean()))
    return out


def category_scores(probabilities: np.ndarray, labels: np.ndarray) -> dict:
    p = probabilities.argmax(axis=1)
    f1s = []
    for k in range(probabilities.shape[1]):
        tp = ((p == k) & (labels == k)).sum()
        fp = ((p == k) & (labels != k)).sum()
        fn = ((p != k) & (labels == k)).sum()
        if tp + fp + fn:
            f1s.append(float(2 * tp / (2 * tp + fp + fn)))
    return {"n": len(labels), "accuracy": float((p == labels).mean()),
            "macro_f1": float(np.mean(f1s)), "ece": expected_calibration_error(probabilities, labels)}


def binary_scores(predicted: np.ndarray, labels: np.ndarray) -> dict:
    predicted, labels = np.asarray(predicted, bool), np.asarray(labels, bool)
    tp = int((predicted & labels).sum())
    fp = int((predicted & ~labels).sum())
    fn = int((~predicted & labels).sum())
    return {"micro_f1": 2 * tp / max(2 * tp + fp + fn, 1), "tp": tp, "fp": fp, "fn": fn}


def temperature(logits: np.ndarray, labels: np.ndarray) -> float:
    from scipy.optimize import minimize_scalar
    logits = np.asarray(logits, float)
    def nll(log_t):
        z = logits / np.exp(log_t)
        z -= z.max(axis=1, keepdims=True)
        return float((np.log(np.exp(z).sum(axis=1)) - z[np.arange(len(labels)), labels]).mean())
    result = minimize_scalar(nll, bounds=(np.log(.05), np.log(20)), method="bounded")
    return float(np.exp(result.x))


def calibrate(raw: dict[str, np.ndarray], category_y: np.ndarray, channel_y: np.ndarray,
              tag_y: np.ndarray, known_false_positive_rate: float = .05,
              categories: tuple[str, ...] | None = None) -> dict:
    if not 0 < known_false_positive_rate < 1:
        raise ValueError("invalid false positive target")
    tc = temperature(raw["category_logits"], category_y)
    th = temperature(raw["channel_logits"], channel_y)
    tag_p = sigmoid(raw["tag_logits"])
    thresholds = []
    for j in range(tag_y.shape[1]):
        # A tag absent from calibration cannot receive an optimistically
        # fitted threshold; retain the fixed default instead.
        candidates = np.linspace(.1, .9, 33) if tag_y[:, j].any() else [.5]
        best = max(candidates, key=lambda t: (binary_scores(tag_p[:, j] >= t, tag_y[:, j])["micro_f1"], -abs(t - .5)))
        thresholds.append(float(best))
    # Per-tag F1 maximizes macro rather than micro F1. Compare it with a single
    # shared threshold on the same calibration rows; never accept a regression
    # in the specified micro objective merely from independent tuning.
    choices = [thresholds] + [[float(t)] * tag_y.shape[1] for t in np.linspace(.1, .9, 33)]
    thresholds = max(choices, key=lambda ts: binary_scores(tag_p >= np.asarray(ts), tag_y)["micro_f1"])
    novelty_reference = None
    novelty = raw["novelty"]
    if categories is not None:
        if len(categories) != raw["category_logits"].shape[1]:
            raise ValueError("category calibration vocabulary mismatch")
        predicted = raw["category_logits"].argmax(1)
        novelty_reference = fit_reference(novelty, predicted, categories)
        novelty = ranks(novelty, predicted, categories, novelty_reference)
        novelty_threshold = 1 - known_false_positive_rate
    else:
        # Compatibility for pre-rank training artifacts. New export/train
        # always supplies the taxonomy vocabulary, never test labels.
        novelty_threshold = float(np.quantile(novelty, 1 - known_false_positive_rate, method="higher"))
    return {"category_temperature": tc, "channel_temperature": th,
            "tag_thresholds": thresholds, "novelty_threshold": novelty_threshold,
            "novelty_reference": novelty_reference,
            "known_calibration_fpr": float((novelty > novelty_threshold).mean()),
            "category": category_scores(softmax(raw["category_logits"] / tc), category_y),
            "channel": category_scores(softmax(raw["channel_logits"] / th), channel_y),
            "tags": binary_scores(tag_p >= np.array(thresholds), tag_y),
            "n": len(category_y), "source": "calibration_companies_only"}
