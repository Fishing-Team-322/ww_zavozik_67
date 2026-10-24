"""Fingerprint code and bundled calendar independently of Git/install location."""

import hashlib
from pathlib import Path


def source_fingerprint() -> str:
    root = Path(__file__).parent
    digest = hashlib.sha256()
    files = sorted([*root.rglob("*.py"), *root.glob("calendar_data/*.json")])
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
