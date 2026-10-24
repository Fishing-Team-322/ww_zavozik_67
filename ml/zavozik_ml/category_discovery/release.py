"""Immutable self-contained local release; neural payloads stay outside Git."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from zavozik_ml.classify_v2.model import sha256_file
from .core import CategoryInventory
from .hierarchy import CategoryHierarchy
from .corpus import TEXT_VERSION


def verify(directory: Path):
    meta = json.loads((directory / "release.json").read_text())
    names = set(meta["files_sha256"])
    actual = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file() and p != directory / "release.json"}
    if names != actual:
        raise ValueError("incomplete or unexpected release payload")
    for name, digest in meta["files_sha256"].items():
        path = directory / name
        if Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink() or sha256_file(path) != digest:
            raise ValueError("release payload checksum mismatch")
    inv = CategoryInventory.load(directory / "inventory")
    tree = CategoryHierarchy.load(directory / "hierarchy.json", inv)
    if inv.version != meta["taxonomy_version"] or tree.version != meta["hierarchy_version"] or inv.encoder_version != meta["encoder_version"]:
        raise ValueError("release semantic versions mismatch")
    return meta


def publish(experiment: Path, hierarchy: Path, base: Path, model_root: Path, card: Path):
    inv = CategoryInventory.load(experiment / "inventory")
    tree = CategoryHierarchy.load(hierarchy, inv)
    identity = hashlib.sha256((inv.encoder_version + inv.version + tree.version).encode()).hexdigest()[:20]
    destination = model_root / ("discovery-v1-" + identity)
    if destination.exists():
        raise ValueError("release exists; never overwrite immutable models")
    model_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".discovery-staging-", dir=model_root))
    try:
        shutil.copytree(experiment / "inventory", stage / "inventory")
        shutil.copytree(experiment / "fit_source", stage / "fit_source", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(base, stage / "encoder")
        shutil.copy2(hierarchy, stage / "hierarchy.json")
        shutil.copy2(experiment / "protocol.json", stage / "protocol.json")
        shutil.copy2(card, stage / "README.md")
        (stage / "hierarchy_source").mkdir()
        shutil.copy2(Path(__file__).with_name("hierarchy.py"), stage / "hierarchy_source/hierarchy.py")
        source = json.loads((stage / "encoder/base_source.json").read_text())
        if source["model_id"] != "intfloat/multilingual-e5-small" or inv.encoder_version != f"e5-small-{source['revision']}-mean128-{TEXT_VERSION}":
            raise ValueError("encoder source and fitted inventory differ")
        for name, digest in source["files_sha256"].items():
            if sha256_file(stage / "encoder" / name) != digest:
                raise ValueError("encoder base payload changed")
        meta = dict(format_version=1, model_version=destination.name, encoder_version=inv.encoder_version,
                    taxonomy_version=inv.version, hierarchy_version=tree.version,
                    status="research_semantic_quality_not_independently_verified",
                    files_sha256={str(p.relative_to(stage)): sha256_file(p) for p in sorted(stage.rglob("*")) if p.is_file()})
        (stage / "release.json").write_text(json.dumps(meta, indent=2) + "\n")
        verify(stage)
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return destination


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--experiment", type=Path, required=True)
    p.add_argument("--hierarchy", type=Path, required=True)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--model-root", type=Path, required=True)
    p.add_argument("--card", type=Path, required=True)
    a = p.parse_args()
    print(publish(a.experiment, a.hierarchy, a.base, a.model_root, a.card).resolve())


if __name__ == "__main__":
    main()
