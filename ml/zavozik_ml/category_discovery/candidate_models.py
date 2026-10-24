"""Pinned offline discovery candidates; model-specific inputs and pooling.

Research adapters, not a migration of the production 384-dimensional contract.
Only public model files are downloaded. Operation texts never leave this host.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import time

import numpy as np

from zavozik_ml.classify_v2.model import sha256_file, unit
from .normalization import TEXT_VERSION


@dataclass(frozen=True)
class Candidate:
    model_id: str
    revision: str
    license: str
    pooling: str
    dimension: int
    max_length: int
    prefix: str

    def inputs(self, texts):
        return [self.prefix + t for t in texts]


MODELS = {
    "e5-small": Candidate("intfloat/multilingual-e5-small", "614241f622f53c4eeff9890bdc4f31cfecc418b3", "mit", "mean", 384, 128, "query: "),
    "e5-base": Candidate("intfloat/multilingual-e5-base", "d128750597153bb5987e10b1c3493a34e5a4502a", "mit", "mean", 768, 128, "query: "),
    "qwen3-embedding-0.6b": Candidate("Qwen/Qwen3-Embedding-0.6B", "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3", "apache-2.0", "last", 1024, 256,
        "Instruct: Represent the economic purpose of this bank payment. Preserve the object, financial roles, and negation; do not infer missing facts.\nQuery: "),
}
FILES = frozenset(("README.md", "LICENSE", "config.json", "model.safetensors", "tokenizer.json",
                   "tokenizer_config.json", "special_tokens_map.json", "sentencepiece.bpe.model", "merges.txt", "vocab.json"))


def verify_base(base: Path, spec: Candidate, *, weights=True):
    manifest = base / "base_source.json"
    if not weights and not manifest.exists():
        manifest = base / "tokenizer_source.json"
    source = json.loads(manifest.read_text())
    if any(source.get(k) != getattr(spec, k) for k in ("model_id", "revision", "license")):
        raise ValueError("base identity mismatch")
    required = {"config.json", "tokenizer.json"} | ({"model.safetensors"} if weights else set())
    if not required <= source["files_sha256"].keys():
        raise ValueError("base missing required files")
    for name, expected in source["files_sha256"].items():
        if name not in FILES or sha256_file(base / name) != expected:
            raise ValueError(f"base hash/path mismatch: {name}")
    return source


def curl(url, target, timeout=1800, *, resume=False):
    # A CDN connection reset (curl 56) is not retried by curl's default retry
    # policy. Re-invoke with the CURRENT partial length; final LFS hash remains
    # mandatory. Never discard a large successful prefix on a transient reset.
    for attempt in range(8 if resume else 1):
        command = ["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "4",
                   "--connect-timeout", "20", "--max-time", str(timeout)]
        if resume:
            command.extend(["--continue-at", "-"])
        result = subprocess.run(command + [url, "-o", str(target)], check=False)
        if result.returncode == 0:
            return
        if not resume or result.returncode not in (18, 28, 35, 52, 55, 56, 92) or attempt == 7:
            raise subprocess.CalledProcessError(result.returncode, command)
        print(f"transient download failure {result.returncode}; resume {target.name}, attempt {attempt+2}", flush=True)
        time.sleep(min(2**attempt, 30))


def fetch(name: str, root: Path, *, weights=True):
    spec = MODELS[name]
    base = root / name / spec.revision
    manifest = base / ("base_source.json" if weights else "tokenizer_source.json")
    if manifest.exists():
        verify_base(base, spec, weights=weights)
        return base
    base.mkdir(parents=True, exist_ok=True)
    metadata_file = base.parent / (spec.revision + ".hub_metadata.json")
    curl(f"https://huggingface.co/api/models/{spec.model_id}/revision/{spec.revision}?blobs=true", metadata_file, 120)
    meta = json.loads(metadata_file.read_text())
    if meta["sha"] != spec.revision or meta.get("cardData", {}).get("license") != spec.license:
        raise ValueError("remote revision/license mismatch")
    available = {item["rfilename"]: item for item in meta["siblings"]}
    if not {"config.json", "model.safetensors", "tokenizer.json"} <= available.keys():
        raise ValueError("required safetensors/tokenizer payload absent")
    hashes = {}
    wanted = FILES if weights else FILES - {"model.safetensors"}
    for filename in sorted(wanted & available.keys()):
        target = base / filename
        if not target.exists():
            print(f"download {name}@{spec.revision[:12]} / {filename}", flush=True)
            partial = target.with_name(filename + ".partial")
            curl(f"https://huggingface.co/{spec.model_id}/resolve/{spec.revision}/{filename}", partial,
                 resume=filename == "model.safetensors")
            partial.rename(target)
        hashes[filename] = sha256_file(target)
        expected = available[filename].get("lfs", {}).get("sha256")
        if expected and hashes[filename] != expected:
            raise ValueError(f"Hub LFS digest mismatch: {filename}")
    source = dict(model_id=spec.model_id, revision=spec.revision, license=spec.license, files_sha256=hashes)
    manifest.write_text(json.dumps(source, indent=2) + "\n")
    verify_base(base, spec, weights=weights)
    print(f"ready {base}", flush=True)
    return base


def tokenizer_for(name, base):
    from transformers import AutoTokenizer
    spec = MODELS[name]
    source = verify_base(base, spec, weights=False)
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True, trust_remote_code=False,
                                            padding_side="left" if spec.pooling == "last" else "right")
    def tokenize(query_texts):
        texts = [t.removeprefix("query: ") for t in query_texts]
        return tokenizer(spec.inputs(texts), truncation=True, max_length=spec.max_length)["input_ids"]
    return tokenize, dict(source, recipe=asdict(spec), text_version=TEXT_VERSION)


class CandidateEncoder:
    def __init__(self, name, base: Path, device="cpu", batch_size=8, threads=4):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.spec = MODELS[name]
        self.source = verify_base(base, self.spec)
        torch.set_num_threads(threads)
        self.torch, self.device, self.batch_size = torch, device, batch_size
        self.model = AutoModel.from_pretrained(base, local_files_only=True, trust_remote_code=False,
                                               attn_implementation="eager").eval().to(device)
        self.tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True, trust_remote_code=False,
            padding_side="left" if self.spec.pooling == "last" else "right")
        if self.model.config.hidden_size != self.spec.dimension:
            raise ValueError("unexpected embedding dimension")

    def __call__(self, semantic_texts):
        if not semantic_texts:
            return np.empty((0, self.spec.dimension), np.float32)
        parts = []
        for start in range(0, len(semantic_texts), self.batch_size):
            tokens = self.tokenizer(self.spec.inputs(semantic_texts[start:start+self.batch_size]),
                padding=True, truncation=True, max_length=self.spec.max_length, return_tensors="pt").to(self.device)
            with self.torch.inference_mode():
                h = self.model(**tokens).last_hidden_state
                mask = tokens["attention_mask"]
                if self.spec.pooling == "mean":
                    x = (h * mask.unsqueeze(-1)).sum(1) / mask.sum(1).unsqueeze(-1).clamp(min=1)
                else:
                    # Last *non-padding* token works with either padding side.
                    indices = (mask * self.torch.arange(mask.shape[1], device=mask.device)).max(1).values
                    x = h[self.torch.arange(len(h), device=h.device), indices]
                parts.append(x.float().cpu().numpy())
            if self.device == "mps":
                self.torch.mps.synchronize()
                self.torch.mps.empty_cache()
        return unit(np.concatenate(parts))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", choices=tuple(MODELS) + ("all",), required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--tokenizers-only", action="store_true")
    a = p.parse_args()
    for name in MODELS if a.model == "all" else (a.model,):
        print(fetch(name, a.root, weights=not a.tokenizers_only), flush=True)


if __name__ == "__main__":
    main()
