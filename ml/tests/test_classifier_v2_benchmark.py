import string

import numpy as np
import pytest

from zavozik_ml.classify_v2.benchmark import benchmark
from zavozik_ml.classify_v2.model import EncoderClassifier
from zavozik_ml.classify_v2.taxonomy import Taxonomy


def test_benchmark_refuses_batches_that_only_differ_in_numbers_or_ids():
    rows = [dict(direction="out", purpose=f"Оплата по счету №{i}", id=str(i), amount=10000) for i in range(300)]
    with pytest.raises(ValueError, match="distinct normalized"):
        benchmark(None, rows, repeats=3)


def test_benchmark_measures_complete_predictions_without_cross_request_cache():
    t = Taxonomy.load(); d = 24
    calls = []
    def encode(texts):
        calls.append(len(texts))
        return np.tile(np.eye(d, dtype=np.float32)[0], (len(texts), 1))
    c = EncoderClassifier(t, dict(embedding_dim=d, category_scale=25., category_temperature=1.,
            channel_temperature=1., novelty_threshold=.5, tag_thresholds=[.5] * len(t.tags), runtime="test"),
        dict(prototypes=np.eye(d)[:len(t.categories)], channel_weight=np.zeros((len(t.channels), d)),
             channel_bias=np.zeros(len(t.channels)), tag_weight=np.zeros((len(t.tags), d)), tag_bias=np.zeros(len(t.tags))), encode)
    words = [a+b for a in string.ascii_lowercase for b in string.ascii_lowercase][:300]
    rows = [dict(direction="out", purpose="Материалы " + word, amount=10000) for word in words]
    r = benchmark(c, rows, repeats=3)
    assert calls == [256] * 4  # warmup + every timed request executes the encoder
    assert r["distinct_normalized_inputs"] == 256
    assert len(r["times_s"]) == 3
    assert "all heads" in r["includes"]
