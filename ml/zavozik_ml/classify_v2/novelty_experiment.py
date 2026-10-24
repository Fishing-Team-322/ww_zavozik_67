"""A leakage-controlled hidden-category experiment, run after recipe freeze.

The supplied model must have excluded whole categories from ALL fitting and
calibration targets. Discovery sees ALL operations of calibration companies,
including false novel alerts from known classes; oracle labels name proposals
only after clustering. New prototypes are evaluated on separate test companies.
Test embeddings are never used to form their own category prototype.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from .data import ML_DIR, read_rows
from .discovery import propose
from .evaluate import predict_rows, label_scores
from .model import EncoderClassifier, unit, sha256_file
from .taxonomy import Taxonomy


def run(model_dir: Path, prepared: Path, out: Path, min_cluster_size=5):
    if out.exists():
        raise ValueError("experiment already exists; do not overwrite test results")
    model = EncoderClassifier.load(model_dir)
    full = Taxonomy.load()
    hidden = set(model.config.get("hidden_categories", []))
    if not hidden or set(full.categories) - set(model.taxonomy.categories) != hidden:
        raise ValueError("model must have excluded the declared hidden categories")
    split = json.loads((prepared / "data_manifest.json").read_text())
    if set(split["calibration_companies"]) & set(split["test_companies"]):
        raise ValueError("discovery/evaluation companies overlap")
    test = read_rows(prepared / "test.jsonl")
    cal = read_rows(prepared / "calibration_full.jsonl")
    # Never prefilter this pool with the hidden-category gold. That would
    # remove known-class false alerts and make cluster purity optimistic.
    discovery_rows = cal
    hidden_test = [r for r in test if r["label"] in hidden]
    known_test = [r for r in test if r["label"] not in hidden]
    out.mkdir(parents=True)
    discovery_pred, _ = predict_rows(model, discovery_rows)
    hidden_pred, _ = predict_rows(model, hidden_test)
    known_pred, _ = predict_rows(model, known_test)
    records = []
    for row, prediction in zip(discovery_rows, discovery_pred):
        records.append(dict(prediction.as_dict(), id=row["id"], purpose=row["purpose"],
                            direction=row["direction"], counterparty_name=row["name"]))
    proposals, centers = propose(model, records, min_cluster_size=min_cluster_size)
    (out / "proposals.json").write_text(json.dumps(proposals, ensure_ascii=False, indent=2) + "\n")
    np.savez_compressed(out / "centers.npz", **centers)
    # Simulation uses true discovery labels to stand in for the human naming
    # step. This is explicit oracle supervision, not autonomous discovery of
    # category names and not human confirmation of a production category.
    extended = model
    extensions = []
    for category in sorted(hidden):
        candidates = []
        for proposal in proposals["proposals"]:
            # Exact HDBSCAN membership; noise points are not silently assigned
            # to their nearest cluster when estimating naming purity.
            group = [discovery_rows[i] for i in proposal["member_indices"]]
            counts = Counter(r["label"] for r in group)
            if counts and counts.most_common(1)[0][0] == category:
                candidates.append((counts[category] / len(group), counts[category], proposal, group))
        if not candidates:
            extensions.append({"category": category, "added": False, "reason": "no discovered cluster dominated by category"})
            continue
        purity, support, proposal, group = max(candidates, key=lambda item: (item[0], item[1]))
        if purity < .8:
            extensions.append({"category": category, "added": False, "reason": "cluster naming purity below fixed 80% requirement"})
            continue
        if proposal["kind"] != "new_category_review":
            extensions.append({"category": category, "added": False, "reason": "cluster flagged as existing-category synonym"})
            continue
        extended = extended.add_category(full.category(category), centers[proposal["candidate_id"]],
                                          extended.taxonomy.version + "+simulated-" + category)
        extensions.append({"category": category, "added": True, "cluster": proposal["candidate_id"],
                           "discovery_support": support, "discovery_naming_purity": purity,
                           "approval": "simulated_oracle_labels_from_discovery_companies_only"})
    # Reuse saved embeddings; no encoder update or second inference can change
    # the comparison. The new prototype centers contain no test information.
    if hidden_pred:
        distribution = extended.distributions(np.stack([p.embedding for p in hidden_pred]))["category"]
        after = [extended.taxonomy.categories[int(i)] for i in distribution.argmax(1)]
    else:
        after = []
    per_category = {}
    for category in sorted(hidden):
        ix = [i for i, r in enumerate(hidden_test) if r["label"] == category]
        per_category[category] = {"n": len(ix), "novel_detected": sum(hidden_pred[i].is_novel for i in ix),
                                  "novel_recall": float(np.mean([hidden_pred[i].is_novel for i in ix])) if ix else None,
                                  "correct_after_extension": sum(after[i] == category for i in ix),
                                  "accuracy_after_extension": float(np.mean([after[i] == category for i in ix])) if ix else None}
    known_before = [p.category for p in known_pred]
    known_distribution = extended.distributions(np.stack([p.embedding for p in known_pred]))["category"]
    known_after = [extended.taxonomy.categories[int(i)] for i in known_distribution.argmax(1)]
    result = {"model_version": model.model_version, "hidden_categories": sorted(hidden),
              "model_manifest_sha256": sha256_file(model_dir / "manifest.json"),
              "discovery_companies": split["calibration_companies"], "test_companies": split["test_companies"],
              "discovery_rows": len(discovery_rows), "discovery_unique_texts": len({r["text"] for r in discovery_rows}),
              "discovery_hidden_rows": sum(r["label"] in hidden for r in discovery_rows),
              "discovery_known_rows": sum(r["label"] not in hidden for r in discovery_rows),
              "discovery_novel_rows": sum(p.is_novel for p in discovery_pred),
              "discovery_known_novel_rows": sum(p.is_novel and r["label"] not in hidden
                                                 for r, p in zip(discovery_rows, discovery_pred)),
              "discovery_prefiltered_by_gold": False,
              "hidden_test_rows": len(hidden_test), "known_test_rows": len(known_test),
              "hidden_novel_recall": float(np.mean([p.is_novel for p in hidden_pred])) if hidden_pred else None,
              "known_false_positive_rate": float(np.mean([p.is_novel for p in known_pred])),
              "per_hidden_category": per_category, "extensions": extensions,
              "after_extension_hidden_accuracy": float(np.mean([p == r["label"] for p, r in zip(after, hidden_test)])) if hidden_test else None,
              "known_accuracy_before": float(np.mean([p == r["label"] for p, r in zip(known_before, known_test)])),
              "known_accuracy_after": float(np.mean([p == r["label"] for p, r in zip(known_after, known_test)])),
              "encoder_retrained": False,
              "test_used_for_prototype_or_threshold": False,
              "limitations": ["Synthetic weak labels, not independent human gold", "Few hidden enforcement events",
                               "Cluster naming uses simulated oracle review, not a real human approval"]}
    (out / "novelty_experiment.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--prepared", type=Path, default=ML_DIR / "data/classifier_v2/prepared")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--min-cluster-size", type=int, default=5)
    args = p.parse_args()
    run(args.model, args.prepared, args.out, args.min_cluster_size)


if __name__ == "__main__":
    main()
