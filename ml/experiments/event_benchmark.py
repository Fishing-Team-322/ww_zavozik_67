"""Matched case-only event-generator benchmark. Train on the designated host.

Five event generators are scored on sampled event-set projections and downstream
cash flows. Existing aggregate models are scored only where their outputs apply.
The completed case_counts reference fixes companies, dates and simulation budget.
"""
from __future__ import annotations

import argparse
import importlib
import json
import pickle
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist

import case_counts as reference
from case_compare import assert_paired, histories_for_training, validate_reference, verify_count_replay
from zavozik_ml import calendar as cal
from zavozik_ml import data
from zavozik_ml.runtime_stats import peak_rss_mib
from zavozik_ml.event_forecasters.core import EventHistory, FitOptions
from zavozik_ml.forecasters import base, ensemble, gbm  # noqa: F401

EVENT_MODELS = ("blocks", "renewal", "marked_counts", "hybrid", "gru")
SAFETY_MODELS = ("seasonal_naive", "gbm_global", "ensemble", "count_bootstrap")


def event_histories(companies, path):
    """Read canonical events and prove they match the earlier business export."""
    frame = pd.read_csv(path, parse_dates=["date"], dtype={"company_id": str, "counterparty": str})
    for name in ("counterparty", "category"):
        if name not in frame:
            frame[name] = "" if name == "counterparty" else "unknown"
    frame["counterparty"] = frame.counterparty.fillna("")
    frame["category"] = frame.category.fillna("unknown").astype(str)
    frame["direction"] = frame.direction.map({"in": 0, "out": 1})
    if frame.direction.isna().any():
        raise ValueError("invalid canonical event direction")
    frame["direction"] = frame.direction.astype(int)
    by_id = {c.id: c for c in companies}
    if not set(frame.company_id) <= set(by_id):
        raise ValueError("event export contains unknown companies")
    result = {}
    for cid, c in by_id.items():
        ev = frame.loc[frame.company_id == cid, ["date", "direction", "amount", "category", "counterparty"]].copy()
        h = EventHistory(cid, c.industry, c.dates.copy(), c.missing.copy(), c.detected.copy(), ev)
        counts, amounts = np.zeros_like(c.counts), np.zeros_like(c.flows)
        if len(ev):
            days = (ev.date.to_numpy(dtype="datetime64[D]") - c.dates[0]).astype(int)
            np.add.at(counts, (days, ev.direction.to_numpy()), 1.)
            np.add.at(amounts, (days, ev.direction.to_numpy()), ev.amount.to_numpy())
        if not np.array_equal(counts, c.counts) or not np.allclose(amounts, c.flows, atol=.02, rtol=1e-10):
            raise ValueError("event ledger does not reconcile with reference counts/flows")
        result[cid] = h
    return result


def crps(samples, actual):
    """Exact empirical CRPS, vectorized over all non-scenario dimensions."""
    samples = np.asarray(samples, dtype=float)
    if not len(samples) or not np.isfinite(samples).all() or not np.isfinite(actual).all():
        raise ValueError("CRPS requires finite nonempty samples and truth")
    n = len(samples)
    weights = (2 * np.arange(1, n + 1) - n - 1).reshape((n,) + (1,) * (samples.ndim - 1))
    return np.maximum(0., np.abs(samples - actual).mean(axis=0) - (weights * np.sort(samples, axis=0)).sum(axis=0) / n**2)


def energy(samples, truth):
    samples = np.asarray(samples, dtype=float).reshape(len(samples), -1)
    truth = np.asarray(truth, dtype=float).reshape(-1)
    # Empirical-distribution energy score; same ensemble size for every model.
    return float(np.linalg.norm(samples - truth, axis=1).mean() - pdist(samples).sum() / len(samples)**2)


def marked_counts(frame, n_paths, horizon, marks):
    result = np.zeros((n_paths, horizon, 2, len(marks)))
    if len(frame):
        index = {name: i for i, name in enumerate(marks)}
        mark = np.array([index.get(str(x), index["unknown"]) for x in frame.category])
        np.add.at(result, (frame.path.to_numpy(int), frame.day.to_numpy(int) - 1,
                           frame.direction.to_numpy(int), mark), 1.)
    return result


