"""Immutable train/calibration embeddings for a fair candidate comparison.

No fit, threshold search, final-test read or category accuracy claim. Two-level
verified pair labels are required before ranking candidates by semantic quality.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import numpy as np

from zavozik_ml.classify_v2.model import sha256_file
from .candidate_models import MODELS, CandidateEncoder
from .corpus import read_rows
from .normalization import TEXT_VERSION
from .preparation import PROTOCOL


def cache(corpus: Path, base: Path, out: Path, model: str, device="cpu"):
    if out.exists():
        raise ValueError("candidate cache exists; refuse overwrite")
    meta = json.loads((corpus / "manifest.json").read_text())
    spec = MODELS[model]
    if meta["protocol"] != PROTOCOL or meta["text_version"] != TEXT_VERSION:
        raise ValueError("unsupported prepared corpus/text version")
    recipe = meta["tokenizers"].get(spec.model_id + "@" + spec.revision, {}).get("recipe")
    if recipe != asdict(spec):
        raise ValueError("candidate input recipe not audited before splitting")
    expected_normalizer = meta["source_files_sha256"]["zavozik_ml/category_discovery/normalization.py"]
    if sha256_file(Path(__file__).with_name("normalization.py")) != expected_normalizer:
        raise ValueError("normalizer changed after preparation")
    parts = {}
    for part in ("train", "calibration"):
        path = corpus / f"{part}_unique.jsonl"
        if sha256_file(path) != meta[part]["unique_sha256"]:
            raise ValueError("corpus changed")
        parts[part] = read_rows(path)
    encoder = CandidateEncoder(model, base, device=device)
    report = dict(model=model, recipe=asdict(spec), text_version=TEXT_VERSION, base=encoder.source,
                  corpus_manifest_sha256=sha256_file(corpus / "manifest.json"),
                  semantic_accuracy=None, fine_tuning=False, final_test_read=False, device=device,
                  code_sha256={name: sha256_file(Path(__file__).with_name(name)) for name in
                               ("candidate_cache.py", "candidate_models.py", "normalization.py")})
    out.mkdir(parents=True)
    # Preserve provenance before the first forward pass, including on failure.
    (out / "started.json").write_text(json.dumps(report, indent=2) + "\n")
    for part, rows in parts.items():
        started = time.perf_counter()
        x = encoder([r["semantic_text"] for r in rows])
        if x.shape != (len(rows), spec.dimension) or not np.isfinite(x).all():
            raise ValueError("bad candidate output")
        np.save(out / f"{part}.npy", x, allow_pickle=False)
        report[part] = dict(rows=len(x), shape=list(x.shape), seconds=time.perf_counter()-started,
                            sha256=sha256_file(out / f"{part}.npy"),
                            unique_sha256=meta[part]["unique_sha256"])
        print(f"{model}: {part} {len(x)} rows {report[part]['seconds']:.2f}s", flush=True)
    (out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--model", choices=MODELS, required=True)
    p.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    a = p.parse_args()
    print(json.dumps(cache(a.corpus, a.base, a.out, a.model, a.device), indent=2))


if __name__ == "__main__":
    main()
