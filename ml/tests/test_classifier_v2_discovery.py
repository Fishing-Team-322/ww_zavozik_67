import copy
import json

import numpy as np
import pytest

from zavozik_ml.classify_v2.discovery import propose, approve
from zavozik_ml.classify_v2.model import EncoderClassifier, sha256_file
from zavozik_ml.classify_v2.taxonomy import Taxonomy
from zavozik_ml.classify_v2.text import Operation


def make_classifier():
    taxonomy = Taxonomy.load()
    d = 24
    config = dict(embedding_dim=d, category_scale=25., category_temperature=1., channel_temperature=1.,
                  novelty_threshold=.3, tag_thresholds=[.5] * len(taxonomy.tags), model_version="discovery-test")
    heads = dict(prototypes=np.eye(d, dtype=np.float32)[:len(taxonomy.categories)],
                 channel_weight=np.zeros((len(taxonomy.channels), d)), channel_bias=np.zeros(len(taxonomy.channels)),
                 tag_weight=np.zeros((len(taxonomy.tags), d)), tag_bias=np.zeros(len(taxonomy.tags)))
    return EncoderClassifier(taxonomy, config, heads, lambda texts: np.tile(np.eye(d)[-1], (len(texts), 1)))


def test_empty_small_and_known_pools_do_not_create_categories():
    model = make_classifier()
    assert propose(model, [])[0]["proposals"] == []
    known = np.eye(model.config["embedding_dim"])[0]
    r = dict(model_version=model.model_version, taxonomy_version=model.taxonomy.version,
             embedding=known.tolist(), is_novel=True)  # stale/caller-supplied flag
    report, centers = propose(model, [r] * 10, min_cluster_size=3)
    assert report["eligible_novel_rows"] == 0
    assert centers == {}
    assert len(model.taxonomy.categories) == 20


def test_discovery_rejects_mixed_feature_spaces_and_nonfinite_vectors():
    model = make_classifier()
    r = dict(model_version="another-model", taxonomy_version=model.taxonomy.version,
             embedding=[0.] * 24, is_novel=True)
    with pytest.raises(ValueError, match="versions"):
        propose(model, [r])
    r["model_version"] = model.model_version
    r["embedding"][-1] = float("nan")
    with pytest.raises(ValueError, match="embedding"):
        propose(model, [r])


def test_real_hdbscan_proposal_keeps_membership_and_source_immutable():
    pytest.importorskip("sklearn")
    model = make_classifier()
    rng = np.random.default_rng(81)
    records = []
    for i in range(24):
        x = rng.normal(0, .002, 24).astype(np.float32)
        x[-1 if i < 12 else -2] += 1
        records.append(dict(model_version=model.model_version, taxonomy_version=model.taxonomy.version,
                            embedding=x.tolist(), is_novel=True, id=str(i), direction="out",
                            purpose="Новый вид платежей", tags=[]))
    original = copy.deepcopy(model.taxonomy.document)
    report, centers = propose(model, records, min_cluster_size=5)
    assert len(centers) == 2
    members = [i for p in report["proposals"] for i in p["member_indices"]]
    assert len(members) == len(set(members))
    for p in report["proposals"]:
        assert p["size"] == len(p["member_indices"])
        assert len(p["representatives"]) <= 10
        assert p["kind"] == "new_category_review"
        assert p["proposed_attributes"]["direction"] == "out"
    assert model.taxonomy.document == original


def test_approval_without_reviewer_fails_before_loading_or_writing(tmp_path):
    with pytest.raises(ValueError, match="reviewer"):
        approve(tmp_path / "missing", tmp_path / "report", tmp_path / "centers", "x", {}, "v2", " ",
                tmp_path / "models", tmp_path / "work")
    assert not (tmp_path / "work").exists()


def test_artifact_hash_manifest_detects_changes_before_runtime_import(tmp_path):
    from zavozik_ml.classify_v2.artifact import seal
    from zavozik_ml.classify_v2.text import NORMALIZER_VERSION
    t = Taxonomy.load()
    model = make_classifier()
    config = dict(model.config, artifact_version=2, normalizer_version=NORMALIZER_VERSION,
                  taxonomy_sha256=t.sha256, base_source=dict(model_id="test/local", revision="0" * 40))
    (tmp_path / "config.json").write_text(json.dumps(config))
    (tmp_path / "taxonomy.json").write_text(t.dumps())
    (tmp_path / "tokenizer.json").write_text("{}")
    np.savez_compressed(tmp_path / "heads.npz", **model.heads)
    seal(tmp_path)
    with (tmp_path / "heads.npz").open("ab") as f:
        f.write(b"tamper")
    with pytest.raises(ValueError, match="digest mismatch"):
        EncoderClassifier.load(tmp_path)


def test_publication_requires_card_and_never_overwrites(tmp_path):
    from zavozik_ml.classify_v2.artifact import publish
    source = tmp_path / "candidate"; source.mkdir()
    (source / "config.json").write_text(json.dumps({"model_version": "encoder-v1-test"}))
    with pytest.raises(ValueError, match="model card"):
        publish(source, tmp_path / "models")
    (source / "README.md").write_text("Test card")
    dest = publish(source, tmp_path / "models")
    assert (dest / "README.md").read_text() == "Test card"
    with pytest.raises(ValueError, match="already exists"):
        publish(source, tmp_path / "models")


def test_artifact_identity_includes_nested_encoder_configuration(tmp_path):
    from zavozik_ml.classify_v2.artifact import seal
    (tmp_path / "config.json").write_text(json.dumps(dict(base_source=dict(model_id="test", revision="fixed"))))
    encoder = tmp_path / "encoder"
    encoder.mkdir()
    (encoder / "config.json").write_text('{"layer_norm_eps": 1e-12}')
    version = seal(tmp_path)
    (encoder / "config.json").write_text('{"layer_norm_eps": 1e-6}')
    assert seal(tmp_path) != version
    version = seal(tmp_path)
    (tmp_path / "README.md").write_text("A human readable card does not affect predictions.")
    assert seal(tmp_path) == version