def amount_bin_counts(frame, n_paths, horizon):
    # Fixed product-space bins, including exact zero and unbounded positive tail.
    edges = np.power(10., np.arange(10))
    result = np.zeros((n_paths, horizon, 2, len(edges) + 2))
    if len(frame):
        amounts = frame.amount.to_numpy(float)
        bins = np.where(amounts == 0, 0, np.searchsorted(edges, amounts, side="right") + 1)
        np.add.at(result, (frame.path.to_numpy(int), frame.day.to_numpy(int) - 1,
                           frame.direction.to_numpy(int), bins), 1.)
    return result


def truth_events(h, origin, horizon):
    # This is retrospective scoring truth, never passed into model generation.
    ev = h.raw_events[(h.raw_events.date > pd.Timestamp(origin)) &
                      (h.raw_events.date <= pd.Timestamp(origin + np.timedelta64(horizon, "D")))].copy()
    ev["day"] = (ev.date.to_numpy(dtype="datetime64[D]") - origin).astype(int)
    ev["path"] = 0
    return ev


def scores(c, o, flows, history, counts=None, paths=None, future=None, marks=None):
    if flows.ndim != 3 or flows.shape[1:] != (reference.HORIZON, 2) or not np.isfinite(flows).all() or (flows < 0).any():
        raise ValueError("invalid complete forecast paths")
    row = reference.metrics(c, o, flows, counts)
    actual = c.flows[o + 1:o + 31]
    actual_net = np.cumsum(actual[:, 0] - actual[:, 1])
    net = np.cumsum(flows[:, :, 0] - flows[:, :, 1], axis=1)
    row["daily_amount_crps"] = float(crps(flows, actual).mean())
    row["net_crps"] = float(crps(net, actual_net).mean())
    scale = np.maximum(np.nanmean(history.daily_amounts[-91:], axis=0), 1.)
    row["flow_energy"] = energy(flows / scale, actual / scale)
    normalized = flows / scale
    variograms = []
    for lag in (1, 7):
        predicted = np.sqrt(np.abs(normalized[:, lag:] - normalized[:, :-lag])).mean(axis=0)
        truth = np.sqrt(np.abs(actual[lag:] / scale - actual[:-lag] / scale))
        variograms.append(np.mean((predicted - truth)**2))
    row["flow_variogram"] = float(np.mean(variograms))
    if np.isfinite(c.balance[o]):
        business_actual = c.balance[o] + actual_net
        median = c.balance[o] + np.median(net, axis=0)
        row.update(business_path_abs_error=float(np.abs(business_actual - median).sum()),
                   business_path_actual=float(np.abs(business_actual).sum()))
    if counts is not None:
        actual_counts = c.counts[o + 1:o + 31]
        row["count_crps"] = float(crps(counts, actual_counts).mean())
        row["occurrence_brier"] = float((((counts > 0).mean(axis=0) - (actual_counts > 0))**2).mean())
        count_scale = np.maximum(np.nanmean(history.daily_counts[-91:], axis=0), .25)
        row["event_projection_energy"] = energy(np.concatenate([counts / count_scale, flows / scale], axis=-1),
                                                np.concatenate([actual_counts / count_scale, actual / scale], axis=-1))
    if paths is not None:
        row["marked_count_crps"] = float(crps(marked_counts(paths.events, paths.n_paths, paths.horizon, marks),
                                               marked_counts(future, 1, paths.horizon, marks)[0]).mean())
        row["amount_bin_count_crps"] = float(crps(amount_bin_counts(paths.events, paths.n_paths, paths.horizon),
                                                   amount_bin_counts(future, 1, paths.horizon)[0]).mean())
    return row


def summarize(results):
    rows = []
    averages = ("net_path_mae", "net_mae_7", "net_mae_14", "net_mae_30", "net_coverage", "net_width",
                "net_pinball", "gap_brier", "daily_amount_crps", "net_crps", "flow_energy", "flow_variogram",
                "count_crps", "occurrence_brier", "event_projection_energy", "marked_count_crps", "amount_bin_count_crps")
    for (cohort, name), group in results.groupby(["cohort", "model"]):
        row = dict(cohort=cohort, model=name, origins=len(group), companies=group.company_id.nunique(),
                   flow_wape=group.flow_abs_error.sum() / max(group.flow_actual.sum(), 1e-9),
                   business_path_wape=group.business_path_abs_error.sum() / max(group.business_path_actual.sum(), 1e-9),
                   forecast_seconds=group.forecast_seconds.sum())
        row.update({key: float(group[key].mean()) if key in group and group[key].notna().any() else None for key in averages})
        rows.append(row)
    summary = pd.DataFrame(rows)
    if "seasonal_naive" in summary.model.values:
        for cohort in summary.cohort.unique():
            selected = summary.cohort == cohort
            naive = summary[selected & (summary.model == "seasonal_naive")].iloc[0]
            summary.loc[selected, "net_mae_vs_naive"] = summary.loc[selected, "net_path_mae"] / naive.net_path_mae
    return summary


