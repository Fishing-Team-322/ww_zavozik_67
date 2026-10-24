import json
from pathlib import Path

from zavozik_ml.classify_v2.fetch_base import fetch


def test_pinned_cached_download_has_stable_nonrecursive_source_manifest(tmp_path, monkeypatch):
    revision = "a" * 40
    calls = []

    def curl(arguments, check):
        assert check is True
        calls.append(arguments)
        out = Path(arguments[arguments.index("-o") + 1])
        if "/api/models/" in arguments[-3]:
            out.write_text(json.dumps(dict(sha=revision, cardData=dict(license="mit"),
                                           siblings=[dict(rfilename=x) for x in ("model.safetensors", "config.json")])))
        else:
            out.write_bytes(b"public pretrained fixture")

    monkeypatch.setattr("zavozik_ml.classify_v2.fetch_base.subprocess.run", curl)
    path = fetch("cointegrated/rubert-tiny2", tmp_path, revision)
    first = (path / "base_source.json").read_bytes()
    (path / "tokenizer.json.partial").write_text("incomplete download is not a base file")
    assert fetch("cointegrated/rubert-tiny2", tmp_path, revision) == path
    assert (path / "base_source.json").read_bytes() == first
    assert len(calls) == 4  # two metadata reads, each base file downloaded once
    assert "base_source.json" not in json.loads(first)["files_sha256"]
