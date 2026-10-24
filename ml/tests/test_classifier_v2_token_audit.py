import json

import pytest

from zavozik_ml.classify_v2.model import sha256_file
from zavozik_ml.classify_v2.token_audit import validate


@pytest.fixture
def inputs(tmp_path):
    base = tmp_path / "base"; base.mkdir()
    (base / "tokenizer.json").write_text("local tokenizer fixture")
    (base / "base_source.json").write_text(json.dumps(dict(model_id="local/test", revision="a" * 40)))
    (tmp_path / "data_manifest.json").write_text("{}")
    report = dict(passed=True, max_length=128, data_manifest_sha256=sha256_file(tmp_path / "data_manifest.json"),
                  models={"local/test": dict(base_revision="a" * 40, text_prefix="query: ",
                          tokenizer_sha256=sha256_file(base / "tokenizer.json"),
                          pairwise_token_input_intersections=dict(train__test=0, train__calibration=0, calibration__test=0))})
    (tmp_path / "token_input_audit.json").write_text(json.dumps(report))
    return tmp_path, base


def test_effective_input_audit_binds_data_tokenizer_revision_prefix_and_length(inputs):
    prepared, base = inputs
    validate(prepared, base, "query: ", 128)
    for prefix, length in [("", 128), ("query: ", 256)]:
        with pytest.raises(ValueError, match="token split audit"):
            validate(prepared, base, prefix, length)
    (prepared / "data_manifest.json").write_text('{"changed": true}')
    with pytest.raises(ValueError, match="token split audit"):
        validate(prepared, base, "query: ", 128)


def test_audit_cannot_pass_with_a_forged_success_flag_and_nonzero_overlap(inputs):
    prepared, base = inputs
    p = prepared / "token_input_audit.json"
    report = json.loads(p.read_text())
    report["models"]["local/test"]["pairwise_token_input_intersections"]["train__test"] = 1
    p.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="token split audit"):
        validate(prepared, base, "query: ", 128)
