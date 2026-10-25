"""Pinned larger local teacher candidate; it is not an approved label oracle.

Separate payload/provenance from the old4B experiment. Download only explicit
data/templates/safetensors, verify Hub LFS digests and shard index, never code.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from zavozik_ml.classify_v2.model import sha256_file
from .candidate_models import curl

MODEL="mlx-community/Qwen3.5-9B-4bit"
REVISION="8b2b98c00a6b4d291155e4890773ca8f769aee53"
SHARDS=frozenset(("model-00001-of-00002.safetensors","model-00002-of-00002.safetensors"))
FILES=SHARDS | frozenset(("README.md","config.json","chat_template.jinja","model.safetensors.index.json",
                         "tokenizer.json","tokenizer_config.json","vocab.json"))


def verify(base):
    meta=json.loads((base/"research_teacher_source.json").read_text())
    if (meta.get("model_id")!=MODEL or meta.get("revision")!=REVISION or
            meta.get("license")!="apache-2.0" or set(meta.get("files_sha256",{}))!=FILES):
        raise ValueError("larger teacher identity/payload mismatch")
    for name,digest in meta["files_sha256"].items():
        if sha256_file(base/name)!=digest:
            raise ValueError("larger teacher payload hash mismatch: "+name)
    index=json.loads((base/"model.safetensors.index.json").read_text())
    if set(index["weight_map"].values())!=SHARDS:
        raise ValueError("unexpected teacher shard index")
    config=json.loads((base/"config.json").read_text())
    if config["model_type"]!="qwen3_5" or config["quantization"]["bits"]!=4:
        raise ValueError("unexpected teacher architecture/precision")
    return meta


def fetch(out):
    base=out/REVISION
    if (base/"research_teacher_source.json").exists():
        return verify(base)
    base.mkdir(parents=True,exist_ok=True)
    metadata_path=out/(REVISION+".hub_metadata.json")
    curl(f"https://huggingface.co/api/models/{MODEL}/revision/{REVISION}?blobs=true",metadata_path,120)
    metadata=json.loads(metadata_path.read_text());card=metadata.get("cardData",{})
    if (metadata["sha"]!=REVISION or card.get("license")!="apache-2.0" or
            card.get("base_model")!=["Qwen/Qwen3.5-9B-Base"]):
        raise ValueError("larger teacher Hub revision/license/lineage mismatch")
    available={r["rfilename"]:r for r in metadata["siblings"]}
    if not FILES <= available.keys():
        raise ValueError("larger teacher missing required data files")
    hashes={}
    for name in sorted(FILES):
        target=base/name;expected=available[name].get("lfs",{}).get("sha256")
        if name in SHARDS and not expected:
            raise ValueError("missing large teacher LFS digest")
        if not target.exists():
            print("research teacher download",name,flush=True)
            partial=target.with_name(name+".partial")
            curl(f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}",partial,resume=name in SHARDS)
            if expected and sha256_file(partial)!=expected:
                raise ValueError("larger teacher LFS digest mismatch: "+name)
            partial.rename(target)
        hashes[name]=sha256_file(target)
        if expected and hashes[name]!=expected:
            raise ValueError("larger teacher saved LFS digest mismatch: "+name)
    meta=dict(model_id=MODEL,revision=REVISION,license="apache-2.0",
        conversion_source="Qwen/Qwen3.5-9B",hub_base_model=card["base_model"],
        files_sha256=hashes,hub_metadata_sha256=sha256_file(metadata_path),
        status="candidate_teacher_unvalidated",label_provenance="local_model_weak_not_human_gold")
    (base/"research_teacher_source.json").write_text(json.dumps(meta,indent=2)+"\n")
    verify(base)
    print("research teacher payload ready",base,flush=True)
    return meta


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args();fetch(a.out)


if __name__=="__main__":
    main()
