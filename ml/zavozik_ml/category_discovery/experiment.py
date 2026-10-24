"""Train-only unsupervised fit, then one explicit frozen transfer evaluation."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import time

import numpy as np

from zavozik_ml.classify_v2.model import sha256_file
from .corpus import PROTOCOL, read_rows, write_rows
from .core import CategoryInventory, Settings, fit_inventory, cluster_labels


def load_partition(corpus, embeddings, partition):
    data = json.loads((corpus / "manifest.json").read_text())
    enc = json.loads((embeddings / "manifest.json").read_text())
    if data["protocol"] != PROTOCOL or enc["corpus_manifest_sha256"] != sha256_file(corpus / "manifest.json"):
        raise ValueError("incompatible corpus/embeddings")
    rows_path, vector_path = corpus / f"{partition}_unique.jsonl", embeddings / f"{partition}.npy"
    if sha256_file(rows_path) != data[partition]["unique_sha256"] or sha256_file(vector_path) != enc[partition]["sha256"]:
        raise ValueError("partition payload checksum mismatch")
    return read_rows(rows_path), np.load(vector_path, allow_pickle=False), enc


def assignment_summary(rows, assigned):
    statuses = Counter(a["status"] for a in assigned)
    weighted = Counter()
    families = defaultdict(list)
    for r, a in zip(rows, assigned):
        weighted[a["status"]] += r.get("count", 1)
        families[r["template_family"]].append(a["category_id"] is not None)
    total = sum(weighted.values())
    return dict(unique_texts=len(rows), operations=total, families=len(families), status_unique=dict(statuses),
                status_operations=dict(weighted), assigned_unique_fraction=statuses["assigned"]/max(1, len(rows)),
                assigned_operation_fraction=weighted["assigned"]/max(1, total),
                assigned_family_macro_fraction=float(np.mean([np.mean(v) for v in families.values()])) if families else None,
                supported_categories=len({a["category_id"] for a in assigned if a["category_id"] is not None}),
                semantic_accuracy=None, semantic_accuracy_reason="No independent human labels; assignment coverage is not accuracy")


def stability(records, points, labels, settings):
    from sklearn.metrics import adjusted_rand_score, silhouette_score
    known = labels >= 0
    silhouette = None
    if len(set(labels[known])) > 1 and known.sum() > len(set(labels[known])):
        silhouette = float(silhouette_score(points[known], labels[known], metric="cosine"))
    runs = []
    for seed in range(5):
        ids = np.sort(np.random.default_rng(seed+42).choice(len(points), int(len(points)*.8), replace=False))
        alt = cluster_labels([records[int(i)] for i in ids], points[ids], settings)
        common = (labels[ids] >= 0) & (alt >= 0)
        union = (labels[ids] >= 0) | (alt >= 0)
        runs.append(dict(seed=seed+42, retained_families=len(ids), jointly_clustered=int(common.sum()),
                         clustered_set_jaccard=float(common.sum()/max(1, union.sum())),
                         adjusted_rand_jointly_clustered=float(adjusted_rand_score(labels[ids][common], alt[common])) if common.sum() >= 2 else None,
                         clusters=len(set(alt)-{-1}), noise_fraction=float(np.mean(alt < 0))))
    return dict(train_silhouette_cosine_excluding_noise=silhouette, family_subsample_runs=runs,
                caveat="Internal geometry and perturbation stability, not economic correctness; no test selection")


def fit(corpus: Path, embeddings: Path, out: Path, parent: Path | None = None):
    if out.exists():
        raise ValueError("experiment exists; do not overwrite fitted inventories")
    rows, x, enc = load_partition(corpus, embeddings, "train")
    settings = Settings()
    out.mkdir(parents=True)
    # Freeze source, input binding and all settings BEFORE generating groups.
    src = Path(__file__).parent
    shutil.copytree(src, out / "fit_source", ignore=shutil.ignore_patterns("__pycache__"))
    protocol = dict(corpus_manifest_sha256=sha256_file(corpus / "manifest.json"),
                    embedding_manifest_sha256=sha256_file(embeddings / "manifest.json"),
                    encoder_version=enc["encoder_version"], settings=asdict(settings),
                    parent=CategoryInventory.load(parent).version if parent else None,
                    final_consumed=False, created_unix=time.time(),
                    source_files_sha256={p.name: sha256_file(p) for p in src.glob("*.py")},
                    category_targets=False, fixed_category_count=None)
    (out / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    inv, diagnostics, (records, points, labels) = fit_inventory(rows, x, enc["encoder_version"], settings,
                                                                            CategoryInventory.load(parent) if parent else None)
    inv.save(out / "inventory")
    diagnostics["stability"] = stability(records, points, labels, settings) if len(points) else None
    diagnostics["train_assignment"] = assignment_summary(rows, inv.assign(rows, x, enc["encoder_version"]))
    diagnostics["taxonomy_version"] = inv.version
    (out / "fit_diagnostics.json").write_text(json.dumps(diagnostics, indent=2) + "\n")
    return diagnostics


def evaluate(corpus: Path, embeddings: Path, experiment: Path, unlock: bool):
    if not unlock:
        raise ValueError("explicit --unlock-final required; results cannot be used to tune this candidate")
    protocol = json.loads((experiment / "protocol.json").read_text())
    if protocol["corpus_manifest_sha256"] != sha256_file(corpus / "manifest.json") or protocol["embedding_manifest_sha256"] != sha256_file(embeddings / "manifest.json"):
        raise ValueError("evaluation inputs differ from fitted protocol")
    out = experiment / "final_evaluation"
    if out.exists():
        raise ValueError("final evaluation already consumed; inspect results instead of repeating it")
    # Lock before reading final vectors or predictions, including partial runs.
    out.mkdir()
    inv = CategoryInventory.load(experiment / "inventory")
    report = dict(taxonomy_version=inv.version, protocol=protocol,
                  research_status="semantic_quality_unverified_without_independent_review")
    for p in ("calibration", "test"):
        rows, x, enc = load_partition(corpus, embeddings, p)
        predictions = inv.assign(rows, x, enc["encoder_version"])
        write_rows(out / f"{p}_assignments.jsonl", predictions)
        report[p] = assignment_summary(rows, predictions)
    protocol["final_consumed"] = True
    (experiment / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    (out / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("fit", "evaluate"):
        s = sub.add_parser(command)
        s.add_argument("--corpus", type=Path, required=True)
        s.add_argument("--embeddings", type=Path, required=True)
        s.add_argument("--experiment", type=Path, required=True)
        if command == "fit":
            s.add_argument("--parent", type=Path)
        else:
            s.add_argument("--unlock-final", action="store_true")
    a = p.parse_args()
    result = fit(a.corpus, a.embeddings, a.experiment, a.parent) if a.command == "fit" else evaluate(a.corpus, a.embeddings, a.experiment, a.unlock_final)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
