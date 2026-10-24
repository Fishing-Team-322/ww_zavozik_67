"""Local blind pair review. Never fabricate human gold from model clusters.

Judgments: same / different / uncertain. A semantic category means the same
economic purpose, not merely the same payment channel, counterparty or wording.
The balanced audit sample is not a population accuracy estimate.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
from pathlib import Path
import random

from zavozik_ml.classify_v2.model import sha256_file
from .corpus import read_rows, write_rows


def create(rows, assignments, out: Path, per_stratum=40, seed=42):
    if out.exists():
        raise ValueError("review output exists")
    if len(rows) != len(assignments):
        raise ValueError("row/prediction count mismatch")
    strata = defaultdict(list)
    for i, j in itertools.combinations(range(len(rows)), 2):
        if rows[i]["template_family"] == rows[j]["template_family"] or rows[i]["company"] == rows[j]["company"]:
            continue
        a, b = assignments[i]["category_id"], assignments[j]["category_id"]
        kind = "unassigned" if a is None or b is None else "same_cluster" if a == b else "different_clusters"
        strata[kind].append((i, j))
    rng = random.Random(seed)
    sampled = [(kind, pair) for kind, pairs in sorted(strata.items()) for pair in rng.sample(pairs, min(per_stratum, len(pairs)))]
    rng.shuffle(sampled)
    blind, key = [], []
    for kind, (i, j) in sampled:
        if rng.random() < .5:
            i, j = j, i
        identity = hashlib.sha256((rows[i]["id"] + "|" + rows[j]["id"]).encode()).hexdigest()[:20]
        item = dict(pair_id=identity, left={k: rows[i][k] for k in ("id", "direction", "purpose")},
                    right={k: rows[j][k] for k in ("id", "direction", "purpose")}, judgment=None, reviewer="")
        blind.append(item)
        key.append(dict(pair_id=identity, stratum=kind, predicted_same=kind == "same_cluster",
                        both_assigned=kind != "unassigned"))
    out.mkdir(parents=True)
    write_rows(out / "blind_pairs.jsonl", blind)
    write_rows(out / "private_sampling_key.jsonl", key)
    manifest = dict(seed=seed, selected=dict(Counter(k["stratum"] for k in key)),
                    eligible={k: len(v) for k, v in strata.items()}, judgments_prefilled=False,
                    taxonomy_versions=sorted({a["taxonomy_version"] for a in assignments}),
                    instruction="Judge same economic purpose: same/different/uncertain. Do not inspect private_sampling_key while labeling.",
                    limitation="Balanced stratified audit of different companies/templates; not population accuracy")
    manifest["blind_sha256"] = sha256_file(out / "blind_pairs.jsonl")
    manifest["key_sha256"] = sha256_file(out / "private_sampling_key.jsonl")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def score(review: Path, judgments: Path):
    meta = json.loads((review / "manifest.json").read_text())
    key_path = review / "private_sampling_key.jsonl"
    if sha256_file(key_path) != meta["key_sha256"] or sha256_file(review / "blind_pairs.jsonl") != meta["blind_sha256"]:
        raise ValueError("review source changed")
    keys = {r["pair_id"]: r for r in read_rows(key_path)}
    originals = {r["pair_id"]: r for r in read_rows(review / "blind_pairs.jsonl")}
    values = read_rows(judgments)
    seen, totals = set(), Counter()
    for row in values:
        pid = row["pair_id"]
        if pid not in keys or pid in seen:
            raise ValueError("unknown or repeated pair id")
        seen.add(pid)
        if row["left"] != originals[pid]["left"] or row["right"] != originals[pid]["right"]:
            raise ValueError("reviewed pair input changed")
        judgment = row.get("judgment")
        if judgment is None:
            continue
        if judgment not in ("same", "different", "uncertain") or not row.get("reviewer", "").strip():
            raise ValueError("valid judgment and human reviewer identity required")
        totals["reviewed"] += 1
        if judgment == "uncertain":
            totals["uncertain"] += 1
            continue
        k = keys[pid]
        if not k["both_assigned"]:
            totals["unassigned_reviewed"] += 1
            continue
        totals["scored_assigned_pairs"] += 1
        actual, predicted = judgment == "same", k["predicted_same"]
        totals["tp" if predicted and actual else "fp" if predicted else "fn" if actual else "tn"] += 1
    return dict(counts=dict(totals), selected_pair_precision=totals["tp"]/(totals["tp"]+totals["fp"]) if totals["tp"]+totals["fp"] else None,
                selected_pair_recall=totals["tp"]/(totals["tp"]+totals["fn"]) if totals["tp"]+totals["fn"] else None,
                unreviewed=len(keys)-totals["reviewed"], population_accuracy=None, limitation=meta["limitation"],
                taxonomy_versions=meta["taxonomy_versions"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create")
    c.add_argument("--rows", type=Path, required=True)
    c.add_argument("--assignments", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("--review", type=Path, required=True)
    s.add_argument("--judgments", type=Path, required=True)
    a = p.parse_args()
    result = create(read_rows(a.rows), read_rows(a.assignments), a.out) if a.command == "create" else score(a.review, a.judgments)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
