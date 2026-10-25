"""Offline CPU encoder/head benchmark, explicitly NOT RPC/service latency.

Use a fresh process per model. Inputs are length-spread training examples;
there are no labels, final/test reads, external requests or quality selection.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np

from zavozik_ml.classify_v2.model import sha256_file, unit
from .adapted_regressions import load_heads
from .candidate_models import CandidateEncoder, MODELS
from .corpus import read_rows
from .metric_evaluation import project


def statistics(values):
    return dict(samples=len(values),p50_seconds=float(np.median(values)),
                p95_seconds=float(np.percentile(values,95)),minimum_seconds=min(values),
                maximum_seconds=max(values))


def run(model,base,corpus,cache,heads,out,*,repeats=12,threads=4):
    if out.exists() or repeats < 10 or not 1 <= threads <= 8:
        raise ValueError("new benchmark output, at least10 repeats, threads1..8 required")
    spec=MODELS[model]; meta=json.loads((corpus/"manifest.json").read_text())
    encoded=json.loads((cache/"manifest.json").read_text())
    source=corpus/"train_unique.jsonl"
    if (sha256_file(source)!=meta["train"]["unique_sha256"] or
            encoded["corpus_manifest_sha256"]!=sha256_file(corpus/"manifest.json") or
            encoded["model"]!=model or encoded["recipe"]!=asdict(spec) or
            sha256_file(cache/"train.npy")!=encoded["train"]["sha256"]):
        raise ValueError("training/cache/encoder provenance mismatch")
    rows=sorted((r for r in read_rows(source) if r["usable"]),
                key=lambda r:(len(r["semantic_text"]),r["content_key"]))
    if len(rows)<64:
        raise ValueError("benchmark requires at least64 training inputs")
    cohort=[rows[int(i)] for i in np.linspace(0,len(rows)-1,64,dtype=int)]
    texts=[r["semantic_text"] for r in cohort]
    fit,weights=load_heads(heads,cache,spec.dimension)
    mean=np.load(cache/"train.npy",allow_pickle=False).mean(0)
    out.mkdir(parents=True)
    report=dict(scope="offline_cpu_encoder_and_postprocessing_microbenchmark_not_rpc",
        model=model,recipe=asdict(spec),device="cpu",threads=threads,repeats_per_batch=repeats,
        input_selection="64 deterministic length-spread usable training inputs",
        input_content_keys=[r["content_key"] for r in cohort],
        input_semantic_text_sha256=hashlib.sha256(json.dumps(texts,ensure_ascii=False).encode()).hexdigest(),
        input_char_lengths=dict(minimum=min(map(len,texts)),median=float(np.median(list(map(len,texts)))),
                                maximum=max(map(len,texts))),
        corpus_manifest_sha256=sha256_file(corpus/"manifest.json"),
        cache_manifest_sha256=sha256_file(cache/"manifest.json"),
        heads_manifest_sha256=sha256_file(heads/"manifest.json"),head_seed=fit["seed"],
        code_sha256=sha256_file(Path(__file__)),platform=platform.platform(),
        packages={name:version(name) for name in ("torch","transformers","numpy")},
        final_test_read=False,quality_evaluated=False,semantic_accuracy=None,
        limitations="Single fresh-process local CPU run; small nonrandom length-spread cohort. Encoder batch latency and head-only latency, not RPC p95, concurrency, end-to-end classification, or general server capacity.")
    (out/"started.json").write_text(json.dumps(report,indent=2)+"\n")
    begin=time.perf_counter();encoder=CandidateEncoder(model,base,device="cpu",batch_size=8,threads=threads)
    report["cold_load_and_file_verification_seconds"]=time.perf_counter()-begin
    if encoder.source!=encoded["base"]:
        raise ValueError("base/cache source mismatch")
    report["base_payload_bytes"]=sum((base/name).stat().st_size for name in encoder.source["files_sha256"])
    report["learned_two_heads_bytes"]=(heads/"best_heads.npz").stat().st_size
    report["batches"]={}
    for batch in (1,8):
        encoder(texts[:batch])  # explicit warmup outside timing
        timings=[]; timed_keys=[]
        # Spread EACH batch-size's timed requests across the whole length
        # range. Sequential offsets made batch1 time only the shortest12/64.
        for start in np.linspace(0,len(texts)-batch,repeats,dtype=int):
            chosen=[texts[(start+i)%len(texts)] for i in range(batch)]
            timed_keys.append([cohort[(start+i)%len(texts)]["content_key"] for i in range(batch)])
            begin=time.perf_counter(); x=encoder(chosen);timings.append(time.perf_counter()-begin)
        post={}
        for name,transform in [
            ("centered_two_levels",lambda z:(unit(z-mean),unit(z-mean))),
            ("adapted_two_levels",lambda z:(project(z,weights,"coarse"),project(z,weights,"fine")))]:
            overhead=[]
            for _ in range(30):
                begin=time.perf_counter();transform(x);overhead.append(time.perf_counter()-begin)
            post[name]=statistics(overhead)
        report["batches"][str(batch)]=dict(encoder=statistics(timings),encoder_seconds=timings,
            timed_input_content_keys=timed_keys,
            postprocessing_only=post,throughput_operations_per_second=batch/float(np.median(timings)))
        print(model,"batch",batch,"p50",np.median(timings),flush=True)
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report["process_peak_rss_bytes"]=int(rss if platform.system()=="Darwin" else rss*1024)
    report["process_peak_rss_mib"]=report["process_peak_rss_bytes"]/2**20
    (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model",choices=tuple(MODELS),required=True)
    for name in ("base","corpus","cache","heads","out"):
        p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args();r=run(a.model,a.base,a.corpus,a.cache,a.heads,a.out)
    print(json.dumps(dict(model=r["model"],peak_rss_mib=r["process_peak_rss_mib"])))


if __name__=="__main__":
    main()
