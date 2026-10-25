"""Open economic contrasts after metric adaptation, never an accuracy audit.

Reuse exactly the exposed authored cases, encode once, and compare original,
train-centered and every supplied fit. No thresholds, fit, category inventory,
or final labels are read or selected here.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import numpy as np

from zavozik_ml.classify_v2.model import sha256_file, unit
from .candidate_models import CandidateEncoder, MODELS
from .economic_regressions import CASES
from .metric_evaluation import project
from .normalization import analyze


def summarize(vectors_by_level, cases=CASES):
    results = []
    for i, (identity, level, anchor, positive, negative) in enumerate(cases):
        a, p, n = vectors_by_level[level][3*i:3*i+3]
        pos, neg = float(a @ p), float(a @ n)
        results.append(dict(id=identity, level=level, anchor=anchor, positive=positive,
                            negative=negative, positive_cosine=pos, negative_cosine=neg,
                            ranking_margin=pos-neg, expected_order_observed=pos > neg))
    return dict(cases=results, expected_order_count=sum(r["expected_order_observed"] for r in results),
                total_open_development_contrasts=len(results))


def load_heads(path, cache, dimension):
    manifest = json.loads((path / "manifest.json").read_text())
    if (manifest["cache_manifest_sha256"] != sha256_file(cache / "manifest.json") or
            manifest["head_sha256"] != sha256_file(path / "best_heads.npz") or
            manifest["output_dimension_per_level"] != dimension):
        raise ValueError("head/cache/dimension provenance mismatch")
    with np.load(path / "best_heads.npz", allow_pickle=False) as data:
        weights = {k: data[k].copy() for k in data.files}
    return manifest, weights


def run(model: str, base: Path, cache: Path, heads: list[Path], out: Path, device="cpu"):
    if out.exists():
        raise ValueError("open diagnostic output exists; never overwrite")
    encoded = json.loads((cache / "manifest.json").read_text())
    spec = MODELS[model]
    if encoded["model"] != model or encoded["recipe"] != asdict(spec):
        raise ValueError("encoder/cache recipe mismatch")
    if sha256_file(cache / "train.npy") != encoded["train"]["sha256"]:
        raise ValueError("training centering features changed")
    train = np.load(cache / "train.npy", allow_pickle=False)
    if train.ndim != 2 or train.shape[1] != spec.dimension or not np.isfinite(train).all():
        raise ValueError("invalid centering features")
    if len({p.resolve() for p in heads}) != len(heads):
        raise ValueError("duplicate fit supplied")
    fits = [(path, *load_heads(path, cache, spec.dimension)) for path in heads]
    views = [analyze(text) for case in CASES for text in case[2:]]
    if not all(v.usable for v in views):
        raise ValueError("open contrast lost its economic object")
    load_start = time.perf_counter()
    encoder = CandidateEncoder(model, base, device=device)
    load_seconds = time.perf_counter()-load_start
    if encoder.source != encoded["base"]:
        raise ValueError("encoder/cache base provenance mismatch")
    out.mkdir(parents=True)
    report = dict(model=model, source="agent_authored_open_development_regressions",
        purpose="Known-error transfer/debugging; NOT model/threshold selection or semantic accuracy",
        status="research_not_deployable", independent_test=False, semantic_accuracy=None,
        final_test_read=False, category_inventory="not_used", full_encoder_fine_tuning=False,
        device=device, recipe=asdict(spec), base=encoder.source,
        cache_manifest_sha256=sha256_file(cache / "manifest.json"),
        code_sha256={name:sha256_file(Path(__file__).with_name(name)) for name in
                     ("adapted_regressions.py", "economic_regressions.py", "normalization.py",
                      "candidate_models.py", "metric_evaluation.py")},
        encoder_load_seconds=load_seconds, comparisons={})
    (out / "started.json").write_text(json.dumps(report, indent=2)+"\n")
    started = time.perf_counter()
    x = encoder([v.semantic_text for v in views])
    report["encoding_seconds"] = time.perf_counter()-started
    np.save(out / "open_features.npy", x, allow_pickle=False)
    report["open_features_sha256"] = sha256_file(out / "open_features.npy")
    report["comparisons"]["original"] = summarize({level:x for level in ("coarse", "fine")})
    centered = unit(x-train.mean(0))
    report["comparisons"]["centered"] = summarize({level:centered for level in ("coarse", "fine")})
    for path, manifest, weights in fits:
        record = summarize({level:project(x, weights, level) for level in ("coarse", "fine")})
        record.update(heads_path=str(path.resolve()), seed=manifest["seed"],
                      best_epoch=manifest["best_epoch"],
                      heads_manifest_sha256=sha256_file(path / "manifest.json"))
        report["comparisons"][path.name] = record
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", choices=tuple(MODELS), required=True)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--heads", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    a = p.parse_args()
    r = run(a.model, a.base, a.cache, a.heads, a.out, a.device)
    print(json.dumps({k:v["expected_order_count"] for k,v in r["comparisons"].items()}))


if __name__ == "__main__":
    main()
