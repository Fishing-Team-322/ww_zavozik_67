"""Bounded TWO-level metric adaptation of a FROZEN encoder's cached features.

No category vocabulary, implicit in-batch negatives, final-test read, or full
encoder fine-tuning. Weak supervision requires an explicit flag and remains
weak in every output. Independent production quality is NOT established here.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

import numpy as np

from zavozik_ml.classify_v2.model import sha256_file
from .corpus import read_rows

LEVELS = ("coarse", "fine")


def load_part(corpus, cache, labels, part, allow_weak, minimum_support):
    meta = json.loads((corpus / "manifest.json").read_text())
    if "intersections" not in meta or any(v for entry in meta["intersections"].values() for v in entry.values()):
        raise ValueError("prepared corpus must have a zero-intersection split audit")
    encoded = json.loads((cache / "manifest.json").read_text())
    path = corpus / f"{part}_unique.jsonl"
    if (sha256_file(path) != meta[part]["unique_sha256"] or
            encoded["corpus_manifest_sha256"] != sha256_file(corpus / "manifest.json") or
            sha256_file(cache / f"{part}.npy") != encoded[part]["sha256"] or
            encoded[part]["unique_sha256"] != meta[part]["unique_sha256"]):
        raise ValueError("feature/corpus provenance changed")
    rows = read_rows(path)
    x = np.load(cache / f"{part}.npy", allow_pickle=False)
    if x.ndim != 2 or len(x) != len(rows) or not np.isfinite(x).all():
        raise ValueError("bad cached features")
    positions = {r["content_key"]: i for i, r in enumerate(rows)}
    pairs, seen, provenance = [], set(), Counter()
    for r in read_rows(labels):
        if r["partition"] != part:
            raise ValueError("pair partition mismatch")
        source = r.get("provenance")
        if source == "local_model_weak":
            if not allow_weak or r.get("reviewer_kind") != "local_model":
                raise ValueError("weak supervision requires explicit research opt-in")
        elif source == "human_consensus":
            humans = {v["reviewer"] for v in r.get("annotations", []) if v["reviewer_kind"] == "human"}
            if len(humans) < 2:
                raise ValueError("two distinct human reviewers required for consensus")
        else:
            raise ValueError("unsupported pair label provenance")
        ids = []
        for side in ("left", "right"):
            endpoint = r[side]
            if endpoint["content_key"] not in positions:
                raise ValueError("pair endpoint outside declared corpus partition")
            i = positions[endpoint["content_key"]]
            if any(endpoint[k] != rows[i][k] for k in ("id", "purpose", "direction")):
                raise ValueError("pair input changed")
            ids.append(i)
        key = tuple(sorted(ids))
        if ids[0] == ids[1] or key in seen:
            raise ValueError("duplicate/self training pair")
        seen.add(key)
        targets = []
        for level in LEVELS:
            if r[level] not in ("same", "different", "uncertain"):
                raise ValueError("invalid economic relation")
            targets.append({"same": 1, "different": 0, "uncertain": -1}[r[level]])
        if targets[1] == 1 and targets[0] != 1 or targets[0] == 0 and targets[1] != 0:
            raise ValueError("inconsistent hierarchy target")
        pairs.append(ids + targets)
        provenance[source] += 1
    matrix = np.asarray(pairs, np.int64).reshape(-1, 4)
    counts = {level: dict(Counter("same" if y == 1 else "different" if y == 0 else "uncertain" for y in matrix[:, i+2]))
              for i, level in enumerate(LEVELS)}
    if any(counts[level].get(value, 0) < minimum_support for level in LEVELS for value in ("same", "different")):
        raise ValueError(f"insufficient same/different support for two-level fit: {counts}")
    return x, matrix, dict(provenance), counts


def fit(corpus: Path, cache: Path, train_labels: Path, calibration_labels: Path, out: Path, *,
        allow_weak=False, seed=42, epochs=6, patience=2, minimum_support=20):
    if out.exists() or not 1 <= epochs <= 6 or not 1 <= patience <= 2 or minimum_support < 1:
        raise ValueError("immutable output, <=6 epochs, <=2 patience and positive support required")
    tx, train, train_prov, train_counts = load_part(corpus, cache, train_labels, "train", allow_weak, minimum_support)
    cx, cal, cal_prov, cal_counts = load_part(corpus, cache, calibration_labels, "calibration", allow_weak, minimum_support)
    if tx.shape[1] != cx.shape[1]:
        raise ValueError("train/calibration encoder dimensions differ")
    import torch
    from torch import nn
    import torch.nn.functional as F
    torch.set_num_threads(2)
    torch.manual_seed(seed)
    dim = tx.shape[1]
    heads = nn.ModuleDict({level: nn.Linear(dim, dim) for level in LEVELS})
    with torch.no_grad():
        for head in heads.values():
            head.weight.copy_(torch.eye(dim))
            head.weight.add_(torch.randn_like(head.weight) * .0001)
            head.bias.copy_(-torch.from_numpy(tx.mean(0)))
    train_x, cal_x = torch.from_numpy(tx), torch.from_numpy(cx)
    optimizer = torch.optim.AdamW(heads.parameters(), lr=1e-3, weight_decay=1e-4)
    out.mkdir(parents=True)
    recipe = dict(status="research_not_deployable", training_mode="frozen_encoder_two_affine_cosine_heads",
        full_encoder_fine_tuning=False, category_classes="none", output_dimension_per_level=dim,
        seed=seed, maximum_epochs=epochs, patience=patience, minimum_relation_support=minimum_support,
        allow_weak_supervision=allow_weak, train_label_provenance=train_prov, calibration_label_provenance=cal_prov,
        train_counts=train_counts, calibration_counts=cal_counts, final_test_read=False, independent_accuracy=None,
        code_sha256=sha256_file(Path(__file__)), cache_manifest_sha256=sha256_file(cache / "manifest.json"),
        corpus_manifest_sha256=sha256_file(corpus / "manifest.json"),
        train_labels_sha256=sha256_file(train_labels), calibration_labels_sha256=sha256_file(calibration_labels),
        feature_normalization="L2 pretrained; train-only mean centering at head initialization",
        loss="explicit pair cosine contrastive, balanced known relations per level, negative margin0.15; uncertain masked; no in-batch negatives")
    (out / "started.json").write_text(json.dumps(recipe, indent=2)+"\n")
    shutil.copyfile(Path(__file__), out / "fit_source.py.txt")
    def loss_for(x, pairs):
        terms = []
        for i, level in enumerate(LEVELS):
            mask = pairs[:, i+2] >= 0
            if not mask.any():
                continue
            indices = pairs[mask]
            y = torch.from_numpy(indices[:, i+2]).float()
            a = F.normalize(heads[level](x[indices[:, 0]]), dim=1)
            b = F.normalize(heads[level](x[indices[:, 1]]), dim=1)
            cosine = (a*b).sum(1)
            per_pair = torch.where(y == 1, 1-cosine, (cosine-.15).clamp(min=0))
            # Use ONLY train prevalence for weights, including on calibration.
            counts = train_counts[level]
            total = counts["same"] + counts["different"]
            weights = torch.where(y == 1, total/(2*counts["same"]), total/(2*counts["different"]))
            terms.append((per_pair*weights).mean())
        return torch.stack(terms).mean() if terms else None
    def evaluate():
        with torch.no_grad():
            return float(loss_for(cal_x, cal))
    def save(target):
        np.savez(target, **{k: v.detach().numpy() for k, v in heads.state_dict().items()})
    baseline_loss = evaluate()
    best_loss, best_epoch, stale = baseline_loss, 0, 0
    save(out / "best_heads.npz")
    history = []
    rng = np.random.default_rng(seed)
    for epoch in range(1, epochs+1):
        shuffled = train[rng.permutation(len(train))]
        losses = []
        for start in range(0, len(shuffled), 64):
            loss = loss_for(train_x, shuffled[start:start+64])
            if loss is None:
                continue
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(heads.parameters(), 1)
            optimizer.step()
            losses.append(float(loss.detach()))
        cal_loss = evaluate()
        record = dict(epoch=epoch, train_loss=float(np.mean(losses)), calibration_loss=cal_loss)
        history.append(record)
        print(json.dumps(record), flush=True)
        if cal_loss < best_loss - 1e-6:
            best_loss, best_epoch, stale = cal_loss, epoch, 0
            save(out / "best_heads.npz")
        else:
            stale += 1
        (out / "history.json").write_text(json.dumps(history, indent=2)+"\n")
        if stale >= patience:
            break
    recipe.update(best_epoch=best_epoch, baseline_centered_calibration_loss=baseline_loss,
                  best_calibration_loss=best_loss, epochs_run=len(history),
                  head_sha256=sha256_file(out / "best_heads.npz"),
                  limitations="calibration agreement/loss on supplied labels, not independent quality; weak targets remain weak; no online contract migration")
    (out / "manifest.json").write_text(json.dumps(recipe, indent=2)+"\n")
    return recipe


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--train-labels", type=Path, required=True)
    p.add_argument("--calibration-labels", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--allow-weak-supervision", action="store_true")
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    print(json.dumps(fit(a.corpus, a.cache, a.train_labels, a.calibration_labels, a.out,
                         allow_weak=a.allow_weak_supervision, seed=a.seed), indent=2))


if __name__ == "__main__":
    main()
