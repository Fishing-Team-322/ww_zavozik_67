"""Calibration-rank novelty from distances to the nearest category prototype.

Scores denote geometric extremity relative to known calibration operations,
not the posterior probability of a genuinely new economic category. Reference
groups use the frozen model's predicted category, never a test/unknown label.
Rare groups fall back to the global reference; no formal external FPR guarantee
is claimed after model selection on the same weak calibration dataset.
"""
from __future__ import annotations

import numpy as np

METHOD = "predicted_category_distance_rank_v1"
MIN_GROUP = 30


def fit_reference(distances: np.ndarray, predicted: np.ndarray, categories: tuple[str, ...],
                  min_group: int = MIN_GROUP) -> dict:
    distances = np.asarray(distances, float)
    predicted = np.asarray(predicted, int)
    if distances.ndim != 1 or distances.shape != predicted.shape or not len(distances):
        raise ValueError("novelty calibration needs matching nonempty vectors")
    if not np.isfinite(distances).all() or ((distances < 0) | (distances > 1)).any():
        raise ValueError("invalid novelty distances")
    if ((predicted < 0) | (predicted >= len(categories))).any() or min_group < 10:
        raise ValueError("invalid novelty grouping")
    return {"method": METHOD, "min_group": min_group,
            "global": np.sort(distances).tolist(),
            "by_category": {key: np.sort(distances[predicted == i]).tolist()
                            for i, key in enumerate(categories) if (predicted == i).sum() >= min_group},
            "source": "known calibration operations, grouped by predicted category; not unknown-class labels"}


def ranks(distances: np.ndarray, predicted: np.ndarray, categories: tuple[str, ...], reference: dict) -> np.ndarray:
    if reference.get("method") != METHOD:
        raise ValueError("unknown novelty calibration method")
    distances = np.asarray(distances, float)
    predicted = np.asarray(predicted, int)
    if distances.ndim != 1 or distances.shape != predicted.shape or not np.isfinite(distances).all():
        raise ValueError("invalid novelty score input")
    global_reference = np.asarray(reference["global"], float)
    if not len(global_reference):
        raise ValueError("empty global novelty reference")
    result = np.empty(len(distances), np.float32)
    for i in np.unique(predicted):
        if not 0 <= i < len(categories):
            raise ValueError("unknown predicted category index")
        ref = np.asarray(reference["by_category"].get(categories[int(i)], global_reference), float)
        if not len(ref) or not np.isfinite(ref).all() or (np.diff(ref) < 0).any():
            raise ValueError("invalid novelty reference")
        mask = predicted == i
        # Ties are conservative. Finite-sample smoothing permits a score of1
        # beyond the largest observed known distance, including new prototypes
        # which use the global fallback until separately recalibrated.
        result[mask] = (1 + np.searchsorted(ref, distances[mask], side="left")) / (len(ref) + 1)
    return result
