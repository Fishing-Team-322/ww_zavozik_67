"""Download a pinned local 4-bit teacher; generated labels will remain WEAK.

Only data/tokenizer templates/safetensors, no pickle or downloaded Python.
MLX is optional in an isolated research environment, never a server dependency.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from zavozik_ml.classify_v2.model import sha256_file
from .candidate_models import curl

MODEL = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
REVISION = "50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b"
FILES = frozenset(("README.md", "config.json", "generation_config.json", "model.safetensors", "model.safetensors.index.json",
                   "added_tokens.json", "chat_template.jinja", "merges.txt", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.json"))


def verify(base):
    meta = json.loads((base / "teacher_source.json").read_text())
    if (meta["model_id"] != MODEL or meta["revision"] != REVISION or meta["license"] != "apache-2.0" or
            not {"config.json", "model.safetensors", "tokenizer.json"} <= meta["files_sha256"].keys()):
        raise ValueError("teacher identity/payload mismatch")
    for name, expected in meta["files_sha256"].items():
        if name not in FILES or sha256_file(base / name) != expected:
            raise ValueError(f"teacher payload hash/path mismatch: {name}")
    return meta


def fetch(out):
    base = out / REVISION
    if (base / "teacher_source.json").exists():
        return verify(base)
    base.mkdir(parents=True, exist_ok=True)
    path = out / "hub_metadata.json"
    curl(f"https://huggingface.co/api/models/{MODEL}/revision/{REVISION}?blobs=true", path, 120)
    metadata = json.loads(path.read_text())
    card = metadata.get("cardData", {})
    if metadata["sha"] != REVISION or card.get("license") != "apache-2.0" or card.get("base_model") != "Qwen/Qwen3-4B-Instruct-2507":
        raise ValueError("teacher remote provenance mismatch")
    available = {r["rfilename"]: r for r in metadata["siblings"]}
    hashes = {}
    for name in sorted(FILES & available.keys()):
        target = base / name
        if not target.exists():
            print(f"teacher download {name}", flush=True)
            partial = target.with_name(name + ".partial")
            curl(f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}", partial, resume=name.endswith(".safetensors"))
            partial.rename(target)
        hashes[name] = sha256_file(target)
        expected = available[name].get("lfs", {}).get("sha256")
        if expected and hashes[name] != expected:
            raise ValueError(f"teacher LFS digest mismatch: {name}")
    meta = dict(model_id=MODEL, revision=REVISION, license="apache-2.0", base_model=card["base_model"],
                label_provenance="local_model_weak_not_human_gold", files_sha256=hashes)
    (base / "teacher_source.json").write_text(json.dumps(meta, indent=2) + "\n")
    verify(base)
    print(f"teacher ready {base}", flush=True)
    return meta


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(fetch(a.out), indent=2))


if __name__ == "__main__":
    main()
