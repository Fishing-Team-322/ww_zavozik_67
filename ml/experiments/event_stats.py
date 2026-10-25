"""Paired company-bootstrap comparisons and gap-probability calibration.

Reads a benchmark origins.csv (one row per cohort/company/origin/model) and answers
the two questions the event benchmark could not: is a model-vs-model difference
stable across companies, and does the gap probability beat a constant base rate?

Usage:
    python -m event_stats --origins ml/data/event_adjust_v1/origins.csv \
        --cohort unseen --model blocks --against ensemble --against gbm_global
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

BINS = np.array([0.0, 0.2, 0.4, 0.6, 0.8, 1.0001])


def _cohort(frame, cohort, metric):
    subset = frame[(frame.cohort == cohort) & frame[metric].notna()]
    if subset.empty:
        raise ValueError(f"no rows for cohort {cohort!r}")
    return subset


def paired_ratio(frame, cohort, metric, model, against, repeats=10_000, seed=7):
    """Bootstrap the ratio of company-mean errors by resampling companies."""
    data = _cohort(frame, cohort, metric)
    wide = data.pivot_table(index=["company_id", "origin"], columns="model", values=metric)
    if model not in wide or against not in wide:
        raise ValueError(f"missing model in cohort: {model!r} or {against!r}")
    wide = wide[[model, against]].dropna()
    if wide.empty:
        raise ValueError("no shared origins between the two models")
    companies = wide.index.get_level_values(0).unique().to_numpy()
    means = wide.groupby(level=0).mean()
    observed = float(means[model].sum() / means[against].sum())
    rng = np.random.default_rng(seed)
    draws = np.empty(repeats)
    for i in range(repeats):
        pick = rng.choice(companies, size=len(companies), replace=True)
        sample = means.loc[pick]
        draws[i] = sample[model].sum() / sample[against].sum()
    low, high = np.quantile(draws, [0.025, 0.975])
    per_origin = (wide[model] < wide[against]).mean()
    return dict(cohort=cohort, metric=metric, model=model, against=against,
                ratio=observed, ci_low=float(low), ci_high=float(high),
                p_better=float((draws < 1).mean()), companies=len(companies),
                origins=len(wide), origin_win_rate=float(per_origin))


def gap_calibration(frame, cohort, model):
    """Reliability of the 30-day gap probability against a constant base rate."""
    data = _cohort(frame, cohort, "gap_probability")
    data = data[(data.model == model) & data.gap_actual.notna()]
    if data.empty:
        raise ValueError(f"no scored gaps for {model!r} in {cohort!r}")
    probability = data.gap_probability.to_numpy(float)
    actual = data.gap_actual.astype(bool).to_numpy()
    base = float(actual.mean())
    brier = float(np.mean((probability - actual) ** 2))
    reference = float(np.mean((base - actual) ** 2))
    bins = np.clip(np.digitize(probability, BINS) - 1, 0, len(BINS) - 2)
    reliability, counts, weighted = [], [], 0.0
    for index in range(len(BINS) - 1):
        mask = bins == index
        if not mask.any():
            continue
        predicted, observed = float(probability[mask].mean()), float(actual[mask].mean())
        reliability.append(dict(low=float(BINS[index]), high=float(BINS[index + 1]),
                                n=int(mask.sum()), predicted=predicted, observed=observed))
        weighted += mask.sum() * abs(predicted - observed)
    return dict(cohort=cohort, model=model, origins=len(data), events=int(actual.sum()),
                base_rate=base, brier=brier, base_brier=reference,
                brier_skill=1 - brier / reference if reference else None,
                mean_probability=float(probability.mean()),
                ece=weighted / len(data), reliability=reliability)


def select_rows(frame: pd.DataFrame, out_of_fit: bool) -> pd.DataFrame:
    """Optionally keep only rows whose target window ends after the fit cutoff."""
    if not out_of_fit:
        return frame
    if "in_fit" not in frame:
        raise ValueError("origins file has no in_fit column; cannot select out-of-fit rows")
    selected = frame[~frame.in_fit.astype(bool)]
    if selected.empty:
        raise ValueError("no out-of-fit rows in this file")
    return selected


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--origins", type=Path, required=True)
    p.add_argument("--cohort", default="unseen")
    p.add_argument("--metric", default="net_path_mae")
    p.add_argument("--repeats", type=int, default=10_000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out-of-fit", action="store_true",
                   help="keep only rows whose 30-day window ends after train_end (requires in_fit column)")
    p.add_argument("--model", nargs="+", default=["blocks", "hybrid", "mixture"])
    p.add_argument("--against", nargs="+", default=["ensemble", "gbm_global", "seasonal_naive"])
    p.add_argument("--gap", nargs="*", default=None, help="models for gap calibration; default all")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    frame = select_rows(pd.read_csv(args.origins), args.out_of_fit)
    rows = []
    for model in args.model:
        for against in args.against:
            if model == against:
                continue
            try:
                rows.append(paired_ratio(frame, args.cohort, args.metric, model, against,
                                         repeats=args.repeats, seed=args.seed))
            except ValueError as error:
                rows.append(dict(model=model, against=against, error=str(error)))
    models = args.gap if args.gap is not None else sorted(frame.model.unique())
    gaps = []
    for model in models:
        try:
            gaps.append(gap_calibration(frame, args.cohort, model))
        except ValueError as error:
            gaps.append(dict(model=model, error=str(error)))
    result = dict(comparisons=rows, gap=gaps)
    text = json.dumps(result, indent=2, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
