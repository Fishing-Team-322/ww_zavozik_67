"""Measure the complete CPU classifier on distinct calibration operations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import time

import numpy as np

from .data import ML_DIR, read_rows, operation
from .model import EncoderClassifier, sha256_file
from .text import encoder_text


def benchmark(model: EncoderClassifier, rows: list[dict], repeats: int = 10) -> dict:
    if repeats < 3:
        raise ValueError("at least 3 repetitions required")
    by_text = {}
    for row in rows:
        op = operation(row)
        by_text.setdefault(encoder_text(op), op)
    if len(by_text) < 256:
        raise ValueError("need 256 genuinely distinct normalized operations")
    population = sorted(by_text)
    indices = np.random.default_rng(42).choice(len(population), 256, replace=False)
    texts = [population[i] for i in indices]
    sample = [by_text[s] for s in texts]
    model.predict(sample)
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        output = model.predict(sample)
        timings.append(time.perf_counter() - started)
        if len(output) != 256:
            raise ValueError("unexpected output length")
    return {"model_version": model.model_version, "runtime": model.config["runtime"],
            "batch_size": 256, "distinct_normalized_inputs": len(set(texts)),
            "source": "calibration companies, fixed seed42; no final test selection",
            "includes": "normalization, tokenization, CPU encoder, all heads, probability dictionaries and attributes",
            "excludes": "process/model startup, network serialization", "warmup": 1, "repeats": repeats,
            "torch_worker_ipc_included": type(model.encode).__name__ == "TorchProcessEncoder",
            "median_s": float(np.median(timings)), "p95_s": float(np.quantile(timings, .95)),
            "max_s": max(timings), "times_s": timings, "cpu_threads": model.config.get("cpu_threads", 4),
            "normalized_text_chars": {"median": float(np.median([len(s) for s in texts])), "max": max(map(len, texts))},
            "host": {"system": platform.system(), "machine": platform.machine(), "processor": platform.processor()},
            "local_measurement_not_server_sla": True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--prepared", type=Path, default=ML_DIR / "data/classifier_v2/prepared")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--repeats", type=int, default=10)
    args = p.parse_args()
    runtime = json.loads((args.model / "config.json").read_text())["runtime"]
    if runtime == "torch":
        from zavozik_ml.serving.torch_process import load_isolated_classifier
        model = load_isolated_classifier(args.model)
    else:
        model = EncoderClassifier.load(args.model)
    try:
        report = benchmark(model, read_rows(args.prepared / "calibration_full.jsonl"), args.repeats)
    finally:
        if hasattr(model.encode, "close"):
            model.encode.close()
    report["manifest_sha256"] = sha256_file(args.model / "manifest.json")
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
