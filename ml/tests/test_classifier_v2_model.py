import json
from pathlib import Path

import grpc
import numpy as np
import pytest

from categorize.v2 import categorizer_pb2 as pb
from categorize.v2 import categorizer_pb2_grpc as pb_grpc
from zavozik_ml.classify_v2.model import EncoderClassifier
from zavozik_ml.classify_v2.taxonomy import Taxonomy
from zavozik_ml.classify_v2.text import Operation
from zavozik_ml.serving.server import build_server


@pytest.fixture
def classifier():
    t = Taxonomy.load()
    d = len(t.categories) + 3
    cfg = dict(embedding_dim=d, category_scale=25., category_temperature=1., channel_temperature=1.,
               novelty_threshold=.2, tag_thresholds=[.5] * len(t.tags), model_version="test-encoder")
    heads = dict(prototypes=np.eye(d, dtype=np.float32)[:len(t.categories)],
                 channel_weight=np.zeros((len(t.channels), d)), channel_bias=np.zeros(len(t.channels)),
                 tag_weight=np.zeros((len(t.tags), d)), tag_bias=np.full(len(t.tags), -10.))
    def encode(texts):
        result = []
        for text in texts:
            x = np.zeros(d, np.float32)
            x[-1 if "newphenomenon" in text else t.categories.index("other") if "не указано" in text else t.categories.index("supplier")] = 1
            result.append(x)
        return np.array(result)
    return EncoderClassifier(t, cfg, heads, encode)


def test_output_complete_distributions_and_semantic_properties(classifier):
    out = classifier.predict([Operation("out", "Материалы цифровыми рублями"), Operation("in")])
    assert len(out) == 2
    for p in out:
        assert p.embedding.dtype == np.float32
        assert np.isclose(np.linalg.norm(p.embedding), 1)
        assert set(p.category_probs) == set(classifier.taxonomy.categories)
        assert set(p.channel_probs) == set(classifier.taxonomy.channels)
        assert set(p.tag_probs) == set(classifier.taxonomy.tags)
        assert np.isclose(sum(p.category_probs.values()), 1)
        assert np.isclose(sum(p.channel_probs.values()), 1)
        assert p.category == max(p.category_probs, key=p.category_probs.get)
        assert p.attributes == classifier.taxonomy.category(p.category)["attributes"]
        assert 0 <= p.novelty <= 1
        assert json.loads(json.dumps(p.as_dict()))["category"] == p.category
    assert out[1].category == "other"
    assert classifier.predict([]) == []


def test_add_prototype_reuses_encoder_and_preserves_source(classifier):
    x = np.zeros(classifier.config["embedding_dim"], np.float32); x[-1] = 1
    category = dict(key="new_phenomenon", title_ru="Новый вид", description_ru="Новое явление.",
                    attributes=dict(flow="business", direction="both", mandatory=False, regular_hint=False))
    op = Operation("out", "newphenomenon")
    assert classifier.predict([op])[0].is_novel
    extended = classifier.add_category(category, x, "taxonomy-test-next")
    assert extended.encode is classifier.encode
    assert extended.predict([op])[0].category == "new_phenomenon"
    assert not extended.predict([op])[0].is_novel
    assert "new_phenomenon" not in classifier.taxonomy.categories
    assert extended.model_version != classifier.model_version
    with pytest.raises(ValueError):
        classifier.add_category(category, x * float("nan"), "bad")
    with pytest.raises(ValueError):
        classifier.add_category(category, x, classifier.taxonomy.version)


@pytest.mark.parametrize("text", ["", "??? 000", "🙂", "\x00\ud800", "-" * 8192])
def test_empty_and_garbage_are_total_for_local_inference(classifier, text):
    assert classifier.predict([Operation("out", text)])[0].category in classifier.taxonomy.categories


def test_nonfinite_encoder_output_fails_explicitly(classifier):
    classifier.encode = lambda texts: np.full((len(texts), classifier.config["embedding_dim"]), np.nan)
    with pytest.raises(ValueError, match="invalid embeddings"):
        classifier.predict([Operation("out", "test")])


@pytest.fixture
def stub(classifier):
    server, port = build_server("127.0.0.1:0", workers=2, classifier_v2=classifier)
    server.start()
    with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
        yield pb_grpc.CategorizerServiceStub(channel)
    server.stop(0)


def test_grpc_v2_roundtrip_order_dimensions_and_versions(stub, classifier):
    response = stub.Classify(pb.ClassifyRequest(operations=[
        pb.Operation(id="same-id", direction="out", payment_purpose="Поставка цифровыми рублями"),
        pb.Operation(id="same-id", direction="in"),
    ]))
    assert [p.id for p in response.results] == ["same-id", "same-id"]
    assert response.embedding_dim == classifier.config["embedding_dim"]
    assert response.model_version == "test-encoder"
    assert response.taxonomy_version == classifier.taxonomy.version
    assert all(len(p.embedding) == response.embedding_dim for p in response.results)
    assert response.results[1].category == "other"
    assert stub.Classify(pb.ClassifyRequest()).results == []


@pytest.mark.parametrize("operation", [
    pb.Operation(direction="wrong"), pb.Operation(direction="out", amount=float("nan")),
    pb.Operation(direction="out", amount=-1), pb.Operation(direction="out", amount=1e16),
    pb.Operation(direction="out", counterparty_type="7701234567"),
    pb.Operation(direction="out", payment_purpose="a" * 8193),
])
def test_grpc_rejects_invalid_input(stub, operation):
    with pytest.raises(grpc.RpcError) as e:
        stub.Classify(pb.ClassifyRequest(operations=[operation]))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_unconfigured_v2_fails_without_affecting_forecast_or_v1():
    server, port = build_server("127.0.0.1:0", workers=1)
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            with pytest.raises(grpc.RpcError) as e:
                pb_grpc.CategorizerServiceStub(channel).Classify(pb.ClassifyRequest())
            assert e.value.code() == grpc.StatusCode.FAILED_PRECONDITION
            from forecast.v1 import forecaster_pb2, forecaster_pb2_grpc
            assert forecaster_pb2_grpc.ForecasterServiceStub(channel).ListModels(forecaster_pb2.ListModelsRequest()).models
    finally:
        server.stop(0)


def test_loader_rejects_incompatible_or_tampered_artifact(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"artifact_version": -1}))
    with pytest.raises(ValueError, match="incompatible"):
        EncoderClassifier.load(tmp_path)


def test_calibration_fits_known_fpr_without_hidden_labels():
    from zavozik_ml.classify_v2.calibration import calibrate
    rng = np.random.default_rng(12)
    y = np.repeat([0, 1], 100)
    logits = np.column_stack([1-y, y]) * 3 + rng.normal(0, .1, (200, 2))
    raw = dict(category_logits=logits, channel_logits=logits, tag_logits=logits,
               novelty=np.linspace(.01, .3, 200))
    r = calibrate(raw, y, y, np.column_stack([1-y, y]))
    assert r["known_calibration_fpr"] <= .05
    assert r["category"]["ece"] <= .05
    assert r["tags"]["micro_f1"] >= .9
