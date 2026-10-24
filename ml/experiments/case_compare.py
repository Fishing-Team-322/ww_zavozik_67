"""Matched case-only comparison of repository forecasters and count bootstrap.

The completed count-reference metadata fixes the split, dates and simulation
budget. Existing global models are fitted from scratch, never loaded from the
production artifacts. This experiment does not modify serving or frozen audit.
"""
from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd

import case_counts as reference
from zavozik_ml import calendar as cal
from zavozik_ml import data
from zavozik_ml.runtime_stats import peak_rss_mib
from zavozik_ml.forecasters import base, ensemble, gbm  # noqa: F401: register compared models

NAMES = ("count_bootstrap", "seasonal_naive", "gbm_global", "ensemble")


def histories_for_training(companies, ids, cutoff):
    """Order is fixed by the reference split; mask gaps only as of the cutoff."""
    by_id = {c.id: c for c in companies}
    histories = []
    for cid in ids:
        h = by_id[cid].history
        n = sum(d <= pd.Timestamp(cutoff).date() for d in h.dates)
        if n:
            histories.append(h.head(n))
    return histories


def validate_reference(args, meta):
    for key in ("flows", "transactions", "split"):
        path = getattr(args, key)
        original = meta["config"][key]
        if reference.file_hash(path) != meta["sha256"][original]:
            raise ValueError(f"{key} differs from the completed count reference")
    config = meta["config"]
    audit = json.loads(args.split.read_text())
    groups = [meta[k] for k in ("train_ids", "calibration_ids", "test_ids")]
    sets = [set(g) for g in groups]
    if any(len(g) != len(s) for g, s in zip(groups, sets)) or any(
            sets[i] & sets[j] for i in range(3) for j in range(i)):
        raise ValueError("reference company splits must be unique and disjoint")
    if set.union(*sets) & set(audit["audit_companies"]):
        raise ValueError("audit companies cannot participate")
    first_test = min(config["test_origins"])
    if not (np.datetime64(config["train_end"]) <= np.datetime64(config["calibration_origin"]) and
            np.datetime64(config["calibration_origin"]) + np.timedelta64(reference.HORIZON, "D") <= np.datetime64(first_test)):
        raise ValueError("training/calibration overlap the test forecast dates")
    for origin in (config["calibration_origin"], *config["test_origins"]):
        if np.datetime64(origin) + np.timedelta64(reference.HORIZON, "D") >= np.datetime64(audit["audit_start"]):
            raise ValueError("forecast targets must precede audit_start")
    return config


def score(c, o, flows, counts=None):
    flows = np.asarray(flows)
    if flows.ndim != 3 or flows.shape[1:] != (reference.HORIZON, 2) or not len(flows):
        raise ValueError("forecast must contain full inflow/outflow paths")
    if not np.isfinite(flows).all() or (flows < 0).any():
        raise ValueError("forecast flows must be finite and nonnegative")
    row = reference.metrics(c, o, flows, counts)
    if np.isfinite(c.balance[o]):
        actual = c.balance[o] + np.cumsum(c.flows[o + 1:o + 31, 0] - c.flows[o + 1:o + 31, 1])
        paths = c.balance[o] + np.cumsum(flows[:, :, 0] - flows[:, :, 1], axis=1)
        median = np.quantile(paths, .5, axis=0)
        row.update(business_path_abs_error=float(np.abs(actual - median).sum()),
                   business_path_actual=float(np.abs(actual).sum()))
    return row


def summarize(results):
    rows = []
    for (cohort, name), group in results.groupby(["cohort", "model"]):
        row = dict(cohort=cohort, model=name, companies=group.company_id.nunique(), origins=len(group),
                   flow_wape=group.flow_abs_error.sum() / max(group.flow_actual.sum(), 1e-9),
                   business_path_wape=group.business_path_abs_error.sum() / max(group.business_path_actual.sum(), 1e-9),
                   gap_brier=group.gap_brier.mean() if "gap_brier" in group else None,
                   forecast_seconds=group.forecast_seconds.sum())
        for key in ("net_path_mae", "net_mae_7", "net_mae_14", "net_mae_30", "net_coverage", "net_pinball", "net_width"):
            row[key] = group[key].mean()
        rows.append(row)
    summary = pd.DataFrame(rows)
    for cohort in summary.cohort.unique():
        selection = summary.cohort == cohort
        naive = summary[selection & (summary.model == "seasonal_naive")].iloc[0]
        summary.loc[selection, "net_mae_vs_naive"] = summary.loc[selection, "net_path_mae"] / naive.net_path_mae
    return summary


