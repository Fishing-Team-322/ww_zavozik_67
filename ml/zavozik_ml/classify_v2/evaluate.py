"""One final evaluation of a frozen v2 artifact against the fixed v1 baseline.

This is deliberately separate from train/export. Looking at errors consumes
the authored holdout as an independent selection set: do not tune against it.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import csv
import json
from pathlib import Path
import time

import numpy as np

from zavozik_ml.classify.model import Classifier
from zavozik_ml.classify.text import Op, counterparty_type, norm_direction
from .calibration import category_scores, binary_scores, expected_calibration_error
from .data import ML_DIR, read_rows, operation
from .model import EncoderClassifier, sha256_file
from .text import Operation


def baseline_predictions(classifier, rows):
    inns = {"org": "0000000000", "person": "000000000000", "none": "", "bad": "0"}
    ops = [Op(r["direction"], r.get("purpose", ""), r.get("name", ""), inns.get(r.get("inn_type", "none"), ""), r.get("amount", 10000)) for r in rows]
    pred = classifier.predict(ops)
    return [p.category for p in pred]


def label_scores(truth, predicted, vocabulary):
    indices = {key: i for i, key in enumerate(vocabulary)}
    y = np.array([indices[c] for c in truth])
    p = np.zeros((len(predicted), len(vocabulary)), np.float32)
    for i, c in enumerate(predicted):
        if c in indices:
            p[i, indices[c]] = 1
    s = category_scores(p, y)
    s.pop("ece")  # one-hot baseline pseudo-probabilities are not confidence
    return s


def predict_rows(classifier, rows, batch_size=256):
    result = []
    started = time.perf_counter()
    for i in range(0, len(rows), batch_size):
        result.extend(classifier.predict([operation(r) for r in rows[i:i+batch_size]]))
    return result, time.perf_counter() - started


def score_rows(classifier, rows, baseline, auxiliary_gold=True):
    predicted, elapsed = predict_rows(classifier, rows)
    t = classifier.taxonomy
    y = np.array([t.categories.index(r["label"]) for r in rows])
    probabilities = np.array([[p.category_probs[c] for c in t.categories] for p in predicted])
    base = baseline_predictions(baseline, rows)
    result = {"category": category_scores(probabilities, y),
              "linear_v1": label_scores([r["label"] for r in rows], base, t.categories),
              "novel_fraction": float(np.mean([p.is_novel for p in predicted])), "elapsed_s": elapsed}
    if auxiliary_gold:
        hy = np.array([t.channels.index(r["channel"]) for r in rows])
        hp = np.array([[p.channel_probs[c] for c in t.channels] for p in predicted])
        tg = np.array([[int(tag in r["tags"]) for tag in t.tags] for r in rows], bool)
        tp = np.array([[tag in p.tags for tag in t.tags] for p in predicted], bool)
        result["channel"] = category_scores(hp, hy)
        result["tags"] = binary_scores(tp, tg)
        result["tags"]["per_tag"] = {tag: binary_scores(tp[:, j], tg[:, j]) for j, tag in enumerate(t.tags)}
    errors = []
    for r, p, linear in zip(rows, predicted, base):
        wrong = []
        if p.category != r["label"]:
            wrong.append("category")
        if auxiliary_gold and p.channel != r["channel"]:
            wrong.append("channel")
        if auxiliary_gold and set(p.tags) != set(r["tags"]):
            wrong.append("tags")
        if wrong or linear != r["label"]:
            errors.append({"id": r.get("id", ""), "group": r.get("group", ""), "purpose": r.get("purpose", ""),
                           "name": r.get("name", ""), "direction": r["direction"], "truth": r["label"],
                           "predicted": p.category, "confidence": max(p.category_probs.values()), "linear_v1": linear,
                           "channel_truth": r.get("channel"), "channel_predicted": p.channel,
                           "tags_truth": r.get("tags"), "tags_predicted": p.tags, "wrong_axes": wrong,
                           "novelty": p.novelty, "is_novel": p.is_novel})
    return result, errors, predicted


def authored_rows(path):
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    if sha256_file(path) != manifest["sha256"]:
        raise ValueError("frozen holdout was modified")
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        for i, r in enumerate(csv.DictReader(f, delimiter="\t"), 1):
            rows.append(dict(id=f"V2-{i:03d}", label=r["category"], channel=r["channel"],
                             tags=list(filter(None, r["tags"].split(","))), direction=r["direction"],
                             name=r["counterparty_name"], purpose=r["payment_purpose"], amount=10000,
                             inn_type="org" if r["counterparty_name"] else "none", group="authored_v1"))
    return rows, manifest


def novel_rows(path):
    # This old dataset is already inspected regression data. Only category gold
    # exists; do not invent channel/tag gold by reusing the weak labeler.
    import pandas as pd
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str).fillna("")
    rows = []
    for r in df.to_dict("records"):
        rows.append(dict(id=r.get("id", ""), label=r.get("expected", r.get("category", "")),
                         direction=norm_direction(r["direction"]), purpose=r.get("payment_purpose", r.get("purpose", "")),
                         name=r.get("counterparty_name", ""), inn_type=counterparty_type(r.get("counterparty_inn", "")),
                         amount=float(r.get("amount") or 10000), group=r.get("group", "")))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--prepared", type=Path, default=ML_DIR / "data/classifier_v2/prepared")
    ap.add_argument("--baseline-company", type=Path, required=True, help="v1 eval artifact trained only on same 90 companies")
    ap.add_argument("--baseline-release", type=Path, default=ML_DIR / "artifacts/classifier")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--overlap-report", type=Path)
    ap.add_argument("--unlock-heldout", action="store_true", help="explicitly consume final evaluation; no subsequent tuning")
    args = ap.parse_args()
    if not args.unlock_heldout:
        ap.error("pass --unlock-heldout only after freezing all selection/calibration/runtime decisions")
    if args.out.exists():
        ap.error("out exists; do not silently repeat/overwrite final evaluation")
    args.out.mkdir(parents=True)
    model = EncoderClassifier.load(args.model)
    baseline_company = Classifier.load(args.baseline_company)
    baseline_release = Classifier.load(args.baseline_release)
    split = json.loads((args.prepared / "data_manifest.json").read_text())
    if set(baseline_company.meta.get("test_companies", [])) != set(split["test_companies"]):
        raise ValueError("baseline company split mismatch")
    if not baseline_company.meta.get("evaluation_only"):
        raise ValueError("company baseline must be evaluation-only; full-data artifact leaks test companies")
    frozen_path = Path(__file__).with_name("heldout_v1.tsv")
    provenance = {"model_version": model.model_version, "taxonomy_version": model.taxonomy.version,
                  "model_manifest_sha256": sha256_file(args.model / "manifest.json"),
                  "authored_fixture_sha256": sha256_file(frozen_path),
                  "baseline_company_weights_sha256": sha256_file(args.baseline_company / "weights.npz"),
                  "baseline_release_weights_sha256": sha256_file(args.baseline_release / "weights.npz"),
                  "policy": "Final evaluation; subsequent changes require a fresh held-out set"}
    (args.out / "evaluation_lock.json").write_text(json.dumps(provenance, indent=2) + "\n")
    results = {"provenance": provenance, "datasets": {}}
    sources = [("company_test", read_rows(args.prepared / "test.jsonl"), baseline_company, True)]
    authored, manifest = authored_rows(frozen_path)
    novel = novel_rows(ML_DIR / "zavozik_ml/classify/novel_test.csv")
    sources += [("novel_regression", novel, baseline_release, False), ("authored_holdout", authored, baseline_release, True)]
    overlap = json.loads(args.overlap_report.read_text()) if args.overlap_report else None
    if overlap and (overlap["frozen_fixture_sha256"] != sha256_file(frozen_path)
                    or overlap["train_sha256"] != split["train"]["sha256"]):
        raise ValueError("input-overlap audit does not match frozen fixture/training source")
    for name, rows, baseline, auxiliary in sources:
        result, errors, predictions = score_rows(model, rows, baseline, auxiliary)
        result["label_source"] = ("partition-local weak category labels; auxiliary regex weak labels" if name == "company_test"
                                  else "previously inspected authored category regression" if name == "novel_regression"
                                  else "synthetic authored labels frozen before training; not external human gold")
        if name == "authored_holdout":
            result["fixture_manifest"] = manifest
            if overlap:
                excluded = set(overlap["exact_overlap_ids"])
                ix = [i for i, r in enumerate(rows) if r["id"] not in excluded]
                clean = [rows[i] for i in ix]
                truth = np.array([model.taxonomy.categories.index(r["label"]) for r in clean])
                cp = np.array([[predictions[i].category_probs[k] for k in model.taxonomy.categories] for i in ix])
                channel_truth = np.array([model.taxonomy.channels.index(r["channel"]) for r in clean])
                channel_p = np.array([[predictions[i].channel_probs[k] for k in model.taxonomy.channels] for i in ix])
                tag_truth = np.array([[tag in r["tags"] for tag in model.taxonomy.tags] for r in clean])
                tag_p = np.array([[tag in predictions[i].tags for tag in model.taxonomy.tags] for i in ix])
                result["input_overlap_audit"] = overlap
                result["without_exact_train_input_overlap"] = {
                    "category": category_scores(cp, truth),
                    "linear_v1": label_scores([r["label"] for r in clean], baseline_predictions(baseline, clean), model.taxonomy.categories),
                    "channel": category_scores(channel_p, channel_truth), "tags": binary_scores(tag_p, tag_truth)}
        digital = [i for i, r in enumerate(rows) if r.get("group") == "digital_ruble" or r.get("channel") == "digital_ruble"]
        if digital:
            result["digital_ruble"] = {"n": len(digital),
                "category_correct": sum(predictions[i].category == rows[i]["label"] for i in digital),
                "channel_correct": sum(predictions[i].channel == "digital_ruble" for i in digital),
                "categories_in_taxonomy": all(predictions[i].category in model.taxonomy.categories for i in digital)}
        results["datasets"][name] = result
        (args.out / (name + "_errors.json")).write_text(json.dumps(errors, ensure_ascii=False, indent=2) + "\n")
        (args.out / "evaluation.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
        print(name, json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
