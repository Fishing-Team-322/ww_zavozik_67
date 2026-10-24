"""Artifact identity and immutable local publication (large weights excluded)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from .model import sha256_file


def seal(directory: Path) -> str:
    """Seal an unpublished candidate. README/report text is not model identity."""
    directory = Path(directory)
    config_path = directory / "config.json"
    config = json.loads(config_path.read_text())
    config.pop("model_version", None)
    identity = hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode())
    excluded = {directory / name for name in ("config.json", "manifest.json", "README.md", "calibration_raw.npz")}
    payload = [p for p in sorted(directory.rglob("*")) if p.is_file()
               and p not in excluded
               and p.suffix not in (".log",)]
    for path in payload:
        identity.update(str(path.relative_to(directory)).encode())
        identity.update(sha256_file(path).encode())
    version = "encoder-v1-" + identity.hexdigest()[:16]
    config["model_version"] = version
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    files = {str(p.relative_to(directory)): sha256_file(p) for p in sorted(directory.rglob("*"))
             if p.is_file() and p.name not in ("manifest.json", "README.md", "calibration_raw.npz")}
    manifest = {"model_version": version, "files_sha256": files,
                "files_bytes": {name: (directory / name).stat().st_size for name in files},
                "base_model": config["base_source"]["model_id"], "base_revision": config["base_source"]["revision"]}
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return version


def publish(candidate: Path, model_root: Path) -> Path:
    """Copy a completely evaluated candidate to its final immutable directory."""
    candidate, model_root = Path(candidate), Path(model_root)
    if not (candidate / "README.md").is_file():
        raise ValueError("model card required before publication")
    version = json.loads((candidate / "config.json").read_text())["model_version"]
    if not version.startswith("encoder-v1-"):
        raise ValueError("invalid model version")
    destination = model_root / version
    if destination.exists():
        raise ValueError("published model already exists; do not overwrite")
    model_root.mkdir(parents=True, exist_ok=True)
    temporary = model_root / ("." + version + ".partial")
    if temporary.exists():
        raise ValueError("partial publication exists; inspect it before retrying")
    shutil.copytree(candidate, temporary, ignore=shutil.ignore_patterns("calibration_raw.npz"))
    temporary.rename(destination)
    return destination
