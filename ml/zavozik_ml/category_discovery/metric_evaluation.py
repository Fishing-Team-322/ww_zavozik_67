"""Calibration-only relation agreement; never semantic accuracy or final audit.

Reports original/centered frozen baselines alongside two learned metric heads,
so centering alone cannot be described as successful supervised adaptation.
Thresholds fit on this same calibration sample are explicitly apparent scores.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from zavozik_ml.classify_v2.model import sha256_file, unit
from .train_metric_heads import LEVELS, load_part


def project(x, weights, level):
    w, b = weights[level+".weight"], weights[level+".bias"]
    if w.shape != (x.shape[1], x.shape[1]) or b.shape != (x.shape[1],) or not np.isfinite(w).all() or not np.isfinite(b).all():
        raise ValueError("metric head dimension/value mismatch")
    return unit(x @ w.T + b)


def agreement(scores, targets):
    from sklearn.metrics import average_precision_score, roc_auc_score, precision_recall_curve
    mask = targets >= 0
    y, s = targets[mask], scores[mask]
    p, r, thresholds = precision_recall_curve(y, s)
    f1 = 2*p[:-1]*r[:-1] / np.maximum(p[:-1]+r[:-1], 1e-12)
    best = int(np.argmax(f1))
    return dict(known_pairs=len(y), uncertain_pairs=int((~mask).sum()), same_pairs=int(y.sum()),
        different_pairs=int(len(y)-y.sum()), average_precision=float(average_precision_score(y, s)),
        roc_auc=float(roc_auc_score(y, s)), apparent_max_f1=float(f1[best]),
        apparent_precision=float(p[best]), apparent_recall=float(r[best]), selected_threshold=float(thresholds[best]),
        threshold_source="same calibration sample; apparent agreement, not independently measured operating precision")


def evaluate(corpus: Path, cache: Path, labels: Path, out: Path, heads: Path | None = None, allow_weak=False):
    if out.exists():
        raise ValueError("calibration evaluation exists; never overwrite")
    x, pairs, provenance, counts = load_part(corpus, cache, labels, "calibration", allow_weak, 1)
    encoded = json.loads((cache / "manifest.json").read_text())
    if sha256_file(cache / "train.npy") != encoded["train"]["sha256"]:
        raise ValueError("training centering source changed")
    train_x = np.load(cache / "train.npy", allow_pickle=False)
    views = dict(original={level:x for level in LEVELS},
                 centered={level:unit(x-train_x.mean(0)) for level in LEVELS})
    fit_manifest = None
    if heads is not None:
        fit_manifest = json.loads((heads / "manifest.json").read_text())
        if (fit_manifest["cache_manifest_sha256"] != sha256_file(cache / "manifest.json") or
                fit_manifest["calibration_labels_sha256"] != sha256_file(labels) or
                fit_manifest["head_sha256"] != sha256_file(heads / "best_heads.npz")):
            raise ValueError("heads/cache/calibration label provenance mismatch")
        with np.load(heads / "best_heads.npz", allow_pickle=False) as weights:
            views["adapted"] = {level:project(x, weights, level) for level in LEVELS}
    result = dict(scope="calibration_only_relation_agreement", semantic_accuracy=None, final_test_read=False,
        independent_test=False, label_provenance=provenance, relation_counts=counts,
        cache_manifest_sha256=sha256_file(cache / "manifest.json"), labels_sha256=sha256_file(labels),
        heads_manifest_sha256=sha256_file(heads / "manifest.json") if heads else None,
        code_sha256=sha256_file(Path(__file__)), comparisons={},
        uncertainty_intervals=None,
        limitations="Pairs share endpoints/families; no IID confidence intervals. Weak labels are not human gold. Stratified pair sampling is not population accuracy.")
    for name, vectors_by_level in views.items():
        scores = {}
        for i, level in enumerate(LEVELS):
            z = vectors_by_level[level]
            cosine = (z[pairs[:,0]] * z[pairs[:,1]]).sum(1)
            scores[level] = agreement(cosine, pairs[:,i+2])
        scores["macro_average_precision"] = float(np.mean([scores[level]["average_precision"] for level in LEVELS]))
        result["comparisons"][name] = scores
    out.mkdir(parents=True)
    (out / "report.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--heads", type=Path)
    p.add_argument("--allow-weak-supervision", action="store_true")
    a = p.parse_args()
    print(json.dumps(evaluate(a.corpus, a.cache, a.labels, a.out, a.heads, a.allow_weak_supervision), indent=2))


if __name__ == "__main__":
    main()
