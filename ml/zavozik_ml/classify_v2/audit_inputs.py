"""Input-only fixture/train overlap audit; no predictions or model selection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .data import ML_DIR, read_rows, operation
from .evaluate import authored_rows
from .model import sha256_file
from .text import encoder_text, normalize


def audit(train: Path, fixture: Path) -> dict:
    training = read_rows(train)
    rows, manifest = authored_rows(fixture)
    texts = {r["text"] for r in training}
    purposes = {normalize(r.get("purpose", "")) for r in training}
    overlaps = [r["id"] for r in rows if encoder_text(operation(r)) in texts]
    return {"frozen_fixture_sha256": manifest["sha256"], "train_sha256": sha256_file(train),
            "authored_rows": len(rows), "exact_normalized_input_overlap": len(overlaps),
            "exact_overlap_ids": overlaps, "no_exact_input_overlap": len(rows) - len(overlaps),
            "normalized_purpose_overlap": sum(normalize(r["purpose"]) in purposes for r in rows),
            "scope": "Input-only audit before final predictions; no fixture edits or model selection; empty/garbage inputs can overlap by construction"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--train", type=Path, required=True)
    p.add_argument("--fixture", type=Path, default=Path(__file__).with_name("heldout_v1.tsv"))
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = audit(args.train, args.fixture)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
