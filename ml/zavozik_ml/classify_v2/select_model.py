"""Freeze encoder selection using completed calibration artifacts only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .model import sha256_file
from .splitting import PROTOCOL


def selection_score(calibration: dict) -> float:
    return (calibration["category"]["accuracy"] + .15 * calibration["category"]["macro_f1"]
            + .05 * calibration["channel"]["accuracy"] + .05 * calibration["tags"]["micro_f1"])


def select(candidates: list[Path]) -> dict:
    if not candidates:
        raise ValueError("no candidates")
    records = []
    calibration_signatures = set()
    train_signatures = set()
    registry_signatures = set()
    test_splits = set()
    for path in candidates:
        config = json.loads((path / "config.json").read_text())
        # This file is produced only at the successful end of training. An
        # intermediate selected checkpoint is not a completed candidate.
        calibration = json.loads((path / "calibration.json").read_text())
        if calibration.get("source") != "calibration_companies_only" or config.get("hidden_categories"):
            raise ValueError("ineligible calibration/hidden-category experiment")
        manifest = config["data_manifest"]
        if manifest.get("split_protocol") != PROTOCOL or not manifest.get("split_audit", {}).get("passed"):
            raise ValueError("candidate does not use audited template-disjoint data")
        calibration_signatures.add(manifest["calibration"]["sha256"])
        train_signatures.add(manifest["train"]["sha256"])
        registry_signatures.add(manifest["template_registry_sha256"])
        test_splits.add(tuple(manifest["test_companies"]))
        weights = path / "encoder/model.safetensors"
        records.append({"checkpoint": str(path), "base_model": config["base_source"]["model_id"],
                        "base_revision": config["base_source"]["revision"], "selected_epoch": config["selected_epoch"],
                        "calibration": calibration, "selection_score": selection_score(calibration),
                        "encoder_weights_bytes": weights.stat().st_size, "encoder_weights_sha256": sha256_file(weights),
                        "heads_sha256": sha256_file(path / "heads.npz"),
                        "config_sha256": sha256_file(path / "config.json")})
    if any(len(x) != 1 for x in (calibration_signatures, train_signatures, registry_signatures, test_splits)):
        raise ValueError("candidates must use exactly the same calibration data and company split")
    best = max(r["selection_score"] for r in records)
    tied = [r for r in records if r["selection_score"] >= best - 1e-6]
    chosen = min(tied, key=lambda r: (r["encoder_weights_bytes"], r["checkpoint"]))
    return {"selected_checkpoint": chosen["checkpoint"], "selected_base_model": chosen["base_model"],
            "policy": "max(category_accuracy + .15*category_macro_f1 + .05*channel_accuracy + .05*tag_micro_f1); ties within1e-6 prefer smaller encoder weights",
            "evaluation_scope": "Completed calibration artifacts only. Company test, novel280 and authored182 not accessed.",
            "calibration_data_sha256": next(iter(calibration_signatures)), "candidates": records}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate", type=Path, action="append", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.out.exists():
        p.error("selection lock already exists; do not replace it after final evaluation")
    report = select(args.candidate)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(report["selected_checkpoint"], flush=True)


if __name__ == "__main__":
    main()
