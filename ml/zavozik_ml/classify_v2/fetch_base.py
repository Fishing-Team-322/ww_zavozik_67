"""Download public pretrained weights only, pinned by immutable HF revision.

No operation text is sent. curl is used for TLS compatibility with the local
training runtime; certificate verification stays enabled. Loading is offline.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

from .model import sha256_file

BASE_MODELS = ("cointegrated/rubert-tiny2", "intfloat/multilingual-e5-small")
FILES = {"config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
         "special_tokens_map.json", "vocab.txt", "sentencepiece.bpe.model", "README.md", "LICENSE"}


def fetch(model_id: str, out: Path, revision: str | None = None) -> Path:
    if model_id not in BASE_MODELS:
        raise ValueError("unsupported base model")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    api_file = out / "hub_metadata.json"
    api_url = f"https://huggingface.co/api/models/{model_id}" + (f"/revision/{revision}" if revision else "")
    subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "4",
                    "--connect-timeout", "20", "--max-time", "120", api_url, "-o", str(api_file)], check=True)
    metadata = json.loads(api_file.read_text())
    revision = metadata["sha"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("invalid model revision")
    local = out / revision
    local.mkdir(exist_ok=True)
    available = {item["rfilename"] for item in metadata["siblings"]}
    if "model.safetensors" not in available:
        raise ValueError("safetensors weights are required; no pickle loading")
    for name in sorted(FILES & available):
        path = local / name
        if path.is_file() and path.stat().st_size:
            continue
        print(f"download {model_id}@{revision[:12]} / {name}", flush=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "5",
                        "--connect-timeout", "30", "--max-time", "1800",
                        f"https://huggingface.co/{model_id}/resolve/{revision}/{name}", "-o", str(temporary)], check=True)
        temporary.replace(path)
    source = {"model_id": model_id, "revision": revision,
              "license": metadata.get("cardData", {}).get("license"),
              "files_sha256": {p.name: sha256_file(p) for p in sorted(local.iterdir()) if p.is_file()}}
    (local / "base_source.json").write_text(json.dumps(source, indent=2) + "\n")
    print(local, flush=True)
    return local


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=BASE_MODELS, default=BASE_MODELS[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--revision")
    args = parser.parse_args()
    fetch(args.model, args.out, args.revision)


if __name__ == "__main__":
    main()
