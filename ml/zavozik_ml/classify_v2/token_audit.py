"""Audit effective truncated tokenizer inputs before fitting any encoder."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from .data import read_rows
from .model import sha256_file


def run(prepared: Path, bases: list[Path], prefixes: list[str], max_length: int = 128) -> dict:
    from tokenizers import Tokenizer
    if len(bases) != len(prefixes) or not bases:
        raise ValueError("one explicit prefix required per tokenizer")
    manifest = json.loads((prepared / "data_manifest.json").read_text())
    rows = {}
    for name in ("train", "calibration", "test"):
        if sha256_file(prepared / (name + ".jsonl")) != manifest[name]["sha256"]:
            raise ValueError("prepared data changed")
        rows[name] = read_rows(prepared / (name + ".jsonl"))
    result = {"scope": "Input-only pre-fit audit, no model predictions", "max_length": max_length,
              "data_manifest_sha256": sha256_file(prepared / "data_manifest.json"), "models": {}}
    for base, prefix in zip(bases, prefixes):
        source = json.loads((base / "base_source.json").read_text())
        tokenizer = Tokenizer.from_file(str(base / "tokenizer.json"))
        tokenizer.no_padding()
        tokenizer.enable_truncation(max_length=max_length)
        sets = {}
        for name, records in rows.items():
            texts = sorted({prefix + r["text"] for r in records})
            values = set()
            for start in range(0, len(texts), 512):
                for encoded in tokenizer.encode_batch(texts[start:start+512]):
                    values.add(hashlib.sha256(struct.pack("!" + "i" * len(encoded.ids), *encoded.ids)).hexdigest())
            sets[name] = values
        pairs = {a + "__" + b: len(sets[a] & sets[b]) for a, b in
                 (("train", "calibration"), ("train", "test"), ("calibration", "test"))}
        result["models"][source["model_id"]] = {"base_revision": source["revision"], "text_prefix": prefix,
            "tokenizer_sha256": sha256_file(base / "tokenizer.json"), "pairwise_token_input_intersections": pairs,
            "unique_token_inputs": {name: len(s) for name, s in sets.items()}}
    result["passed"] = not any(v for m in result["models"].values() for v in m["pairwise_token_input_intersections"].values())
    return result


def validate(prepared: Path, base: Path, prefix: str, max_length: int) -> None:
    report = json.loads((prepared / "token_input_audit.json").read_text())
    source = json.loads((base / "base_source.json").read_text())
    model = report.get("models", {}).get(source["model_id"], {})
    if (not report.get("passed") or report.get("max_length") != max_length
            or report.get("data_manifest_sha256") != sha256_file(prepared / "data_manifest.json")
            or model.get("tokenizer_sha256") != sha256_file(base / "tokenizer.json")
            or model.get("base_revision") != source["revision"] or model.get("text_prefix") != prefix
            or not model.get("pairwise_token_input_intersections")
            or any(model["pairwise_token_input_intersections"].values())):
        raise ValueError("missing, stale or failed effective-token split audit")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--base", type=Path, action="append", required=True)
    p.add_argument("--prefix", action="append", required=True)
    p.add_argument("--max-length", type=int, default=128)
    args = p.parse_args()
    out = args.prepared / "token_input_audit.json"
    if out.exists():
        p.error("audit exists; do not overwrite a frozen validation")
    result = run(args.prepared, args.base, args.prefix, args.max_length)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    if not result["passed"]:
        raise SystemExit("Token input overlap: fitting forbidden")


if __name__ == "__main__":
    main()
