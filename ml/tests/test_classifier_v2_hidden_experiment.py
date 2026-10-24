import json
from types import SimpleNamespace

import numpy as np

from zavozik_ml.classify_v2 import novelty_experiment as experiment
from zavozik_ml.classify_v2.model import EncoderClassifier
from zavozik_ml.classify_v2.taxonomy import Taxonomy


def test_discovery_pool_includes_known_false_alerts_before_oracle_naming(tmp_path, monkeypatch):
    full = Taxonomy.load()
    taxonomy = full.without({"leasing", "enforcement"})
    d = len(taxonomy.categories) + 1
    cfg = dict(embedding_dim=d, category_scale=20., category_temperature=1., channel_temperature=1.,
               novelty_threshold=.5, tag_thresholds=[.5] * len(taxonomy.tags),
               hidden_categories=["leasing", "enforcement"], model_version="hidden-test")
    heads = dict(prototypes=np.eye(d)[:len(taxonomy.categories)],
                 channel_weight=np.zeros((len(taxonomy.channels), d)), channel_bias=np.zeros(len(taxonomy.channels)),
                 tag_weight=np.zeros((len(taxonomy.tags), d)), tag_bias=np.zeros(len(taxonomy.tags)))
    model = EncoderClassifier(taxonomy, cfg, heads, lambda texts: np.eye(d)[[0] * len(texts)])
    monkeypatch.setattr(experiment.EncoderClassifier, "load", lambda path: model)
    rows = [dict(id="known-alert", label="supplier", text="known", purpose="known", direction="out", name=""),
            dict(id="hidden", label="leasing", text="hidden", purpose="hidden", direction="out", name="")]
    monkeypatch.setattr(experiment, "read_rows", lambda path: rows)
    (tmp_path / "data_manifest.json").write_text(json.dumps(dict(calibration_companies=["cal"], test_companies=["test"])))
    (tmp_path / "manifest.json").write_text("{}")

    def predict(classifier, examples):
        predictions = []
        for row in examples:
            x = np.eye(d)[0].astype(np.float32)
            record = dict(embedding=x.tolist(), is_novel=True, model_version=model.model_version,
                          taxonomy_version=taxonomy.version)
            predictions.append(SimpleNamespace(embedding=x, is_novel=True, category="supplier",
                                                as_dict=lambda r=record: r))
        return predictions, 0.

    monkeypatch.setattr(experiment, "predict_rows", predict)
    pools = []

    def propose(classifier, records, min_cluster_size):
        pools.append([r["id"] for r in records])
        return {"proposals": []}, {}

    monkeypatch.setattr(experiment, "propose", propose)
    result = experiment.run(tmp_path, tmp_path, tmp_path / "result")
    assert pools == [["known-alert", "hidden"]]
    assert result["discovery_known_novel_rows"] == 1
    assert result["discovery_hidden_rows"] == 1
    assert result["discovery_prefiltered_by_gold"] is False
    assert all(not e["added"] for e in result["extensions"])
    assert result["encoder_retrained"] is False
