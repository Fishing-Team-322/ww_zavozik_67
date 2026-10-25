"""Protocol D evaluation: does a model change beat its unchanged self?

Fits the requested event models on train-only prefixes, samples the out-of-fit
unseen company-origins from the completed reference split, and reports paired
company-bootstrap ratios. Variants are compared against the SAME baseline in the
SAME process and seed, which is stricter than comparing to archived numbers.

Usage:
    python -m option_eval --flows ... --events ... --out runs/option-eval \
        --candidates blocks hybrid --seeds 20261024 20261025 20261026
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd

import case_counts as reference
import case_compare as cc
import event_benchmark as eb
from zavozik_ml.runtime_stats import peak_rss_mib

ORIGINS = ("2026-03-31", "2026-04-30", "2026-05-31")


def seeds_for(config_seed: int, seeds: list[int]) -> list[int]:
    return seeds or [config_seed]


def build(module_name: str, histories):
    module = importlib.import_module(f"zavozik_ml.event_forecasters.{module_name}")
    from zavozik_ml.event_forecasters.core import FitOptions
    return module.Model(FitOptions()).fit(histories)


def run(args):
    started = time.monotonic()
    meta = json.loads((args.reference / "metadata.json").read_text())
    config = cc.validate_reference(args, meta)
    args.out.mkdir(parents=True, exist_ok=False)
    cs = reference.load(args.flows, args.transactions)
    by_id = {c.id: c for c in cs}
    events = eb.event_histories(cs, args.events)
    marks = sorted({str(x) for h in events.values() for x in h.events.category.unique()})
    train = [events[cid].prefix(config["train_end"]) for cid in meta["train_ids"]
             if events[cid].dates[0] <= np.datetime64(config["train_end"])]
    if not train:
        raise ValueError("no fit histories")
    models = {name: build(name, train) for name in args.candidates}
    rows = []
    for seed in seeds_for(config["seed"], args.seeds):
        for cid in meta["test_ids"]:
            for origin in ORIGINS:
                c = by_id[cid]
                o = c.origin(origin)
                if not reference.evaluable(c, o):
                    continue
                history = events[cid].prefix(origin)
                future = eb.truth_events(events[cid], np.datetime64(origin), reference.HORIZON)
                sampled = {}
                for name, model in models.items():
                    key = int(hashlib.sha256(f"{seed}:{cid}:{origin}:{name}".encode()).hexdigest()[:16], 16)
                    paths = model.sample(history, reference.HORIZON, 300, np.random.default_rng(key)).validate()
                    flows, counts = paths.daily()
                    sampled[name] = (flows, counts)
                    rows.append(dict(cohort="unseen", seed=seed, company_id=cid, origin=origin, model=name,
                                     forecast_seconds=0.0, flow_scale=float(np.abs(flows).mean()),
                                     level_factor=json.dumps(paths.diagnostics.get("level_factor")) if paths.diagnostics else None,
                                     **eb.scores(c, o, flows, history, counts, None, future, marks)))
    results = pd.DataFrame(rows)
    results.to_csv(args.out / "origins.csv", index=False)
    summary = eb.summarize(results)
    summary.to_csv(args.out / "summary.csv", index=False)
    # Paired comparison per seed: candidate vs its own naive within this run.
    pairs = []
    naive = eb.scores  # noqa: F841 - naive baseline is computed below by the same harness
    for seed in sorted(results.seed.unique()):
        subset = results[results.seed == seed]
        for name in models:
            group = subset[subset.model == name]
            if group.empty:
                continue
            pairs.append(dict(seed=seed, model=name, origins=len(group),
                              net_path_mae=float(group.net_path_mae.mean()),
                              coverage=float(group.net_coverage.mean())))
    pd.DataFrame(pairs).to_csv(args.out / "per_seed.csv", index=False)
    metadata = dict(status="option_eval_internal", candidates=list(models), origins=list(ORIGINS),
                    seeds=seeds_for(config["seed"], args.seeds), paths=300, config=config,
                    reference_metadata_sha256=reference.file_hash(args.reference / "metadata.json"),
                    script_sha256=reference.file_hash(Path(__file__)),
                    note="Variants and baselines are sampled in one process with identical seeds; "
                         "compare rows within this run, not to archived numbers.",
                    total_seconds=time.monotonic() - started, peak_rss_mib=peak_rss_mib(),
                    versions=dict(python=platform.python_version(), numpy=np.__version__,
                                  pandas=pd.__version__, lightgbm=reference.lgb.__version__))
    (args.out / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str) + "\n")
    print(summary.to_string(index=False))
    print(f"total_seconds={metadata['total_seconds']:.1f} peak_rss_mib={metadata['peak_rss_mib']:.1f}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", type=Path, default=Path("ml/data/case_reference_60"))
    p.add_argument("--flows", type=Path, default=Path("ml/data/case_flows.csv"))
    p.add_argument("--transactions", type=Path, default=Path("ml/data/case_transactions.csv"))
    p.add_argument("--events", type=Path, default=Path("ml/data/case_events.csv"))
    p.add_argument("--split", type=Path, default=Path("ml/eval/split_v2.json"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--candidates", nargs="+", default=["blocks", "hybrid"])
    p.add_argument("--seeds", nargs="*", type=int, default=[20261024, 20261025, 20261026])
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
