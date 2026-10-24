"""Fit a prototype/category + channel + tag encoder on training companies.

Only train.jsonl/calibration*.jsonl are read. Neither company test nor the
frozen authored fixtures are ever accessed here. Checkpoint selection and all
calibration use calibration companies. Final scoring is a separate command.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import random
import time

# Initialize Torch before other OpenMP users on macOS.
import torch
from torch import nn
from torch.nn import functional as F
import numpy as np
from transformers import AutoModel, AutoTokenizer

from .calibration import binary_scores, calibrate, category_scores
from .data import ML_DIR, read_rows
from .model import softmax, sigmoid, sha256_file, ARTIFACT_VERSION
from .network import MultiTaskEncoder, supervised_contrastive
from .taxonomy import Taxonomy
from .text import NORMALIZER_VERSION
from .artifact import archive_fitting_sources
from .splitting import PROTOCOL
from .token_audit import validate as validate_token_audit


def targets(rows, taxonomy):
    cat = {s: i for i, s in enumerate(taxonomy.categories)}
    ch = {s: i for i, s in enumerate(taxonomy.channels)}
    return (np.array([cat[r["label"]] for r in rows], np.int64),
            np.array([ch[r["channel"]] for r in rows], np.int64),
            np.array([[int(tag in r["tags"]) for tag in taxonomy.tags] for r in rows], np.float32))


def tokenize(tokenizer, rows, max_length, prefix=""):
    texts = [prefix + r["text"] for r in rows]
    batch = tokenizer(texts, padding="max_length", truncation=True, max_length=max_length, return_tensors="np")
    return {k: np.asarray(v, np.int64) for k, v in batch.items() if k in ("input_ids", "attention_mask", "token_type_ids")}


def batch_tokens(tokens, indices, device):
    # MPS graph/allocator caches grow with many sequence shapes. A fixed
    # padded training shape keeps memory bounded; the attention mask and
    # original token prefix are identical. CPU/CUDA retain right-pad trimming.
    length = (tokens["input_ids"].shape[1] if device.type == "mps" else
              max(1, int(tokens["attention_mask"][indices].sum(axis=1).max())))
    return {k: torch.from_numpy(v[indices, :length]).to(device) for k, v in tokens.items()}


def inference(model, tokens, device, batch_size):
    result = {k: [] for k in ("embedding", "category_logits", "channel_logits", "tag_logits", "novelty")}
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(tokens["input_ids"]), batch_size):
            ix = np.arange(start, min(start + batch_size, len(tokens["input_ids"])))
            out = model(**batch_tokens(tokens, ix, device))
            for k in result:
                result[k].append(out[k].cpu().numpy())
    return {k: np.concatenate(v) for k, v in result.items()}


def save_checkpoint(directory, model, tokenizer, taxonomy, config):
    directory.mkdir(parents=True, exist_ok=True)
    model.encoder.save_pretrained(directory / "encoder", safe_serialization=True)
    tokenizer.save_pretrained(directory / "encoder")
    tokenizer.backend_tokenizer.save(str(directory / "tokenizer.json"))
    heads = {"prototypes": F.normalize(model.prototypes.detach(), dim=-1).cpu().numpy(),
             "channel_weight": model.channel.weight.detach().cpu().numpy(),
             "channel_bias": model.channel.bias.detach().cpu().numpy(),
             "tag_weight": model.tags.weight.detach().cpu().numpy(), "tag_bias": model.tags.bias.detach().cpu().numpy()}
    np.savez_compressed(directory / "heads.npz", **heads)
    (directory / "taxonomy.json").write_text(taxonomy.dumps())
    config = dict(config, category_scale=float(model.log_scale.detach().clamp(0, math.log(100)).exp().cpu()))
    archive_fitting_sources(config, ML_DIR, directory)
    (directory / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", type=Path, required=True, help="offline pinned pretrained directory")
    ap.add_argument("--prepared", type=Path, default=ML_DIR / "data/classifier_v2/prepared")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--max-length", type=int, default=128)
    ap.add_argument("--lr", type=float, default=4e-5)
    ap.add_argument("--head-lr", type=float, default=.005)
    ap.add_argument("--contrastive", type=float, default=.1)
    ap.add_argument("--channel-loss", type=float, default=.5)
    ap.add_argument("--tag-loss", type=float, default=.5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", choices=("mps", "cpu", "cuda"), default="mps" if torch.backends.mps.is_available() else "cpu")
    ap.add_argument("--hide", default="", help="categories entirely excluded from training and calibration")
    ap.add_argument("--limit-train", type=int, default=0, help="smoke only; never release a limited run")
    ap.add_argument("--pooling", choices=("cls", "mean"), default="cls")
    ap.add_argument("--text-prefix", default="")
    args = ap.parse_args()
    if args.out.exists():
        ap.error("out already exists; choose a new run directory")
    args.out.mkdir(parents=True)
    if args.device == "mps":
        # Default unified-memory limits are too permissive for this16GiB host.
        # Keep math/optimizer unchanged; commit buffers and collect idle cache
        # earlier instead of driving the laptop into swap pressure.
        os.environ.setdefault("PYTORCH_MPS_LOW_WATERMARK_RATIO", "0.7")
        os.environ.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "1.0")
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    torch.set_num_threads(4)
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    device = torch.device(args.device)
    taxonomy = Taxonomy.load()
    hidden = set(filter(None, args.hide.split(",")))
    if hidden:
        taxonomy = taxonomy.without(hidden)
    manifest = json.loads((args.prepared / "data_manifest.json").read_text())
    validate_token_audit(args.prepared, args.base, args.text_prefix, args.max_length)
    if (manifest.get("split_protocol") != PROTOCOL or not manifest.get("split_audit", {}).get("passed")
            or any(value for pair in manifest["split_audit"]["pairwise_intersections"].values() for value in pair.values())):
        raise ValueError("training requires audited company AND template-disjoint data")
    for filename, key in (("split_audit.json", "split_audit_sha256"), ("template_registry.json", "template_registry_sha256")):
        if sha256_file(args.prepared / filename) != manifest[key]:
            raise ValueError(f"frozen split metadata changed: {filename}")
    if not manifest.get("preparation_files_sha256"):
        raise ValueError("preparation provenance missing; regenerate data")
    for path, digest in manifest["preparation_files_sha256"].items():
        if sha256_file(ML_DIR / path) != digest:
            raise ValueError(f"prepared data is stale after source change: {path}")
    for name in ("train", "calibration"):
        if sha256_file(args.prepared / (name + ".jsonl")) != manifest[name]["sha256"]:
            raise ValueError(f"prepared {name} file changed after preparation")
    all_train, all_cal = read_rows(args.prepared / "train.jsonl"), read_rows(args.prepared / "calibration.jsonl")
    train = [r for r in all_train if r["label"] in taxonomy.categories]
    cal = [r for r in all_cal if r["label"] in taxonomy.categories]
    assert not set(manifest["train_companies"]) & set(manifest["calibration_companies"])
    assert not set(manifest["train_companies"]) & set(manifest["test_companies"])
    if args.limit_train:
        rng = random.Random(args.seed)
        train = rng.sample(train, min(args.limit_train, len(train)))
    tokenizer = AutoTokenizer.from_pretrained(args.base, local_files_only=True, trust_remote_code=False)
    base = AutoModel.from_pretrained(args.base, local_files_only=True, trust_remote_code=False, attn_implementation="eager")
    model = MultiTaskEncoder(base, len(taxonomy.categories), len(taxonomy.channels), len(taxonomy.tags), args.pooling).to(device)
    print(f"train={len(train)} calibration={len(cal)} categories={len(taxonomy.categories)} device={device}", flush=True)
    print("tokenizing", flush=True)
    tr_tokens, cal_tokens = tokenize(tokenizer, train, args.max_length, args.text_prefix), tokenize(tokenizer, cal, args.max_length, args.text_prefix)
    cy, hy, ty = targets(train, taxonomy)
    ccal, hcal, tcal = targets(cal, taxonomy)
    descriptions = [args.text_prefix + x["description_ru"] for x in taxonomy.document["categories"]]
    with torch.inference_mode():
        model.eval()
        t = tokenizer(descriptions, padding=True, truncation=True, max_length=args.max_length, return_tensors="pt")
        model.prototypes.copy_(model.embeddings(**{k: v.to(device) for k, v in t.items()}))
    encoder_parameters = list(model.encoder.parameters())
    encoder_ids = {id(p) for p in encoder_parameters}
    head_parameters = [p for p in model.parameters() if id(p) not in encoder_ids]
    optimizer = torch.optim.AdamW([{"params": encoder_parameters, "lr": args.lr},
                                   {"params": head_parameters, "lr": args.head_lr}], weight_decay=.01)
    n_steps = math.ceil(len(train) / args.batch_size) * args.epochs
    def schedule(step):
        warmup = max(1, int(.06 * n_steps))
        return min((step + 1) / warmup, max(.1, (n_steps - step) / max(1, n_steps - warmup)))
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, schedule)
    cw = np.bincount(cy, minlength=len(taxonomy.categories)).astype(float)
    cw = (cw.mean() / np.maximum(cw, 1)) ** .35
    hw = np.bincount(hy, minlength=len(taxonomy.channels)).astype(float)
    hw = (hw.mean() / np.maximum(hw, 1)) ** .25
    positive = np.clip((len(ty) - ty.sum(0)) / np.maximum(ty.sum(0), 1), 1, 12)
    cw, hw, positive = [torch.tensor(x, dtype=torch.float32, device=device) for x in (cw, hw, positive)]
    weights = np.asarray([r.get("weight", 1) for r in train], np.float32)
    best_score = -float("inf")
    history = []
    start = time.perf_counter()
    cfg = {"artifact_version": ARTIFACT_VERSION, "normalizer_version": NORMALIZER_VERSION,
           "embedding_dim": base.config.hidden_size, "max_length": args.max_length,
           "pooling": args.pooling, "text_prefix": args.text_prefix,
           "pad_token_id": tokenizer.pad_token_id, "pad_token": tokenizer.pad_token,
           "taxonomy_sha256": taxonomy.sha256, "category_temperature": 1.0, "channel_temperature": 1.0,
           "tag_thresholds": [.5] * len(taxonomy.tags), "novelty_threshold": 1.0, "runtime": "torch",
           "cpu_threads": 4, "inference_batch_size": 64,
           "base_source": json.loads((args.base / "base_source.json").read_text()),
           "training": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
           "data_manifest": manifest, "hidden_categories": sorted(hidden),
           "training_runtime": {"mps_fixed_padding": True, "mps_cache_release_every_batches": 100,
                                "mps_low_watermark_ratio": os.environ.get("PYTORCH_MPS_LOW_WATERMARK_RATIO"),
                                "mps_high_watermark_ratio": os.environ.get("PYTORCH_MPS_HIGH_WATERMARK_RATIO")}}
    # Save only the files that determine fitting/calibration. New serving/tests
    # may be written while this run is active without obscuring fit provenance.
    fit_files = [Path(__file__).with_name(name) for name in (
        "train.py", "network.py", "model.py", "calibration.py", "novelty.py", "data.py", "splitting.py", "token_audit.py", "text.py", "weak_labels.py", "taxonomy.py", "taxonomy.json")]
    fit_files += [ML_DIR / "zavozik_ml/classify" / name for name in ("augment.py", "labels.py", "text.py")]
    cfg["training_files_sha256"] = {str(p.relative_to(ML_DIR)): sha256_file(p) for p in fit_files}
    for epoch in range(1, args.epochs + 1):
        model.train()
        permutation = np.random.default_rng(args.seed + epoch).permutation(len(train))
        losses = []
        for batch, start_i in enumerate(range(0, len(train), args.batch_size)):
            ix = permutation[start_i:start_i + args.batch_size]
            out = model(**batch_tokens(tr_tokens, ix, device))
            c, h = torch.from_numpy(cy[ix]).to(device), torch.from_numpy(hy[ix]).to(device)
            tags = torch.from_numpy(ty[ix]).to(device)
            weight = torch.from_numpy(weights[ix]).to(device)
            category_loss = F.cross_entropy(out["category_logits"], c, weight=cw, reduction="none")
            channel_loss = F.cross_entropy(out["channel_logits"], h, weight=hw, reduction="none")
            tag_loss = F.binary_cross_entropy_with_logits(out["tag_logits"], tags, pos_weight=positive, reduction="none").mean(1)
            loss = ((category_loss + args.channel_loss * channel_loss + args.tag_loss * tag_loss) * weight).sum() / weight.sum()
            contrast = supervised_contrastive(out["embedding"], c, exclude_label=taxonomy.categories.index("other") if "other" in taxonomy.categories else None)
            loss = loss + args.contrastive * contrast
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1)
            optimizer.step(); scheduler.step()
            losses.append(float(loss.detach().cpu()))
            if batch % 100 == 0:
                if device.type == "mps":
                    torch.mps.synchronize()
                    torch.mps.empty_cache()
                    print(f"mps allocated_gib={torch.mps.current_allocated_memory()/2**30:.3f} driver_gib={torch.mps.driver_allocated_memory()/2**30:.3f}", flush=True)
                print(f"epoch={epoch} batch={batch} loss={np.mean(losses[-100:]):.4f} elapsed={time.perf_counter()-start:.1f}s", flush=True)
        raw = inference(model, cal_tokens, device, args.batch_size)
        category = category_scores(softmax(raw["category_logits"]), ccal)
        channel = category_scores(softmax(raw["channel_logits"]), hcal)
        tags = binary_scores(sigmoid(raw["tag_logits"]) >= .5, tcal)
        score = category["accuracy"] + .15 * category["macro_f1"] + .05 * channel["accuracy"] + .05 * tags["micro_f1"]
        record = dict(epoch=epoch, loss=float(np.mean(losses)), category=category, channel=channel, tags=tags,
                      score=score, elapsed_s=time.perf_counter() - start)
        history.append(record)
        print(json.dumps(record), flush=True)
        if score > best_score:
            best_score = score
            cfg["selected_epoch"] = epoch
            save_checkpoint(args.out / "selected", model, tokenizer, taxonomy, cfg)
            np.savez_compressed(args.out / "selected/calibration_raw.npz", **raw, category_y=ccal, channel_y=hcal, tag_y=tcal)
        (args.out / "history.json").write_text(json.dumps(history, indent=2) + "\n")
        if device.type == "mps":
            torch.mps.empty_cache()
    # Calibrate the selected artifact, not the final training epoch.
    selected = args.out / "selected"
    if any(sha256_file(ML_DIR / p) != digest for p, digest in cfg["training_files_sha256"].items()):
        raise RuntimeError("fitting source changed during training; preserve checkpoint and inspect provenance")
    with np.load(selected / "calibration_raw.npz", allow_pickle=False) as r:
        calibration = calibrate(dict(r), r["category_y"], r["channel_y"], r["tag_y"], categories=taxonomy.categories)
    config = json.loads((selected / "config.json").read_text())
    for key in ("category_temperature", "channel_temperature", "tag_thresholds", "novelty_threshold", "novelty_reference"):
        config[key] = calibration[key]
    config["model_version"] = "encoder-v1-" + sha256_file(selected / "encoder/model.safetensors")[:16]
    (selected / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    (selected / "calibration.json").write_text(json.dumps(calibration, indent=2) + "\n")
    print("selected", selected, json.dumps(calibration), flush=True)


if __name__ == "__main__":
    main()
