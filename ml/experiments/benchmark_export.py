"""Assemble completed benchmark runs into committed, machine-readable artifacts.

Reads finished experiment output directories (each with `summary.csv` and
`metadata.json`) and writes normalised CSVs plus one provenance file under
`ml/benchmarks/`. Values are copied, never recomputed, so the committed table can
always be traced back to the run that produced it.

Usage:
    python -m benchmark_export --spec ml/benchmarks/runs.json --out ml/benchmarks
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd

BENCHMARKS = Path(__file__).resolve().parents[1] / "benchmarks"
METRICS = ("net_mae_vs_naive", "net_path_mae", "flow_wape", "business_path_wape", "net_coverage",
           "net_width", "net_pinball", "gap_brier", "gap_precision_0.5", "gap_recall_0.5",
           "gap_f1_0.5", "gap_accuracy_0.5", "flow_mse", "net_mse", "count_crps",
           "marked_count_crps", "amount_bin_count_crps", "occurrences")
KEEP = ("benchmark", "cohort", "model", "origins", "companies") + METRICS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def normalise(name: str, summary: pd.DataFrame) -> pd.DataFrame:
    missing = {"cohort", "model"} - set(summary.columns)
    if missing:
        raise ValueError(f"{name}: summary lacks columns {sorted(missing)}")
    frame = summary.copy()
    frame.insert(0, "benchmark", name)
    if "occurrences" not in frame:
        for column in ("origins", "companies"):
            if column in frame:
                frame = frame.rename(columns={column: column})
        frame["occurrences"] = frame.get("origins")
    for column in KEEP:
        if column not in frame:
            frame[column] = None
    frame = frame[list(KEEP)]
    return frame.sort_values(["cohort", "benchmark", "model"], kind="stable").reset_index(drop=True)


def export(spec_path: Path, out: Path) -> dict:
    """Build the committed artifacts; return the provenance record."""
    spec = json.loads(spec_path.read_text())
    runs = spec["runs"]
    if not runs:
        raise ValueError("no runs in spec")
    frames, provenance = [], []
    for run in runs:
        directory = Path(run["dir"])
        summary_path, meta_path = directory / run.get("summary", "summary.csv"), directory / "metadata.json"
        if not summary_path.exists():
            raise ValueError(f"missing summary: {summary_path}")
        summary = pd.read_csv(summary_path)
        if run.get("cohorts") and "cohort" in summary:
            summary = summary[summary.cohort.isin(run["cohorts"])]
        if summary.empty:
            raise ValueError(f"{run['name']}: no rows after cohort filter")
        frames.append(normalise(run["name"], summary))
        entry = dict(name=run["name"], dir=str(directory), summary_sha256=_sha256(summary_path),
                     note=run.get("note", ""))
        if meta_path.exists():
            entry["metadata_sha256"] = _sha256(meta_path)
            meta = json.loads(meta_path.read_text())
            entry["run_status"] = meta.get("status")
        provenance.append(entry)
    combined = pd.concat(frames, ignore_index=True)
    out.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out / "model_benchmarks.csv", index=False)
    record = dict(generated_from=spec_path.name, git_head=_git_head(),
                  spec_sha256=_sha256(spec_path), runs=provenance,
                  rows=int(len(combined)),
                  note="Values are copied from completed runs; see each run's metadata.json for config, "
                       "split and hashes. Cohorts differ between benchmarks and must not be pooled.")
    (out / "provenance.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--spec", type=Path, default=BENCHMARKS / "runs.json")
    p.add_argument("--out", type=Path, default=BENCHMARKS)
    args = p.parse_args()
    record = export(args.spec, args.out)
    print(f"rows={record['rows']} runs={len(record['runs'])} out={args.out}")


if __name__ == "__main__":
    main()
