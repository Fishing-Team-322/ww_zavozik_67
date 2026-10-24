"""Offline novelty review. Proposals never change a running model/taxonomy.

`propose` accepts locally stored v2 predictions and clusters only is_novel rows.
`approve` requires an explicit reviewed category document and reviewer identity,
and writes a NEW immutable model directory reusing the exact encoder weights.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil

import numpy as np

from .artifact import publish, seal
from .model import EncoderClassifier, unit, sha256_file
from .taxonomy import Taxonomy


def propose(classifier: EncoderClassifier, records: list[dict], min_cluster_size: int = 8,
            synonym_similarity: float = .95) -> tuple[dict, dict[str, np.ndarray]]:
    if min_cluster_size < 3 or not 0 <= synonym_similarity <= 1:
        raise ValueError("invalid cluster parameters")
    eligible = []
    eligible_source_indices = []
    for source_index, record in enumerate(records):
        if record.get("model_version") != classifier.model_version or record.get("taxonomy_version") != classifier.taxonomy.version:
            raise ValueError("mixed or incompatible embedding model/taxonomy versions")
        x = np.asarray(record.get("embedding"), np.float32)
        if x.shape != (classifier.config["embedding_dim"],) or not np.isfinite(x).all() or np.linalg.norm(x) < 1e-8:
            raise ValueError("invalid stored embedding")
        if type(record.get("is_novel")) is not bool:
            raise ValueError("is_novel must be boolean")
        # Recompute novelty with the declared artifact. Do not let a stale or
        # caller-supplied flag silently redefine which rows are truly eligible.
        score = float(classifier.distributions(x[None])["novelty"][0])
        if record["is_novel"] and score > classifier.config["novelty_threshold"]:
            eligible.append((record, unit(x)))
            eligible_source_indices.append(source_index)
    report = {"model_version": classifier.model_version, "taxonomy_version": classifier.taxonomy.version,
              "input_rows": len(records), "eligible_novel_rows": len(eligible),
              "min_cluster_size": min_cluster_size, "synonym_similarity": synonym_similarity,
              "proposals": [], "noise_rows": len(eligible),
              "policy": "Proposals only. Human confirmation required; production never self-adds."}
    centers = {}
    if len(eligible) < min_cluster_size:
        return report, centers
    from sklearn.cluster import HDBSCAN
    values = np.stack([x for _, x in eligible])
    labels = HDBSCAN(min_cluster_size=min_cluster_size, min_samples=min(3, min_cluster_size),
                     metric="euclidean", allow_single_cluster=True, n_jobs=1).fit_predict(values)
    report["noise_rows"] = int((labels == -1).sum())
    stops = {"оплата", "платеж", "за", "по", "на", "от", "и", "в", "с", "из", "для", "средств", "рублей", "рублями", "номер", "дата"}
    for label in sorted(set(labels) - {-1}):
        positions = np.flatnonzero(labels == label)
        center = unit(values[positions].mean(0))
        key = f"cluster_{int(label):03d}"
        centers[key] = center
        similarity = classifier.heads["prototypes"] @ center
        nearest = int(similarity.argmax())
        representative_order = positions[np.argsort(-(values[positions] @ center))[:10]]
        representatives = []
        for i in representative_order:
            r = eligible[int(i)][0]
            representatives.append({"id": r.get("id", ""), "purpose": r.get("purpose", r.get("payment_purpose", "")),
                                    "counterparty_name": r.get("counterparty_name", "")})
        words = Counter(w for r in representatives for w in re.findall(r"[а-яё]{3,}", r["purpose"].lower()) if w not in stops)
        directions = Counter(eligible[int(i)][0].get("direction") for i in positions)
        direction, count = directions.most_common(1)[0]
        if direction not in ("in", "out") or count / len(positions) < .8:
            direction = "both"
        owner_fraction = np.mean(["owner_money" in eligible[int(i)][0].get("tags", []) for i in positions])
        regular_fraction = np.mean(["recurring_like" in eligible[int(i)][0].get("tags", []) for i in positions])
        report["proposals"].append({
            "candidate_id": key, "size": len(positions), "representatives": representatives,
            "member_indices": [eligible_source_indices[int(i)] for i in positions],
            "nearest_category": classifier.taxonomy.categories[nearest], "similarity": float(similarity[nearest]),
            "kind": "synonym_review" if similarity[nearest] >= synonym_similarity else "new_category_review",
            "proposed_title_ru": "Кандидат: " + ", ".join(w for w, _ in words.most_common(3)),
            "proposed_attributes": {"flow": "owner" if owner_fraction >= .8 else "business", "direction": direction,
                                    "mandatory": False, "regular_hint": bool(regular_fraction >= .7)},
            "attributes_status": "heuristic suggestions, require human confirmation",
        })
    return report, centers


def approve(source: Path, report_path: Path, centers_path: Path, candidate_id: str,
            reviewed_category: dict, new_taxonomy_version: str, reviewer: str,
            model_root: Path, workdir: Path) -> Path:
    if not reviewer.strip():
        raise ValueError("human reviewer identity is required")
    classifier = EncoderClassifier.load(source)
    report = json.loads(report_path.read_text())
    if report["model_version"] != classifier.model_version or report["taxonomy_version"] != classifier.taxonomy.version:
        raise ValueError("proposal provenance does not match source model")
    if sha256_file(centers_path) != report.get("centers_sha256"):
        raise ValueError("proposal centers digest mismatch")
    candidates = [c for c in report["proposals"] if c["candidate_id"] == candidate_id]
    if len(candidates) != 1:
        raise ValueError("candidate not found or ambiguous")
    if candidates[0]["kind"] != "new_category_review":
        raise ValueError("candidate is a probable synonym; do not create a duplicate category")
    with np.load(centers_path, allow_pickle=False) as centers:
        center = centers[candidate_id]
    extended = classifier.add_category(reviewed_category, center, new_taxonomy_version)
    if workdir.exists():
        raise ValueError("workdir already exists")
    shutil.copytree(source, workdir)
    np.savez_compressed(workdir / "heads.npz", **extended.heads)
    (workdir / "taxonomy.json").write_text(extended.taxonomy.dumps())
    config = dict(extended.config, parent_model_version=classifier.model_version,
                  extension={"candidate_id": candidate_id, "reviewer": reviewer,
                             "method": "human_confirmed_cluster_center_without_encoder_retraining"})
    (workdir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    seal(workdir)
    (workdir / "README.md").write_text(
        f"# Extension of {classifier.model_version}\n\n"
        f"Confirmed by {reviewer}; candidate {candidate_id}. New taxonomy {new_taxonomy_version}.\n"
        "Encoder unchanged; category/channel/tag heads and open-set threshold require a new independent assessment.\n"
        "The parent model card documents original training and limitations. This extension has not been promoted automatically.\n")
    return publish(workdir, model_root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("propose")
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--predictions", type=Path, required=True, help="JSONL v2 outputs + optional id/direction/purpose")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--min-cluster-size", type=int, default=8)
    p = sub.add_parser("approve")
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--centers", type=Path, required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--reviewed-category", type=Path, required=True, help="human-authored taxonomy entry JSON")
    p.add_argument("--taxonomy-version", required=True)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--model-root", type=Path, required=True)
    p.add_argument("--workdir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "propose":
        records = [json.loads(s) for s in args.predictions.read_text().splitlines() if s.strip()]
        report, centers = propose(EncoderClassifier.load(args.model), records, args.min_cluster_size)
        if args.out.exists():
            parser.error("out already exists")
        args.out.mkdir(parents=True)
        np.savez_compressed(args.out / "centers.npz", **centers)
        report["centers_sha256"] = sha256_file(args.out / "centers.npz")
        (args.out / "candidates.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"proposals": len(centers), "eligible": report["eligible_novel_rows"]}))
    else:
        print(approve(args.model, args.report, args.centers, args.candidate,
                      json.loads(args.reviewed_category.read_text()), args.taxonomy_version,
                      args.reviewer, args.model_root, args.workdir))


if __name__ == "__main__":
    main()
