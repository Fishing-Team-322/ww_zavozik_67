"""Case-only reference: direct LightGBM counts + historical transaction amounts.

Research only; does not register/replace a serving model. Inputs come from the
canonical Go exporter, including its deduplication, business scope and missing
history detection. No counterparty identities or payment text are required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import time
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from zavozik_ml import calendar as cal

DIRECTIONS = ("in", "out")
HORIZON = 30


@dataclass
class Company:
    id: str
    industry: str
    dates: np.ndarray
    flows: np.ndarray  # day, direction
    counts: np.ndarray
    missing: np.ndarray
    detected: np.ndarray
    balance: np.ndarray
    internal: np.ndarray
    events: pd.DataFrame

    def origin(self, date: str) -> int | None:
        i = int(np.searchsorted(self.dates, np.datetime64(date)))
        return i if i < len(self.dates) and self.dates[i] == np.datetime64(date) else None

    def known(self, o: int) -> np.ndarray:
        # A gap discovered after this cutoff must not leak into its features.
        return ~(self.missing[:o + 1] & (self.detected[:o + 1] <= self.dates[o]))


def load(flows_path: Path, events_path: Path) -> list[Company]:
    frame = pd.read_csv(flows_path, parse_dates=["date", "missing_known_on"])
    events = pd.read_csv(events_path, parse_dates=["date"], dtype={"company_id": str})
    if not set(events.direction).issubset(DIRECTIONS):
        raise ValueError("unknown transaction direction")
    if not np.isfinite(events.amount).all() or (events.amount < 0).any():
        raise ValueError("transaction amounts must be finite and nonnegative")
    result = []
    for cid, rows in frame.groupby("company_id", sort=True):
        rows = rows.sort_values("date").reset_index(drop=True)
        dates = rows.date.to_numpy(dtype="datetime64[D]")
        if len(dates) > 1 and not (np.diff(dates) == np.timedelta64(1, "D")).all():
            raise ValueError("daily history must be unique and continuous")
        ev = events[events.company_id == cid].copy()
        counts = np.zeros((len(rows), 2), dtype=np.float64)
        for k, direction in enumerate(DIRECTIONS):
            part = ev[ev.direction == direction]
            counts[:, k] = part.groupby("date").size().reindex(rows.date, fill_value=0).to_numpy()
            totals = part.groupby("date").amount.sum().reindex(rows.date, fill_value=0).to_numpy()
            if not np.allclose(totals, rows[("inflow", "outflow")[k]], atol=.02, rtol=1e-10):
                raise ValueError("transaction export does not reconcile with daily business flows")
        missing = rows.missing.to_numpy(dtype=bool)
        detected = rows.missing_known_on.to_numpy(dtype="datetime64[D]")
        if np.isnat(detected[missing]).any():
            raise ValueError("missing days require discovery dates")
        internal = sum((rows.get("cat_" + cat, pd.Series(0., index=rows.index)).to_numpy()
                        for cat in ("own_transfer", "owner_loan")))
        result.append(Company(str(cid), str(rows.industry.iloc[0]), dates,
                              rows[["inflow", "outflow"]].to_numpy(), counts,
                              missing, detected, rows.balance.to_numpy(), internal, ev))
    if not result:
        raise ValueError("empty input")
    return result


def features(c: Company, o: int, industries: dict[str, int], horizon: int = HORIZON):
    """Use only the prefix ending at o; direct forecasts need no recursive facts."""
    if o < 0 or o >= len(c.dates):
        raise ValueError("invalid origin")
    h = np.arange(1, horizon + 1)
    target = c.dates[o] + h.astype("timedelta64[D]")
    td = pd.DatetimeIndex(target)
    known = c.known(o)
    counts = np.where(known[:, None], c.counts[:o + 1], np.nan)
    gross = np.where(known[:, None], c.flows[:o + 1], np.nan)
    recent = counts[max(0, o - 90):]
    if not np.isfinite(recent).any():
        raise ValueError("no observed recent history")
    scales = np.maximum(np.nanmean(recent, axis=0), .25)
    f = {"horizon": h, "weekday": td.dayofweek, "day": td.day,
         "month": td.month, "days_to_eom": td.days_in_month - td.day,
         "industry": np.full(horizon, industries.get(c.industry, -1)),
         "history_days": np.full(horizon, o + 1),
         "known_share": np.full(horizon, known[max(0, o - 90):].mean())}
    f.update(cal.features(target, c.dates[o]))
    hist_work = cal.is_workday(c.dates[:o + 1])
    calendar_only = not ((c.flows[:o + 1].sum(axis=1) > 0) & known & ~hist_work).any()
    eligible = known & (hist_work if calendar_only else True)
    mask = cal.is_workday(target) if calendar_only else np.ones(horizon, dtype=bool)
    wd = pd.DatetimeIndex(c.dates[:o + 1]).dayofweek.to_numpy()
    for k, direction in enumerate(DIRECTIONS):
        f[direction + "_log_scale"] = np.full(horizon, np.log1p(scales[k]))
        for window in (7, 28, 91):
            part = counts[max(0, o + 1 - window):, k]
            mean = np.nanmean(part) if np.isfinite(part).any() else np.nan
            f[f"{direction}_mean_{window}"] = np.full(horizon, mean / scales[k])
        mean_amount = np.nanmean(gross[max(0, o - 90):, k])
        f[direction + "_log_flow"] = np.full(horizon, np.log1p(mean_amount))
        vals = []
        for day in td.dayofweek:
            pool = np.flatnonzero(eligible & (wd == day) & (np.arange(o + 1) >= o - 55))
            if not len(pool):
                pool = np.flatnonzero(eligible & (np.arange(o + 1) >= o - 55))
            vals.append(counts[pool, k].mean() / scales[k] if len(pool) else np.nan)
        f[direction + "_weekday_mean"] = vals
    return pd.DataFrame(f, dtype=np.float32), scales, mask


def partition(companies: list[Company], excluded: set[str], limit: int, seed: int):
    available = [c for c in companies if c.id not in excluded]
    available.sort(key=lambda c: hashlib.sha256(f"{seed}:{c.id}".encode()).hexdigest())
    available = available[:limit]
    if len(available) < 15:
        raise ValueError("need at least 15 development companies")
    n = max(3, len(available) // 5)
    return available[2*n:], available[:n], available[n:2*n]


def train(companies, cutoff, industries, rounds, threads, seed):
    xs, ys = [], []
    for c in companies:
        end = int(np.searchsorted(c.dates, np.datetime64(cutoff), side="right"))
        for o in range(83, end - HORIZON, 14):
            try:
                x, scale, _ = features(c, o, industries)
            except ValueError:
                continue
            target = c.counts[o + 1:o + 1 + HORIZON] / scale
            valid = c.known(end - 1)[o + 1:o + 1 + HORIZON]
            if valid.any():
                xs.append(x.loc[valid])
                ys.append(target[valid])
    if not xs:
        raise ValueError("no training windows")
    x, y = pd.concat(xs, ignore_index=True), np.concatenate(ys)
    models = []
    for k in range(2):
        if y[:, k].sum() == 0:
            raise ValueError("training requires both flow directions")
        model = lgb.train(
            dict(objective="poisson", learning_rate=.04, num_leaves=15,
                 min_data_in_leaf=150, lambda_l2=10, feature_fraction=.8,
                 num_threads=threads, seed=seed, verbosity=-1),
            lgb.Dataset(x, label=y[:, k], categorical_feature=["industry"]),
            num_boost_round=rounds,
        )
        models.append(model)
    return models, len(x)


def expected(models, c, o, industries):
    x, scale, mask = features(c, o, industries)
    mu = np.column_stack([m.predict(x) * scale[k] for k, m in enumerate(models)])
    return np.maximum(mu, 0) * mask[:, None]


def evaluable(c: Company, o: int | None, as_of: str | None = None) -> bool:
    if o is None or o + HORIZON >= len(c.dates):
        return False
    missing = c.missing[o + 1:o + 1 + HORIZON]
    if as_of is not None:
        cutoff = np.datetime64(as_of)
        if c.dates[o + HORIZON] > cutoff:
            raise ValueError("calibration horizon must finish by its as-of cutoff")
        missing = missing & (c.detected[o + 1:o + 1 + HORIZON] <= cutoff)
    return not missing.any()


def dispersion(models, companies, origin, industries, as_of):
    numerator, denominator = np.zeros(2), np.zeros(2)
    for c in companies:
        o = c.origin(origin)
        if not evaluable(c, o, as_of=as_of):
            continue
        mu = expected(models, c, o, industries)
        actual = c.counts[o + 1:o + 1 + HORIZON]
        numerator += ((actual - mu)**2 - mu).sum(axis=0)
        denominator += (mu**2).sum(axis=0)
    if not denominator.any():
        raise ValueError("no calibration observations")
    return np.clip(numerator / np.maximum(denominator, 1e-9), 0, 5)


def simulate(c, o, npaths, rng, mu=None, alpha=None):
    """Naive samples observed daily pairs; candidate samples individual amounts.

    A shared weekly gamma factor gives overdispersed, dependent counts. Its
    dispersion is estimated only on calibration companies/dates. Amounts are
    sampled from actual historical operations, not daily means.
    """
    _, _, mask = features(c, o, {})
    known = c.known(o)
    hist_work = cal.is_workday(c.dates[:o + 1])
    calendar_only = not ((c.flows[:o + 1].sum(axis=1) > 0) & known & ~hist_work).any()
    eligible = known & (hist_work if calendar_only else True)
    eligible[:max(0, o - 55)] = False
    any_pool = np.flatnonzero(eligible)
    if not len(any_pool):
        raise ValueError("no eligible days for seasonal baseline")
    wd = pd.DatetimeIndex(c.dates[:o + 1]).dayofweek.to_numpy()
    target_wd = pd.DatetimeIndex(c.dates[o] + np.arange(1, HORIZON + 1).astype("timedelta64[D]")).dayofweek
    flows, counts = np.zeros((npaths, HORIZON, 2)), np.zeros((npaths, HORIZON, 2))
    if mu is None:
        for d, day in enumerate(target_wd):
            if mask[d]:
                pool = np.flatnonzero(eligible & (wd == day))
                idx = rng.choice(pool if len(pool) else any_pool, npaths)
                flows[:, d] = c.flows[idx]
                counts[:, d] = c.counts[idx]
        return flows, counts
    ev = c.events
    start = c.dates[max(0, o - 90)]
    valid_dates = c.dates[:o + 1][known]
    ev = ev[(ev.date >= pd.Timestamp(start)) & (ev.date <= pd.Timestamp(c.dates[o])) & ev.date.isin(valid_dates)]
    for k, direction in enumerate(DIRECTIONS):
        amounts = ev.loc[ev.direction == direction, "amount"].to_numpy()
        if not len(amounts):
            continue  # no historical amount evidence: explicit cold-direction zero
        for block in range(0, HORIZON, 7):
            a = float(alpha[k])
            factor = rng.gamma(1/a, a, npaths) if a > 1e-8 else np.ones(npaths)
            for d in range(block, min(block + 7, HORIZON)):
                ns = rng.poisson(mu[d, k] * factor)
                total = int(ns.sum())
                if total > 2_000_000:
                    raise ValueError("simulation batch too large; reduce paths")
                counts[:, d, k] = ns
                if total:
                    flows[:, d, k] = np.bincount(np.repeat(np.arange(npaths), ns),
                                                weights=rng.choice(amounts, total), minlength=npaths)
    return flows, counts


def metrics(c, o, flows, counts=None):
    actual = c.flows[o + 1:o + 1 + HORIZON]
    pred = flows.mean(axis=0)
    net = np.cumsum(flows[:, :, 0] - flows[:, :, 1], axis=1)
    actual_net = np.cumsum(actual[:, 0] - actual[:, 1])
    q = np.quantile(net, [.1, .5, .9], axis=0)
    loss = []
    for i, quantile in enumerate((.1, .5, .9)):
        error = actual_net - q[i]
        loss.append(np.maximum(quantile * error, (quantile - 1) * error).mean())
    row = {"flow_abs_error": float(np.abs(actual - pred).sum()),
           "flow_actual": float(actual.sum()),
           "net_path_mae": float(np.abs(actual_net - q[1]).mean()),
           "net_coverage": float(((actual_net >= q[0]) & (actual_net <= q[2])).mean()),
           "net_pinball": float(np.mean(loss)),
           "net_width": float((q[2] - q[0]).mean())}
    if counts is not None:
        actual_counts = c.counts[o + 1:o + 1 + HORIZON]
        row.update(count_abs_error=float(np.abs(actual_counts - counts.mean(axis=0)).sum()),
                   count_actual=float(actual_counts.sum()))
    for h in (7, 14, 30):
        row[f"net_mae_{h}"] = float(abs(actual_net[h - 1] - q[1, h - 1]))
    # Evaluate business balances only where observed account balances reconcile.
    bal = c.balance[o:o + HORIZON + 1]
    if np.isfinite(bal).all():
        adjusted = bal[1:] - np.cumsum(c.internal[o + 1:o + HORIZON + 1])
        if not np.allclose(adjusted, bal[0] + actual_net, atol=.05, rtol=1e-10):
            raise ValueError("business balance reconciliation failed")
        p = float(((bal[0] + net).min(axis=1) < 0).mean())
        truth = bool((adjusted < 0).any())
        row.update(gap_probability=p, gap_actual=truth, gap_brier=(p - truth)**2)
    return row


def run(args):
    started = time.monotonic()
    out = args.out
    out.mkdir(parents=True, exist_ok=False)
    split = json.loads(args.split.read_text())
    # This development experiment must never consume the frozen audit dates.
    audit_start = np.datetime64(split["audit_start"])
    for origin in (args.calibration_origin, *args.test_origins):
        if np.datetime64(origin) + np.timedelta64(HORIZON, "D") >= audit_start:
            raise ValueError("all evaluation targets must precede audit_start")
    if not (args.train_end <= args.calibration_origin and
            np.datetime64(args.calibration_origin) + np.timedelta64(HORIZON, "D") <= np.datetime64(min(args.test_origins))):
        raise ValueError("training/calibration must finish before test forecasts")
    companies = load(args.flows, args.transactions)
    train_cs, cal_cs, test_cs = partition(companies, set(split["audit_companies"]), args.companies, args.seed)
    industries = {name: i for i, name in enumerate(sorted({c.industry for c in train_cs}))}
    fit_started = time.monotonic()
    models, nrows = train(train_cs, args.train_end, industries, args.rounds, args.threads, args.seed)
    fit_seconds = time.monotonic() - fit_started
    alpha = dispersion(models, cal_cs, args.calibration_origin, industries,
                       as_of=min(args.test_origins))
    for k, direction in enumerate(DIRECTIONS):
        models[k].save_model(str(out / f"count_{direction}.txt"))
    rows, skipped = [], []
    for cohort, cs in (("unseen", test_cs), ("seen_future", train_cs)):
        for c in cs:
            for origin in args.test_origins:
                o = c.origin(origin)
                if not evaluable(c, o):
                    skipped.append({"company_id": c.id, "origin": origin, "cohort": cohort,
                                    "reason": "incomplete_horizon" if o is None or o + HORIZON >= len(c.dates) else "missing_future"})
                    continue
                mu = expected(models, c, o, industries)
                for name in ("seasonal_naive", "count_bootstrap"):
                    seed = int(hashlib.sha256(f"{args.seed}:{c.id}:{origin}:{name}".encode()).hexdigest()[:16], 16)
                    flows, counts = simulate(c, o, args.paths, np.random.default_rng(seed),
                                             mu if name == "count_bootstrap" else None, alpha)
                    rows.append({"company_id": c.id, "origin": origin, "cohort": cohort,
                                 "model": name, **metrics(c, o, flows, counts)})
    results = pd.DataFrame(rows)
    if results.empty or not (results.cohort == "unseen").any():
        raise ValueError("no evaluable unseen-company forecasts")
    results.to_csv(out / "origins.csv", index=False)
    summary = []
    for (cohort, model), group in results.groupby(["cohort", "model"]):
        summary.append({"cohort": cohort, "model": model, "origins": len(group),
                        "flow_wape": group.flow_abs_error.sum() / max(group.flow_actual.sum(), 1e-9),
                        "count_wape": group.count_abs_error.sum() / max(group.count_actual.sum(), 1e-9),
                        **{key: group[key].mean() for key in ("net_path_mae", "net_mae_7", "net_mae_14", "net_mae_30", "net_coverage", "net_pinball", "net_width")},
                        "gap_brier": group.gap_brier.mean() if "gap_brier" in group else None})
    pd.DataFrame(summary).to_csv(out / "summary.csv", index=False)
    metadata = {"status": "internal_development_reference_not_independent_audit",
                "scope": "business_without_internal_transfers", "reserve": 0,
                "limitations": ["No explicit recurring component yet; it remains in the baseline stream.",
                                "Independent historical amount sampling; not a learned amount or counterparty model.",
                                "Weekly count dependence is a modelling assumption, not validated causality.",
                                "Business-balance gap excludes future owner financing; not actual account-gap truth."],
                "config": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                "feature_names": models[0].feature_name(), "skipped_evaluations": skipped,
                "train_ids": [c.id for c in train_cs], "calibration_ids": [c.id for c in cal_cs],
                "test_ids": [c.id for c in test_cs], "industries": industries, "dispersion": alpha.tolist(),
                "training_rows": nrows, "fit_seconds": fit_seconds, "total_seconds": time.monotonic() - started,
                "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                "versions": {"python": platform.python_version(), "lightgbm": lgb.__version__, "numpy": np.__version__, "pandas": pd.__version__},
                "sha256": {str(p): file_hash(p)
                           for p in (args.flows, args.transactions, args.split, Path(__file__), Path(cal.__file__),
                                     *sorted(cal.DATA.glob("*.json")))}}
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(pd.DataFrame(summary).to_string(index=False))
    print(f"training_rows={nrows} fit_seconds={fit_seconds:.2f} total_seconds={metadata['total_seconds']:.2f} peak_rss_mib={metadata['peak_rss_mib']:.1f}")


def file_hash(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--flows", type=Path, required=True)
    p.add_argument("--transactions", type=Path, required=True)
    p.add_argument("--split", type=Path, default=Path("ml/eval/split_v2.json"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--companies", type=int, default=60)
    p.add_argument("--rounds", type=int, default=250)
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--paths", type=int, default=300)
    p.add_argument("--seed", type=int, default=20261024)
    p.add_argument("--train-end", default="2026-03-31")
    p.add_argument("--calibration-origin", default="2026-03-31")
    p.add_argument("--test-origins", nargs="+", default=["2026-04-30", "2026-05-30"])
    args = p.parse_args()
    if min(args.paths, args.rounds, args.threads) < 1:
        p.error("paths, rounds and threads must be positive")
    run(args)


if __name__ == "__main__":
    main()
