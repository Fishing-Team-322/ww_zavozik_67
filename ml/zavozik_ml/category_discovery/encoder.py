"""Pinned local E5 encoder, no category heads or fine-tuning."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np

from zavozik_ml.classify_v2.model import sha256_file, unit
from .corpus import read_rows, PROTOCOL, TEXT_VERSION


class SemanticEncoder:
    def __init__(self, base: Path, device="cpu", batch_size=32, threads=4):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        torch.set_num_threads(threads)
        self.source = json.loads((base / "base_source.json").read_text())
        if self.source["model_id"] != "intfloat/multilingual-e5-small":
            raise ValueError("unsupported semantic encoder")
        for name, digest in self.source["files_sha256"].items():
            if sha256_file(base / name) != digest:
                raise ValueError(f"base payload digest mismatch: {name}")
        self.model = AutoModel.from_pretrained(base, local_files_only=True, trust_remote_code=False,
                                               attn_implementation="eager").eval().to(device)
        self.tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True, trust_remote_code=False)
        self.device, self.batch_size = device, batch_size
        self.version = "e5-small-" + self.source["revision"] + "-mean128-" + TEXT_VERSION
        self.dim = self.model.config.hidden_size

    def __call__(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), np.float32)
        results = []
        for start in range(0, len(texts), self.batch_size):
            t = self.tokenizer(texts[start:start+self.batch_size], padding="max_length" if self.device == "mps" else True,
                               truncation=True, max_length=128, return_tensors="pt").to(self.device)
            with self.torch.inference_mode():
                h = self.model(**t).last_hidden_state
                mask = t["attention_mask"].unsqueeze(-1)
                x = (h * mask).sum(1) / mask.sum(1).clamp(min=1)
                results.append(x.cpu().numpy())
            if self.device == "mps":
                self.torch.mps.synchronize()
                self.torch.mps.empty_cache()
        return unit(np.concatenate(results))


def embed_corpus(corpus: Path, base: Path, out: Path, device="cpu") -> dict:
    if out.exists():
        raise ValueError("embedding output exists")
    manifest = json.loads((corpus / "manifest.json").read_text())
    if manifest["protocol"] != PROTOCOL:
        raise ValueError("unsupported corpus protocol")
    encoder = SemanticEncoder(base, device)
    rows, token_sets = {}, {}
    for p in ("train", "calibration", "test"):
        path = corpus / f"{p}_unique.jsonl"
        if sha256_file(path) != manifest[p]["unique_sha256"]:
            raise ValueError("corpus changed")
        rows[p] = read_rows(path)
        ids = encoder.tokenizer([r["text"] for r in rows[p]], truncation=True, max_length=128)["input_ids"]
        token_sets[p] = {tuple(v) for v in ids}
    overlaps = {f"{a}__{b}": len(token_sets[a] & token_sets[b])
                for a, b in (("train", "calibration"), ("train", "test"), ("calibration", "test"))}
    if any(overlaps.values()):
        raise ValueError(f"actual token input overlap: {overlaps}")
    out.mkdir(parents=True)
    report = dict(encoder_version=encoder.version, embedding_dim=encoder.dim, base=encoder.source,
                  corpus_manifest_sha256=sha256_file(corpus / "manifest.json"), device=device,
                  token_input_intersections=overlaps, fine_tuning=False,
                  code_sha256=sha256_file(Path(__file__)))
    for p in ("train", "calibration", "test"):
        started = time.perf_counter()
        x = encoder([r["text"] for r in rows[p]])
        np.save(out / f"{p}.npy", x, allow_pickle=False)
        report[p] = dict(rows=len(x), sha256=sha256_file(out / f"{p}.npy"), seconds=time.perf_counter()-started)
        print(f"embedded {p}: {len(x)} rows, {report[p]['seconds']:.1f}s", flush=True)
    (out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    a = p.parse_args()
    print(json.dumps(embed_corpus(a.corpus, a.base, a.out, a.device), indent=2))


if __name__ == "__main__":
    main()
