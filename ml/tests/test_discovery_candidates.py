import json
import subprocess

import pytest

from zavozik_ml.category_discovery.candidate_models import MODELS, curl, verify_base
from zavozik_ml.classify_v2.model import sha256_file


def test_candidates_have_distinct_explicit_dimensions_and_correct_input_recipes():
    assert MODELS["e5-small"].dimension == 384
    assert MODELS["e5-base"].dimension == 768
    assert MODELS["qwen3-embedding-0.6b"].dimension == 1024
    assert MODELS["e5-base"].inputs(["цель"])[0] == "query: цель"
    qwen = MODELS["qwen3-embedding-0.6b"]
    assert qwen.pooling == "last" and qwen.inputs(["цель"])[0].endswith("\nQuery: цель")


def test_only_tokenizer_manifest_never_authorizes_a_model_load(tmp_path):
    spec = MODELS["e5-base"]
    files = {}
    for name in ("config.json", "tokenizer.json"):
        (tmp_path / name).write_text("fixture")
        files[name] = sha256_file(tmp_path / name)
    meta = dict(model_id=spec.model_id, revision=spec.revision, license=spec.license, files_sha256=files)
    (tmp_path / "tokenizer_source.json").write_text(json.dumps(meta))
    assert verify_base(tmp_path, spec, weights=False) == meta
    with pytest.raises(FileNotFoundError):
        verify_base(tmp_path, spec)
    (tmp_path / "base_source.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="required files"):
        verify_base(tmp_path, spec)
    (tmp_path / "tokenizer.json").write_text("tampered")
    with pytest.raises(ValueError, match="hash/path mismatch"):
        verify_base(tmp_path, spec, weights=False)


def test_transient_cdn_reset_resumes_without_discarding_prefix(monkeypatch, tmp_path):
    from zavozik_ml.category_discovery import candidate_models
    target = tmp_path / "model.partial"
    target.write_bytes(b"valid prefix")
    calls = []
    def run(command, check):
        calls.append(command)
        assert target.read_bytes().startswith(b"valid prefix")
        with target.open("ab") as f:
            f.write(b" more bytes")
        return subprocess.CompletedProcess(command, 56 if len(calls) == 1 else 0)
    monkeypatch.setattr(candidate_models.subprocess, "run", run)
    monkeypatch.setattr(candidate_models.time, "sleep", lambda _: None)
    curl("https://example.invalid/pinned-model", target, resume=True)
    assert len(calls) == 2
    assert all("--continue-at" in command for command in calls)
    assert target.read_bytes() == b"valid prefix more bytes more bytes"
