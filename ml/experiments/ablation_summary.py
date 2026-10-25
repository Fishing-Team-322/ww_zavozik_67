"""Summarise an A/B ablation run into a tracked table.

Reads two origins.csv files produced by `option_eval` (same protocol, same seeds,
one before and one after a model change) and writes a table with each variant's
metrics, its ratio to its own baseline, and a company-bootstrap interval.

Usage:
    python -m ablation_summary --baseline .../baseline_origins.csv \
        --variant .../variant_origins.csv --out ml/benchmarks/ablation_level_phase.csv
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

import event_stats as stats

METRICS = ("net_path_mae", "net_mae_7", "net_mae_14", "net_mae_30", "net_pinball",
           "net_coverage", "net_width", "gap_brier")


def load(path: Path, suffix: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"cohort", "model", "company_id", "origin", *METRICS}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    frame = frame.copy()
    frame["model"] = frame.model.astype(str) + suffix
    return frame


def summarise(baseline: pd.DataFrame, variant: pd.DataFrame, repeats: int = 5000) -> pd.DataFrame:
    models = sorted(set(baseline.model.str.replace("_baseline", "", regex=False)))
    combined = pd.concat([baseline, variant], ignore_index=True)
    rows = []
    for model in models:
        base_col, var_col = f"{model}_baseline", f"{model}_variant"
        for metric in ("net_path_mae", "net_mae_7", "net_mae_14", "net_mae_30", "net_pinball"):
            result = stats.paired_ratio(combined, "unseen", metric, var_col, base_col, repeats=repeats)
            rows.append(dict(model=model, metric=metric, baseline=float(baseline[baseline.model == base_col][metric].mean()),
                             variant=float(variant[variant.model == var_col][metric].mean()),
                             ratio=result["ratio"], ci_low=result["ci_low"], ci_high=result["ci_high"],
                             p_better=result["p_better"], origin_win_rate=result["origin_win_rate"],
                             companies=result["companies"], rows=result["origins"]))
        for metric in ("net_coverage", "gap_brier"):
            rows.append(dict(model=model, metric=metric,
                             baseline=float(baseline[baseline.model == base_col][metric].mean()),
                             variant=float(variant[variant.model == var_col][metric].mean()),
                             ratio=None, ci_low=None, ci_high=None, p_better=None,
                             origin_win_rate=None, companies=int(baseline[baseline.model == base_col].company_id.nunique()),
                             rows=int(len(baseline[baseline.model == base_col]))))
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--variant", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--repeats", type=int, default=5000)
    args = p.parse_args()
    table = summarise(load(args.baseline, "_baseline"), load(args.variant, "_variant"), args.repeats)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False)
    provenance = args.out.with_suffix(".provenance.json")
    provenance.write_text(json.dumps(dict(
        baseline=str(args.baseline), variant=str(args.variant),
        baseline_sha256=hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
        variant_sha256=hashlib.sha256(args.variant.read_bytes()).hexdigest(),
        repeats=args.repeats, bootstrap="companies, resampled with replacement",
        python=platform.python_version(), pandas=pd.__version__, numpy=np.__version__,
        note="Protocol D: 9 unseen companies, 27 out-of-fit company-origins (2026-03-31/04-30/05-31), "
             "300 paths, seeds 20261024/25/26. ratio < 1 means the variant has lower error."), indent=2) + "\n")
    print(table.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))


if __name__ == "__main__":
    main()