def assert_paired(results, names=NAMES):
    """A failed model must fail the run, not silently improve its cohort."""
    keys = ["cohort", "company_id", "origin"]
    expected = results[results.model == names[0]][keys]
    if expected.empty or not (expected.cohort == "unseen").any():
        raise ValueError("no unseen-company evaluation origins")
    expected = set(map(tuple, expected.to_numpy()))
    for name in names:
        group = results[results.model == name]
        actual = set(map(tuple, group[keys].to_numpy()))
        if actual != expected or len(actual) != len(group):
            raise ValueError(f"unpaired or duplicate evaluation origins for {name}")


def verify_count_replay(results, original):
    """The new comparison may not quietly change the earlier candidate run."""
    keys = ["cohort", "company_id", "origin"]
    old = original[original.model == "count_bootstrap"].set_index(keys).sort_index()
    new = results[results.model == "count_bootstrap"].set_index(keys).sort_index()
    if not old.index.equals(new.index):
        raise ValueError("count reference origin set changed")
    for key in ("flow_abs_error", "count_abs_error", "net_path_mae", "net_mae_7", "net_mae_14", "net_mae_30",
                "net_pinball", "net_coverage", "net_width", "gap_brier"):
        if not np.allclose(old[key], new[key], rtol=1e-10, atol=1e-7, equal_nan=True):
            raise ValueError(f"count reference scores changed: {key}")


