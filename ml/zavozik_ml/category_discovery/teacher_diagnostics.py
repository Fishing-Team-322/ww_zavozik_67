"""Open authored diagnostic ONLY; never independent gold or calibration data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from zavozik_ml.classify_v2.model import sha256_file
from .corpus import read_rows, write_rows
from .economic_regressions import CASES
from .local_teacher import annotate
from .normalization import semantic_text
from .preparation import digest
from .semantic_pairs import SCHEMA


def create(out: Path):
    if out.exists():
        raise ValueError("diagnostic inputs already exist")
    out.mkdir(parents=True)
    rows, key = [], []
    for name, level, anchor, positive, negative in CASES:
        direction = "in" if name == "credit_subsidy" else "out"
        for expected, text in (("same", positive), ("different", negative)):
            pid = digest(name + ":" + expected)[:24]
            def side(text):
                return dict(id="authored-"+digest(text)[:16], content_key="authored-"+digest(text)[:24],
                            direction=direction, purpose=text, semantic_text=semantic_text(text))
            rows.append(dict(schema=SCHEMA, pair_id=pid, partition="train", left=side(anchor), right=side(text),
                coarse=None, fine=None, rationale="", reviewer="", reviewer_kind=""))
            key.append(dict(pair_id=pid, id=name, level=level, expected=expected))
    write_rows(out / "train_blind.jsonl", rows)
    write_rows(out / "private_expected.jsonl", key)
    (out / "manifest.json").write_text(json.dumps(dict(schema=SCHEMA,
        source="agent_authored_open_development_diagnostics", independent_test=False,
        purpose="Debug only; do not train or choose production thresholds on these expectations",
        partitions=dict(train=dict(blind_sha256=sha256_file(out / "train_blind.jsonl")))), indent=2)+"\n")


def score(inputs: Path, run: Path):
    key = {r["pair_id"]: r for r in read_rows(inputs / "private_expected.jsonl")}
    annotations = read_rows(run / "weak_pairs.jsonl")
    cases = [dict(key[r["pair_id"]], actual=r[key[r["pair_id"]]["level"]],
                  observed=r[key[r["pair_id"]]["level"]] == key[r["pair_id"]]["expected"]) for r in annotations]
    report = dict(source="agent_authored_open_development_diagnostics", independent_test=False,
        semantic_accuracy=None, expected_relation_count=sum(r["observed"] for r in cases),
        schema_valid=len(cases), total_authored_contrasts=len(key), cases=cases,
        teacher_report_sha256=sha256_file(run / "report.json"))
    target = run / "open_diagnostic_report.json"
    if target.exists():
        raise ValueError("diagnostic report already exists")
    target.write_text(json.dumps(report, indent=2)+"\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", type=Path, required=True)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if not a.inputs.exists():
        create(a.inputs)
    annotate(a.inputs, "train", a.base, a.out, len(CASES)*2)
    print(json.dumps(score(a.inputs, a.out), indent=2))


if __name__ == "__main__":
    main()
