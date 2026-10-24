"""Export a selected encoder, compare runtimes on calibration, then seal it.

Neither company test nor heldout_v1/novel_test is read. Optional int8 must pass
fixed calibration parity limits; otherwise retain float32 ONNX or PyTorch.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import time

import torch
import numpy as np

from .artifact import seal, archive_fitting_sources
from .calibration import calibrate
from .data import read_rows
from .model import EncoderClassifier, OnnxEncoder, TorchEncoder, unit, sha256_file
from .taxonomy import Taxonomy
from .train import targets


class EmbeddingExport(torch.nn.Module):
    def __init__(self, encoder, pooling):
        super().__init__()
        self.encoder, self.pooling = encoder, pooling

    def forward(self, input_ids, attention_mask, token_type_ids):
        output = self.encoder(input_ids=input_ids, attention_mask=attention_mask,
                              token_type_ids=token_type_ids).last_hidden_state
        if self.pooling == "mean":
            mask = attention_mask.unsqueeze(-1)
            output = (output * mask).sum(1) / mask.sum(1).clamp(min=1)
        else:
            output = output[:, 0]
        return torch.nn.functional.normalize(output, dim=-1)


def raw_outputs(x, heads, config):
    x = unit(x)
    similarity = x @ unit(heads["prototypes"]).T
    return {"category_logits": similarity * config["category_scale"],
            "channel_logits": x @ heads["channel_weight"].T + heads["channel_bias"],
            "tag_logits": x @ heads["tag_weight"].T + heads["tag_bias"],
            "novelty": np.clip(1 - similarity.max(1), 0, 1)}


def encode_unique(encoder, texts):
    unique = list(dict.fromkeys(texts))
    index = {text: i for i, text in enumerate(unique)}
    values = encoder(unique)
    return values[[index[t] for t in texts]]


def benchmark(encoder, texts, repeats=5):
    unique = list(dict.fromkeys(texts))
    if len(unique) < 256:
        raise ValueError("benchmark needs 256 distinct normalized operation texts")
    sample = unique[:256]
    encoder(sample)  # warmup; no request dedup can reduce this batch
    times = []
    for _ in range(repeats):
        start = time.perf_counter(); encoder(sample); times.append(time.perf_counter() - start)
    return {"batch_size": 256, "distinct_normalized_inputs": 256, "repeats": repeats,
            "median_s": float(np.median(times)), "p95_s": float(np.quantile(times, .95)),
            "max_s": max(times), "times_s": times, "includes": "tokenization + CPU encoder; no cross-request cache"}


def export(selected: Path, out: Path, prepared: Path, quantize=True, fit_source: Path | None = None):
    if out.exists():
        raise ValueError("out already exists; never overwrite a candidate")
    shutil.copytree(selected, out, ignore=shutil.ignore_patterns("calibration_raw.npz"))
    config = json.loads((out / "config.json").read_text())
    archived = selected / "fit_source"
    archive_fitting_sources(config, fit_source or (archived if archived.is_dir() else Path(__file__).resolve().parents[2]), out)
    taxonomy = Taxonomy.load(out / "taxonomy.json")
    rows = [r for r in read_rows(prepared / "calibration.jsonl") if r["label"] in taxonomy.categories]
    texts = [config.get("text_prefix", "") + r["text"] for r in rows]
    # Purged clean calibration can have fewer than256 deduplicated views.
    # CPU timing may use other genuine inputs from the SAME known calibration
    # companies; temperatures/heads still use only the clean selected views.
    timing_rows = [r for r in read_rows(prepared / "calibration_full.jsonl") if r["label"] in taxonomy.categories] if (prepared / "calibration_full.jsonl").exists() else rows
    timing_texts = [config.get("text_prefix", "") + r["text"] for r in timing_rows]
    y, h, t = targets(rows, taxonomy)
    with np.load(out / "heads.npz", allow_pickle=False) as f:
        heads = dict(f)
    torch_encoder = TorchEncoder(out, config)
    wrapper = EmbeddingExport(torch_encoder.model, config.get("pooling", "cls")).eval()
    sample = torch_encoder.tokenizer(texts[:2], padding=True, truncation=True,
                                    max_length=config["max_length"], return_tensors="pt")
    ids = sample["input_ids"]
    mask = sample["attention_mask"]
    types = sample.get("token_type_ids", torch.zeros_like(ids))
    names = ["input_ids", "attention_mask", "token_type_ids"]
    torch.onnx.export(wrapper, (ids, mask, types), str(out / "encoder-fp32.onnx"),
                      input_names=names, output_names=["embedding"], opset_version=17, dynamo=False,
                      dynamic_axes={**{k: {0: "batch", 1: "sequence"} for k in names}, "embedding": {0: "batch"}})
    variants = {"torch-fp32": ("torch", None), "onnx-fp32": ("onnx", "encoder-fp32.onnx")}
    if quantize:
        from onnxruntime.quantization import quantize_dynamic, QuantType
        quantize_dynamic(str(out / "encoder-fp32.onnx"), str(out / "encoder-int8.onnx"),
                         weight_type=QuantType.QInt8, per_channel=True,
                         op_types_to_quantize=["MatMul", "Gemm"])
        variants["onnx-int8"] = ("onnx", "encoder-int8.onnx")
    report = {"scope": "calibration companies only; no final evaluation viewed", "variants": {}}
    baseline_prediction = None
    all_x = {}
    for name, (backend, filename) in variants.items():
        cfg = dict(config, runtime=backend, onnx_file=filename)
        encoder = torch_encoder if backend == "torch" else OnnxEncoder(out, cfg)
        x = encode_unique(encoder, texts)
        all_x[name] = x
        raw = raw_outputs(x, heads, cfg)
        calibration = calibrate(raw, y, h, t, categories=taxonomy.categories)
        prediction = raw["category_logits"].argmax(1)
        if baseline_prediction is None:
            baseline_prediction = prediction
        result = {"calibration": calibration, "category_disagreements_vs_torch": int((prediction != baseline_prediction).sum()),
                  "embedding_max_abs_error_vs_torch": float(np.abs(x - all_x["torch-fp32"]).max()),
                  "latency": benchmark(encoder, timing_texts)}
        report["variants"][name] = result
        print(name, json.dumps(result), flush=True)
    base = report["variants"]["torch-fp32"]["calibration"]
    eligible = []
    for name, result in report["variants"].items():
        q = result["calibration"]
        accepted = (q["category"]["accuracy"] >= base["category"]["accuracy"] - .0005
                    and q["category"]["macro_f1"] >= base["category"]["macro_f1"] - .001
                    and q["channel"]["accuracy"] >= base["channel"]["accuracy"] - .002
                    and q["tags"]["micro_f1"] >= base["tags"]["micro_f1"] - .002)
        result["quality_parity_accepted"] = accepted
        if accepted:
            eligible.append(name)
    chosen = min(eligible, key=lambda name: report["variants"][name]["latency"]["median_s"])
    report["selected_runtime"] = chosen
    config.update(runtime=variants[chosen][0], onnx_file=variants[chosen][1])
    for key in ("category_temperature", "channel_temperature", "tag_thresholds", "novelty_threshold", "novelty_reference"):
        config[key] = report["variants"][chosen]["calibration"][key]
    config["runtime_selection"] = {"data": "calibration_only", "selected": chosen,
                                   "category_max_accuracy_drop": .0005, "category_max_f1_drop": .001,
                                   "channel_max_accuracy_drop": .002, "tag_max_micro_f1_drop": .002}
    (out / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    (out / "runtime_comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "calibration.json").write_text(json.dumps(report["variants"][chosen]["calibration"], indent=2) + "\n")
    np.savez_compressed(out.parent / (out.name + "_calibration_embeddings.npz"), embedding=all_x[chosen], category_y=y,
                        channel_y=h, tag_y=t)
    version = seal(out)
    loaded = EncoderClassifier.load(out)
    assert loaded.model_version == version
    print("sealed", version, flush=True)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selected", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--prepared", type=Path, required=True)
    ap.add_argument("--no-int8", action="store_true")
    ap.add_argument("--fit-source", type=Path, help="frozen fitting ML source root if the code changed after training")
    args = ap.parse_args()
    export(args.selected, args.out, args.prepared, not args.no_int8, args.fit_source)


if __name__ == "__main__":
    main()