def run(args):
    started = time.monotonic()
    meta = json.loads((args.reference / "metadata.json").read_text())
    config = validate_reference(args, meta)
    args.out.mkdir(parents=True, exist_ok=False)
    companies = reference.load(args.flows, args.transactions)
    by_id = {c.id: c for c in companies}
    train_cs = [by_id[cid] for cid in meta["train_ids"]]
    cal_cs = [by_id[cid] for cid in meta["calibration_ids"]]
    native = {c.id: c for c in data.load_companies(args.flows)}
    histories = histories_for_training(list(native.values()), meta["train_ids"], config["train_end"])
    industries = {name: i for i, name in enumerate(sorted({c.industry for c in train_cs}))}
    fit_started = time.monotonic()
    count_models, count_rows = reference.train(train_cs, config["train_end"], industries,
                                               config["rounds"], args.threads, config["seed"])
    count_fit_seconds = time.monotonic() - fit_started
    alpha = reference.dispersion(count_models, cal_cs, config["calibration_origin"], industries,
                                 as_of=min(config["test_origins"]))
    for k, direction in enumerate(reference.DIRECTIONS):
        count_models[k].save_model(str(args.out / f"count_{direction}.txt"))
    # Only the thread budget differs from the repository's fixed GBM recipe.
    original_params = gbm.PARAMS.copy()
    gbm.PARAMS = {**original_params, "num_threads": args.threads}
    model = base.get("gbm_global")
    try:
        fit_started = time.monotonic()
        model.fit(histories)
        gbm_fit_seconds = time.monotonic() - fit_started
        model.save(args.out / "gbm_global")
        native_rows = sum(len(gbm._train_origins(h)) * reference.HORIZON for h in histories)
        rows, skipped = [], []
        for cohort, ids in (("unseen", meta["test_ids"]), ("seen_future", meta["train_ids"])):
            for cid in ids:
                c = by_id[cid]
                for origin in config["test_origins"]:
                    o = c.origin(origin)
                    if not reference.evaluable(c, o):
                        skipped.append(dict(cohort=cohort, company_id=cid, origin=origin))
                        continue
                    history = native[cid].history.head(o + 1)
                    if not np.array_equal(np.asarray(history.dates, dtype="datetime64[D]"), c.dates[:o + 1]) or not np.array_equal(~history.missing, c.known(o)):
                        raise ValueError("model histories disagree about dates or missing-data availability")
                    for name in NAMES:
                        forecast_started = time.monotonic()
                        selected = None if name == "count_bootstrap" else base.select_model(name, history)
                        used = name if selected is None else selected.name
                        seed = int(reference.hashlib.sha256(f"{config['seed']}:{cid}:{origin}:{used}".encode()).hexdigest()[:16], 16)
                        rng = np.random.default_rng(seed)
                        counts = None
                        if selected is None:
                            mu = reference.expected(count_models, c, o, industries)
                            flows, counts = reference.simulate(c, o, config["paths"], rng, mu, alpha)
                            low_confidence = None
                        else:
                            paths = selected.forecast(history, reference.HORIZON, config["paths"], rng)
                            flows = np.stack([paths.inflow, paths.outflow], axis=-1)
                            low_confidence = paths.low_confidence
                        elapsed = time.monotonic() - forecast_started
                        rows.append(dict(cohort=cohort, company_id=cid, origin=origin, model=name,
                                         model_used=used, low_confidence=low_confidence,
                                         forecast_seconds=elapsed, **score(c, o, flows, counts)))
        results = pd.DataFrame(rows)
        assert_paired(results)
        verify_count_replay(results, pd.read_csv(args.reference / "origins.csv"))
        results.to_csv(args.out / "origins.csv", index=False)
        summary = summarize(results)
        summary.to_csv(args.out / "summary.csv", index=False)
        source_files = [Path(__file__), Path(reference.__file__), Path(data.__file__), Path(cal.__file__),
                        *sorted(Path(gbm.__file__).parent.glob("*.py")), *sorted(cal.DATA.glob("*.json"))]
        metadata = dict(status="complete_internal_matched_reference_not_independent_audit",
                        reference_metadata_sha256=reference.file_hash(args.reference / "metadata.json"),
                        config=config, train_ids=meta["train_ids"], calibration_ids=meta["calibration_ids"],
                        test_ids=meta["test_ids"], model_names=NAMES, paths=config["paths"], threads=args.threads,
                        count_fit_seconds=count_fit_seconds, gbm_fit_seconds=gbm_fit_seconds,
                        count_training_rows=count_rows, gbm_final_training_rows=native_rows,
                        gbm_params=gbm.PARAMS, gbm_rounds=gbm.NUM_ROUNDS, gbm_spread=model.spread,
                        gbm_calibration=model.calibration, skipped_evaluations=skipped, count_replay_verified=True,
                        calibration_policy="GBM.fit retains built-in 60-day/internal-company spread calibration, then refits only train IDs through train_end. Count dispersion uses separate calibration IDs through first test origin. No test IDs or future test labels enter fitting/calibration.",
                        limitations=["Only shared cash-flow metrics are compared; count scores are retained solely for replay verification.",
                                     "GBM and count recipes use different calibration mechanisms and information dates.",
                                     "Paired scores are descriptive: only 9 unseen companies with 18 eligible origins.",
                                     "All companies were explored previously; this is not a fresh audit."],
                        total_seconds=time.monotonic() - started,
                        peak_rss_mib=peak_rss_mib(),
                        versions=dict(python=platform.python_version(), lightgbm=reference.lgb.__version__,
                                      numpy=np.__version__, pandas=pd.__version__),
                        sha256={str(p): reference.file_hash(p) for p in [args.flows, args.transactions, args.split, *source_files]})
        (args.out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(summary.to_string(index=False))
        print(f"count_fit_seconds={count_fit_seconds:.2f} gbm_fit_seconds={gbm_fit_seconds:.2f} total_seconds={metadata['total_seconds']:.2f} peak_rss_mib={metadata['peak_rss_mib']:.1f}")
    finally:
        gbm.PARAMS = original_params


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", type=Path, required=True, help="completed case_counts output directory")
    p.add_argument("--flows", type=Path, required=True)
    p.add_argument("--transactions", type=Path, required=True)
    p.add_argument("--split", type=Path, default=Path("ml/eval/split_v2.json"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--threads", type=int, default=8)
    args = p.parse_args()
    if args.threads < 1:
        p.error("threads must be positive")
    run(args)


if __name__ == "__main__":
    main()
