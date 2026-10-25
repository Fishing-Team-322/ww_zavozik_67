"""Adjustment experiment: multi-origin evaluation, path mixture, spread calibration.

Research only. Reuses the completed count reference for the company split and the
event-generator pickles from a finished event_benchmark run, so no model is refit
except the count bootstrap (cheap).

IMPORTANT: the pickled models were fitted on prefixes ending 2026-03-31. Origins
before that date therefore forecast windows the models already saw; the runner
records `in_fit` per origin so pooled results can be split honestly.

Variants compared on identical origins:
  * base models (seasonal naive, gbm_global, ensemble, blocks, hybrid, count bootstrap)
  * `mixture`: equal path shares from blocks + hybrid + gbm_global, weights fixed
    before any result is inspected
  * `<model>+spread`: per-model p10-p90 width multiplier chosen on the calibration
    companies only, from a fixed grid, applied around each direction's daily median
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd

import case_counts as reference
import case_compare as cc
import event_benchmark as eb
from zavozik_ml import calendar as cal
from zavozik_ml import data
from zavozik_ml.forecasters import base, ensemble, gbm  # noqa: F401

BASE_MODELS = ("seasonal_naive", "gbm_global", "ensemble", "blocks", "hybrid", "count_bootstrap")
MIX_MEMBERS = ("blocks", "hybrid", "gbm_global")
SPREAD_MODELS = ("blocks", "hybrid", "mixture")
SPREAD_GRID = np.round(np.arange(0.5, 1.81, 0.1), 2)
TARGET_COVERAGE = 0.80


def monthly_origins(start: str, end: str) -> list[str]:
    """Month-end forecast origins in [start, end], inclusive."""
    grid = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="ME")
    return [d.strftime("%Y-%m-%d") for d in grid]


def scale_paths(flows: np.ndarray, factor: float) -> np.ndarray:
    """Widen/narrow each direction around its per-day median, then clip at zero.

    This is a width control on daily flows. Net-path quantiles move in the same
    direction but not exactly proportionally, because clipping is applied after
    scaling and because medians are per direction.
    """
    if factor <= 0:
        raise ValueError("spread factor must be positive")
    if flows.ndim != 3 or flows.shape[-1] != 2:
        raise ValueError("flows must be [paths, days, 2]")
    median = np.median(flows, axis=0, keepdims=True)
    scaled = np.clip(median + factor * (flows - median), 0, None)
    if not np.isfinite(scaled).all():
        raise ValueError("scaled paths must be finite")
    return scaled


def mixture_paths(parts: dict[str, np.ndarray], n_paths: int) -> np.ndarray:
    """Concatenate whole paths from each member in equal, pre-declared shares."""
    if not parts:
        raise ValueError("mixture needs at least one member")
    share = n_paths // len(parts)
    if share < 1:
        raise ValueError("path budget too small for a mixture")
    chunks = [np.asarray(parts[name])[:share] for name in parts]
    mixed = np.concatenate(chunks, axis=0)
    if mixed.shape[0] != n_paths:
        raise ValueError(f"mixture produced {mixed.shape[0]} paths, expected {n_paths}")
    return mixed


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Runner:
    def __init__(self, args, config, meta):
        self.args, self.config, self.meta = args, config, meta
        self.cs = reference.load(args.flows, args.transactions)
        self.by_id = {c.id: c for c in self.cs}
        self.events = eb.event_histories(self.cs, args.events)
        self.native = {c.id: c for c in data.load_companies(args.flows)}
        self.marks = sorted({str(x) for h in self.events.values() for x in h.events.category.unique()})
        self.models, self.artifacts = {}, {}
        for name in ("blocks", "hybrid"):
            path = args.models_dir / f"{name}.pickle"
            with path.open("rb") as handle:
                self.models[name] = pickle.load(handle)  # trusted local research artifact
            self.artifacts[str(path)] = _sha256(path)
        if not base.get("gbm_global").load(args.models_dir / "gbm_global"):
            raise ValueError("gbm_global artifact failed to load")
        for name in ("meta.json", "in.txt", "out.txt"):
            artifact = args.models_dir / "gbm_global" / name
            if artifact.exists():
                self.artifacts[str(artifact)] = _sha256(artifact)
        industries = {name: i for i, name in enumerate(sorted({self.by_id[cid].industry for cid in meta["train_ids"]}))}
        self.count_models, _ = reference.train([self.by_id[cid] for cid in meta["train_ids"]], config["train_end"],
                                               industries, config["rounds"], args.threads, config["seed"])
        self.alpha = reference.dispersion(self.count_models, [self.by_id[cid] for cid in meta["calibration_ids"]],
                                          config["calibration_origin"], industries, as_of=min(config["test_origins"]))
        self.industries = industries
        self.n_paths = int(config["paths"])
        self.calibration_skips: list[dict] = []

    def sample(self, cid, origin, models):
        """Return {model: (flows, counts)} for one company/origin, deterministic per model."""
        c = self.by_id[cid]
        o = c.origin(origin)
        history = self.events[cid].prefix(origin)
        result = {}
        for name in models:
            seed = int(reference.hashlib.sha256(f"{self.config['seed']}:{cid}:{origin}:{name}".encode()).hexdigest()[:16], 16)
            rng = np.random.default_rng(seed)
            if name in self.models:
                paths = self.models[name].sample(history, reference.HORIZON, self.n_paths, rng).validate()
                if (paths.n_paths != self.n_paths or paths.horizon != reference.HORIZON
                        or paths.origin != history.as_of):
                    raise ValueError(f"{name} changed the requested scenario budget or dates")
                flows, counts = paths.daily()
            elif name == "count_bootstrap":
                mu = reference.expected(self.count_models, c, o, self.industries)
                flows, counts = reference.simulate(c, o, self.n_paths, rng, mu, self.alpha)
            else:
                sampled = base.get(name).forecast(self.native[cid].history.head(o + 1), reference.HORIZON,
                                                  self.n_paths, rng)
                flows, counts = np.stack([sampled.inflow, sampled.outflow], axis=-1), None
            if flows.shape != (self.n_paths, reference.HORIZON, 2):
                raise ValueError(f"{name} produced {flows.shape}, expected {(self.n_paths, reference.HORIZON, 2)}")
            result[name] = (flows, counts)
        return c, o, history, result

    def net(self, flows):
        return np.cumsum(flows[:, :, 0] - flows[:, :, 1], axis=1)

    def fit_spread(self, origins):
        """Choose one width multiplier per model on calibration companies only."""
        hits = {name: np.zeros(len(SPREAD_GRID)) for name in SPREAD_MODELS}
        total = pairs = 0
        for cid in self.meta["calibration_ids"]:
            for origin in origins:
                if not reference.evaluable(self.by_id[cid], self.by_id[cid].origin(origin)):
                    self.calibration_skips.append(dict(company_id=cid, origin=origin))
                    continue
                c, o, _, sampled = self.sample(cid, origin, tuple(dict.fromkeys((*MIX_MEMBERS, "blocks", "hybrid"))))
                actual = np.cumsum(c.flows[o + 1:o + 1 + reference.HORIZON, 0]
                                   - c.flows[o + 1:o + 1 + reference.HORIZON, 1])
                variants = {"blocks": sampled["blocks"][0], "hybrid": sampled["hybrid"][0]}
                variants["mixture"] = mixture_paths({n: sampled[n][0] for n in MIX_MEMBERS}, self.n_paths)
                for name, flows in variants.items():
                    for i, factor in enumerate(SPREAD_GRID):
                        net = self.net(scale_paths(flows, factor))
                        q = np.quantile(net, [.1, .9], axis=0)
                        hits[name][i] += ((actual >= q[0]) & (actual <= q[1])).sum()
                total += reference.HORIZON
                pairs += 1
        if total == 0:
            raise ValueError("no calibration origins were evaluable")
        chosen, curves = {}, {}
        for name, counts in hits.items():
            coverage = counts / total
            curves[name] = {f"{f:.2f}": float(c) for f, c in zip(SPREAD_GRID, coverage)}
            best = int(np.argmin(np.abs(coverage - TARGET_COVERAGE)))
            chosen[name] = dict(factor=float(SPREAD_GRID[best]), coverage=float(coverage[best]))
        self.calibration_pairs = pairs
        return chosen, curves

    def evaluate(self, cohorts, origins, factors):
        rows, skipped = [], []
        for cohort, ids in cohorts:
            for cid in ids:
                for origin in origins:
                    c = self.by_id[cid]
                    if not reference.evaluable(c, c.origin(origin)):
                        skipped.append(dict(cohort=cohort, company_id=cid, origin=origin))
                        continue
                    tick = time.monotonic()
                    c, o, history, sampled = self.sample(cid, origin, BASE_MODELS)
                    elapsed = time.monotonic() - tick
                    future = eb.truth_events(self.events[cid], np.datetime64(origin), reference.HORIZON)
                    variants = {name: sampled[name] for name in BASE_MODELS}
                    mixed = mixture_paths({n: sampled[n][0] for n in MIX_MEMBERS}, self.n_paths)
                    variants["mixture"] = (mixed, None)
                    for name in SPREAD_MODELS:
                        variants[name + "+spread"] = (scale_paths(variants[name][0], factors[name]["factor"]), None)
                    for name, (flows, counts) in variants.items():
                        rows.append(dict(cohort=cohort, company_id=cid, origin=origin, model=name,
                                         in_fit=bool(np.datetime64(origin) + np.timedelta64(reference.HORIZON, "D")
                                                     <= np.datetime64(self.config["train_end"])),
                                         forecast_seconds=elapsed / max(len(variants), 1),
                                         **eb.scores(c, o, flows, history, counts, None, future, self.marks)))
        return pd.DataFrame(rows), skipped


def run(args):
    started = time.monotonic()
    meta = json.loads((args.reference / "metadata.json").read_text())
    config = cc.validate_reference(args, meta)
    args.out.mkdir(parents=True, exist_ok=False)
    runner = Runner(args, config, meta)
    test_origins = args.origins or monthly_origins(args.origin_start, args.origin_end)
    audit_start = np.datetime64(json.loads(args.split.read_text())["audit_start"])
    for origin in (*test_origins, *args.calibration_origins):
        if np.datetime64(origin) + np.timedelta64(reference.HORIZON, "D") >= audit_start:
            raise ValueError(f"origin {origin} would cross the frozen audit boundary")
    if max(args.calibration_origins) >= min(test_origins):
        raise ValueError("calibration origins must precede evaluation origins")
    factors, curves = runner.fit_spread(args.calibration_origins)
    cohorts = (("unseen", meta["test_ids"]), ("seen_future", meta["train_ids"]))
    results, skipped = runner.evaluate(cohorts, test_origins, factors)
    eb.assert_paired(results, tuple(results.model.unique()))
    results.to_csv(args.out / "origins.csv", index=False)
    summary = eb.summarize(results)
    summary.to_csv(args.out / "summary.csv", index=False)
    out_of_fit = results[~results.in_fit]
    if not out_of_fit.empty:
        eb.summarize(out_of_fit).to_csv(args.out / "summary_out_of_fit.csv", index=False)
    metadata = dict(status="adjustment_experiment_internal_reference", config=config,
                    reference_metadata_sha256=reference.file_hash(args.reference / "metadata.json"),
                    models_dir=str(args.models_dir), model_artifact_sha256=runner.artifacts,
                    script_sha256=_sha256(Path(__file__)),
                    origins=test_origins, out_of_fit_origins=sorted(results.loc[~results.in_fit, "origin"].unique().tolist()),
                    in_fit_origins=sorted(results.loc[results.in_fit, "origin"].unique().tolist()),
                    calibration_origins=args.calibration_origins,
                    calibration_pairs=runner.calibration_pairs, calibration_skips=runner.calibration_skips,
                    spread=factors, spread_coverage_curves=curves,
                    mixture_members=MIX_MEMBERS, paths=runner.n_paths, threads=args.threads,
                    rounds=config["rounds"], spread_grid=SPREAD_GRID.tolist(),
                    skipped_evaluations=skipped,
                    limitation="Model pickles were fitted on prefixes ending at train_end, so origins whose 30-day window ends on or before train_end are in-sample; see in_fit_origins/out_of_fit_origins and summary_out_of_fit.csv. Overlapping 30-day windows share future data, so company-origin rows are not independent. Spread factors are chosen on calibration companies only; mixing weights are fixed a priori.",
                    total_seconds=time.monotonic() - started,
                    peak_rss_mib=eb.peak_rss_mib(),
                    versions=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
                                  lightgbm=reference.lgb.__version__, torch=eb._torch_version()))
    (args.out / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str) + "\n")
    print(summary.to_string(index=False))
    print(f"spread={json.dumps(factors)} calibration_pairs={runner.calibration_pairs} "
          f"total_seconds={metadata['total_seconds']:.1f}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--models-dir", type=Path, required=True, help="finished event_benchmark output dir with pickles")
    p.add_argument("--flows", type=Path, required=True)
    p.add_argument("--transactions", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--split", type=Path, default=Path("ml/eval/split_v2.json"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--origins", nargs="+", default=None,
                   help="explicit origin dates; default is month-ends in [origin-start, origin-end]")
    p.add_argument("--origin-start", default="2025-07-31")
    p.add_argument("--origin-end", default="2026-05-31")
    p.add_argument("--calibration-origins", nargs="+", default=["2025-06-30", "2025-07-31"])
    p.add_argument("--threads", type=int, default=8)
    args = p.parse_args()
    if args.threads < 1:
        p.error("threads must be positive")
    run(args)


if __name__ == "__main__":
    main()