def run(args):
    started = time.monotonic()
    meta = json.loads((args.reference / "metadata.json").read_text())
    config = validate_reference(args, meta)
    args.out.mkdir(parents=True, exist_ok=False)
    cs = reference.load(args.flows, args.transactions)
    by_id = {c.id: c for c in cs}
    event_data = event_histories(cs, args.events)
    native = {c.id: c for c in data.load_companies(args.flows)}
    train_histories = []
    for cid in meta["train_ids"]:
        if event_data[cid].dates[0] <= np.datetime64(config["train_end"]):
            train_histories.append(event_data[cid].prefix(config["train_end"]))
    if not train_histories:
        raise ValueError("no fit histories")
    options = FitOptions(seed=config["seed"], threads=args.threads, rounds=args.rounds, epochs=args.epochs,
                         max_training_rows=args.max_training_rows, hidden_size=args.hidden_size)
    chosen = list(EVENT_MODELS) if args.models == ["all"] else args.models
    if len(set(chosen)) != len(chosen) or not set(chosen) <= set(EVENT_MODELS):
        raise ValueError("unknown or duplicate event model")
    models, timings = {}, {}
    for name in chosen:
        model = importlib.import_module("zavozik_ml.event_forecasters." + name).Model(options)
        tick = time.monotonic()
        model.fit([h.prefix(h.as_of) for h in train_histories])
        timings[name] = time.monotonic() - tick
        models[name] = model
        with (args.out / f"{name}.pickle").open("wb") as f:
            pickle.dump(model, f)  # trusted local research artifact only; never load untrusted pickle
    names = chosen.copy()
    industries = {name: i for i, name in enumerate(sorted({by_id[cid].industry for cid in meta["train_ids"]}))}
    count_models, alpha = None, None
    old_gbm_params = gbm.PARAMS.copy()
    try:
        if args.safety:
            names.extend(SAFETY_MODELS)
            tick = time.monotonic()
            count_models, _ = reference.train([by_id[cid] for cid in meta["train_ids"]], config["train_end"],
                                              industries, config["rounds"], args.threads, config["seed"])
            timings["count_bootstrap"] = time.monotonic() - tick
            alpha = reference.dispersion(count_models, [by_id[cid] for cid in meta["calibration_ids"]],
                                         config["calibration_origin"], industries, as_of=min(config["test_origins"]))
            gbm.PARAMS = {**old_gbm_params, "num_threads": args.threads}
            tick = time.monotonic()
            base.get("gbm_global").fit(histories_for_training(list(native.values()), meta["train_ids"], config["train_end"]))
            timings["gbm_global"] = time.monotonic() - tick
            base.get("gbm_global").save(args.out / "gbm_global")
        marks = sorted({str(x) for h in train_histories for x in h.events.category.unique()} - {"unknown"}) + ["unknown"]
        rows, skipped, diagnostics, event_files = [], [], [], []
        for cohort, ids in (("unseen", meta["test_ids"]), ("seen_future", meta["train_ids"])):
            for cid in ids:
                c = by_id[cid]
                for origin in config["test_origins"]:
                    o = c.origin(origin)
                    if not reference.evaluable(c, o):
                        skipped.append(dict(cohort=cohort, company_id=cid, origin=origin))
                        continue
                    history = event_data[cid].prefix(origin)
                    future = truth_events(event_data[cid], np.datetime64(origin), reference.HORIZON)
                    for name in names:
                        seed = int(reference.hashlib.sha256(f"{config['seed']}:{cid}:{origin}:{name}".encode()).hexdigest()[:16], 16)
                        rng, tick = np.random.default_rng(seed), time.monotonic()
                        paths, counts = None, None
                        if name in models:
                            paths = models[name].sample(history.prefix(history.as_of), reference.HORIZON, config["paths"], rng).validate()
                            if paths.n_paths != config["paths"] or paths.horizon != reference.HORIZON or paths.origin != history.as_of:
                                raise ValueError("generator changed requested scenario budget or dates")
                            flows, counts = paths.daily()
                        elif name == "count_bootstrap":
                            mu = reference.expected(count_models, c, o, industries)
                            flows, counts = reference.simulate(c, o, config["paths"], rng, mu, alpha)
                        else:
                            sampled = base.get(name).forecast(native[cid].history.head(o + 1), reference.HORIZON, config["paths"], rng)
                            flows = np.stack([sampled.inflow, sampled.outflow], axis=-1)
                        elapsed = time.monotonic() - tick
                        rows.append(dict(cohort=cohort, company_id=cid, origin=origin, model=name, forecast_seconds=elapsed,
                                         **scores(c, o, flows, history, counts, paths, future, marks)))
                        if paths is not None:
                            file = args.out / "events" / name / f"{cid}-{origin}.parquet"
                            file.parent.mkdir(parents=True, exist_ok=True)
                            paths.dated_events().to_parquet(file, index=False)
                            event_files.append(str(file.relative_to(args.out)))
                            diagnostics.append(dict(model=name, company_id=cid, origin=origin, details=paths.diagnostics))
        results = pd.DataFrame(rows)
        assert_paired(results, names)
        if args.safety:
            verify_count_replay(results, pd.read_csv(args.reference / "origins.csv"))
        results.to_csv(args.out / "origins.csv", index=False)
        summary = summarize(results)
        summary.to_csv(args.out / "summary.csv", index=False)
        sources = [Path(__file__), Path(reference.__file__), Path(importlib.import_module("case_compare").__file__),
                   Path(data.__file__), Path(cal.__file__), *sorted(cal.DATA.glob("*.json")),
                   *sorted(Path(importlib.import_module("zavozik_ml.event_forecasters.core").__file__).parent.glob("*.py")),
                   *sorted(Path(gbm.__file__).parent.glob("*.py"))]
        metadata = dict(status="complete_internal_reference_not_independent_audit", config=config,
                        source_reference_hash=reference.file_hash(args.reference / "metadata.json"),
                        fit_options=vars(options), train_ids=meta["train_ids"], calibration_ids=meta["calibration_ids"],
                        test_ids=meta["test_ids"], native_fit_policy="GBM.fit unchanged except thread budget; internal time/company spread calibration",
                        event_fit_policy="Only fit prefixes through train_end; local inference may use each forecast's own visible history; no test/calibration labels used for new model selection",
                        names=names, marks=marks, fit_seconds=timings, skipped_evaluations=skipped,
                        event_files=event_files, diagnostics=diagnostics,
                        score_semantics="CRPS/energy are empirical sample scores. Event projection scores do not identify the full unordered event-set law. Variogram is dependence-sensitive; no invented event matching or comparable likelihood claims.",
                        limitations=["Case data lacks linked invoice due dates; hybrid models historical recurrence, not trained invoice delays.",
                                     "No transformer training/checkpoint is included.", "Aggregate models have no marked event-set scores.",
                                     "Tiny already explored synthetic unseen cohort; descriptive paired scores, not external validation."],
                        total_seconds=time.monotonic() - started,
                        peak_rss_mib=peak_rss_mib(),
                        versions=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__, lightgbm=reference.lgb.__version__),
                        sha256={str(p): reference.file_hash(p) for p in [args.flows, args.transactions, args.events, args.split, *sources]})
        (args.out / "metadata.json").write_text(json.dumps(metadata, indent=2, default=lambda value: value.item() if isinstance(value, np.generic) else value.tolist() if isinstance(value, np.ndarray) else str(value)) + "\n")
        print(summary.to_string(index=False))
        print(f"total_seconds={metadata['total_seconds']:.2f} peak_rss_mib={metadata['peak_rss_mib']:.1f}")
    finally:
        gbm.PARAMS = old_gbm_params


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--flows", type=Path, required=True)
    p.add_argument("--transactions", type=Path, required=True, help="original count-reference transaction export")
    p.add_argument("--events", type=Path, required=True, help="canonical export with pseudonymous counterparties")
    p.add_argument("--split", type=Path, default=Path("ml/eval/split_v2.json"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--models", nargs="+", default=["all"])
    p.add_argument("--safety", action="store_true", help="also fit/evaluate existing comparable aggregate baselines")
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--rounds", type=int, default=120)
    p.add_argument("--epochs", type=int, default=8)
    p.add_argument("--hidden-size", type=int, default=32)
    p.add_argument("--max-training-rows", type=int, default=100000)
    args = p.parse_args()
    if min(args.threads, args.rounds, args.epochs, args.hidden_size, args.max_training_rows) < 1:
        p.error("training budgets must be positive")
    run(args)


if __name__ == "__main__":
    main()
