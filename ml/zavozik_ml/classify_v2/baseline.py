"""Refit linear-v1 on exactly the purged v2 training pool, without extra data.

The deployed v1 artifact remains unchanged. Only calibration observations fit
the temperature; neither test labels nor historical holdouts select anything.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np

from zavozik_ml.classify.model import Classifier
from zavozik_ml.classify.train import CAT_INDEX, class_weights, fit_softmax, fit_temperature, matrix, to_op
from .calibration import category_scores
from .data import read_rows
from .model import sha256_file
from .splitting import PROTOCOL


def fit(prepared: Path, out: Path, l2: float = 3e-6, maxiter: int = 300):
    if out.exists():
        raise ValueError("baseline output exists; do not overwrite")
    manifest = json.loads((prepared / "data_manifest.json").read_text())
    if (manifest.get("split_protocol") != PROTOCOL or not manifest.get("split_audit", {}).get("passed")
            or any(v for pair in manifest["split_audit"]["pairwise_intersections"].values() for v in pair.values())):
        raise ValueError("baseline requires audited template-disjoint data")
    token_report = json.loads((prepared / "token_input_audit.json").read_text())
    if not token_report.get("passed") or token_report.get("data_manifest_sha256") != sha256_file(prepared / "data_manifest.json"):
        raise ValueError("effective-input audit missing or stale")
    for name in ("train", "calibration"):
        if sha256_file(prepared / (name + ".jsonl")) != manifest[name]["sha256"]:
            raise ValueError("prepared data changed")
    rows, cal = read_rows(prepared / "train.jsonl"), read_rows(prepared / "calibration.jsonl")
    started = time.perf_counter()
    x = matrix(rows)
    print(f"linear-v1 train_rows={len(rows)} calibration_rows={len(cal)}", flush=True)
    y = np.array([CAT_INDEX[r["label"]] for r in rows])
    w, bias, optimization = fit_softmax(x, y, class_weights(rows), l2=l2, maxiter=maxiter)
    if not np.isfinite(w).all() or not np.isfinite(bias).all():
        raise ValueError("baseline optimizer produced nonfinite weights")
    classifier = Classifier(w, bias)
    cy = np.array([CAT_INDEX[r["label"]] for r in cal])
    classifier.temperature = fit_temperature(classifier.logits([to_op(r) for r in cal]), cy)
    classifier.meta = dict(evaluation_only=True, split_protocol=PROTOCOL, data_manifest=manifest,
                           train_companies=manifest["train_companies"],
                           calibration_companies=manifest["calibration_companies"], test_companies=manifest["test_companies"],
                           fit=dict(l2=l2, maxiter=maxiter, iterations=int(optimization.nit),
                                    optimizer_success=bool(optimization.success), message=str(optimization.message),
                                    seconds=time.perf_counter()-started),
                           training_pool="Exactly prepared v2 train, including only its audited augmentations; no v1 build_training call",
                           calibration=category_scores(classifier.predict_proba([to_op(r) for r in cal]), cy))
    out.mkdir(parents=True)
    classifier.save(out)
    # Score the actual compact float16 artifact that will be used at final
    # evaluation, not a more precise temporary training matrix.
    saved = Classifier.load(out)
    score = category_scores(saved.predict_proba([to_op(r) for r in cal]), cy)
    (out / "calibration.json").write_text(json.dumps(score, indent=2) + "\n")
    print(json.dumps(dict(calibration=score, fit=classifier.meta["fit"])), flush=True)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    fit(args.prepared, args.out)


if __name__ == "__main__":
    main()
