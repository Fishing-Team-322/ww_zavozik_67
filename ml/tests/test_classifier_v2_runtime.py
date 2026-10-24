import copy
import json

import numpy as np
import pytest

from zavozik_ml.classify_v2.artifact import seal
from zavozik_ml.classify_v2.calibration import calibrate
from zavozik_ml.classify_v2.model import EncoderClassifier
from zavozik_ml.classify_v2.novelty import fit_reference
from zavozik_ml.classify_v2.taxonomy import Taxonomy
from zavozik_ml.classify_v2.text import NORMALIZER_VERSION, Operation


@pytest.fixture
def artifact(tmp_path):
    taxonomy = Taxonomy.load()
    d = len(taxonomy.categories) + 1
    cfg = dict(artifact_version=2, normalizer_version=NORMALIZER_VERSION,
               embedding_dim=d, category_scale=20., category_temperature=1., channel_temperature=1.,
               novelty_threshold=.4, tag_thresholds=[.5] * len(taxonomy.tags),
               taxonomy_sha256=taxonomy.sha256, runtime="onnx", onnx_file="encoder-int8.onnx",
               base_source=dict(model_id="test", revision="fixed"))
    heads = dict(prototypes=np.eye(d)[:len(taxonomy.categories)],
                 channel_weight=np.zeros((len(taxonomy.channels), d)), channel_bias=np.zeros(len(taxonomy.channels)),
                 tag_weight=np.zeros((len(taxonomy.tags), d)), tag_bias=np.zeros(len(taxonomy.tags)))
    np.savez_compressed(tmp_path / "heads.npz", **heads)
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    (tmp_path / "taxonomy.json").write_text(taxonomy.dumps())
    for name in ("tokenizer.json", "encoder/config.json", "encoder/model.safetensors", "encoder/tokenizer.json",
                 "encoder-fp32.onnx", "encoder-int8.onnx"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("test-local-payload")
    ref = fit_reference(np.linspace(.1, .3, 100), np.zeros(100, int), taxonomy.categories)
    cal = dict(category_temperature=2., channel_temperature=3., tag_thresholds=[.7] * len(taxonomy.tags),
               novelty_threshold=.95, novelty_reference=ref)
    comparison = dict(variants={"torch-fp32": {"calibration": cal}, "onnx-fp32": {"calibration": cal}})
    (tmp_path / "runtime_comparison.json").write_text(json.dumps(comparison))
    seal(tmp_path)
    return tmp_path


def factory(directory, config):
    return lambda texts: np.tile(np.eye(config["embedding_dim"])[0], (len(texts), 1))


def test_override_uses_own_calibration_and_distinct_version(artifact):
    default = EncoderClassifier.load(artifact, encoder_factory=factory)
    torch = EncoderClassifier.load(artifact, backend="torch", encoder_factory=factory)
    assert torch.config["category_temperature"] == 2.
    assert torch.config["channel_temperature"] == 3.
    assert torch.config["novelty_reference"]["method"] == "predicted_category_distance_rank_v1"
    assert torch.model_version == default.model_version + "+runtime-torch-fp32"
    assert default.config["category_temperature"] == 1.
    assert not torch.predict([Operation("out", "test")])[0].is_novel


def test_onnx_override_from_torch_chooses_calibrated_fp32_graph(artifact):
    path = artifact / "config.json"
    config = json.loads(path.read_text())
    config.update(runtime="torch", onnx_file=None)
    path.write_text(json.dumps(config)); seal(artifact)
    model = EncoderClassifier.load(artifact, backend="onnx", encoder_factory=factory)
    assert model.config["onnx_file"] == "encoder-fp32.onnx"
    assert model.config["category_temperature"] == 2.
    assert model.model_version.endswith("+runtime-onnx-fp32")


@pytest.mark.parametrize("missing,backend", [("encoder-int8.onnx", None), ("encoder/model.safetensors", "torch"),
                                             ("runtime_comparison.json", "torch")])
def test_unlisted_runtime_payload_is_rejected_before_loading(artifact, missing, backend):
    path = artifact / "manifest.json"
    manifest = json.loads(path.read_text())
    del manifest["files_sha256"][missing]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="missing from artifact manifest"):
        EncoderClassifier.load(artifact, backend=backend, encoder_factory=lambda *_: pytest.fail("runtime initialized"))


def test_calibration_and_runtime_agree_on_distance_rank():
    rng = np.random.default_rng(2)
    n = 100
    raw = dict(category_logits=np.tile([4., -2.], (n, 1)), channel_logits=np.tile([2., -1.], (n, 1)),
               tag_logits=rng.normal(size=(n, 2)), novelty=np.linspace(.1, .3, n))
    cal = calibrate(raw, np.zeros(n, int), np.zeros(n, int), np.zeros((n, 2), bool), categories=("a", "b"))
    assert cal["novelty_threshold"] == .95
    assert cal["known_calibration_fpr"] <= .05
    assert cal["novelty_reference"]["by_category"]["a"] == raw["novelty"].tolist()
