import importlib.util
import itertools
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from zavozik_ml.classify_v2.model import sha256_file
from zavozik_ml.category_discovery.corpus import write_rows
from zavozik_ml.category_discovery.train_metric_heads import load_part
from zavozik_ml.category_discovery.metric_evaluation import project


def fixture(tmp_path):
    corpus, cache = tmp_path / "corpus", tmp_path / "cache"
    corpus.mkdir(); cache.mkdir()
    meta = dict(intersections={"train__calibration": dict(companies=0, families=0, texts=0)})
    encoded = {}
    labels = {}
    for part in ("train", "calibration"):
        rows = [dict(id=part+str(i), content_key=part+str(i), company=part+str(i), template_family=part+str(i),
                     purpose="purpose"+str(i), direction="out") for i in range(4)]
        path = corpus / f"{part}_unique.jsonl"
        write_rows(path, rows)
        meta[part] = dict(unique_sha256=sha256_file(path))
        x = np.array([[1, 0, 0, 0], [1, .2, 0, 0], [.8, 0, .6, 0], [.9, 0, 0, .4]], np.float32)
        x /= np.linalg.norm(x, axis=1, keepdims=True)
        np.save(cache / f"{part}.npy", x, allow_pickle=False)
        encoded[part] = dict(sha256=sha256_file(cache / f"{part}.npy"), unique_sha256=meta[part]["unique_sha256"])
        pairs = []
        for i, j in itertools.combinations(range(4), 2):
            pairs.append(dict(pair_id=f"{i}{j}", partition=part, left={k:rows[i][k] for k in ("content_key", "id", "purpose", "direction")},
                right={k:rows[j][k] for k in ("content_key", "id", "purpose", "direction")},
                coarse="same" if j < 3 else "different", fine="same" if (i,j)==(0,1) else "different",
                provenance="local_model_weak", reviewer_kind="local_model"))
        labels[part] = tmp_path / f"{part}_labels.jsonl"
        write_rows(labels[part], pairs)
    (corpus / "manifest.json").write_text(json.dumps(meta))
    encoded["corpus_manifest_sha256"] = sha256_file(corpus / "manifest.json")
    (cache / "manifest.json").write_text(json.dumps(encoded))
    return corpus, cache, labels


def test_weak_targets_need_explicit_research_opt_in_and_actual_partition(tmp_path):
    corpus, cache, labels = fixture(tmp_path)
    with pytest.raises(ValueError, match="explicit research"):
        load_part(corpus, cache, labels["train"], "train", False, 1)
    with pytest.raises(ValueError, match="partition mismatch"):
        load_part(corpus, cache, labels["calibration"], "train", True, 1)
    with pytest.raises(ValueError, match="insufficient"):
        load_part(corpus, cache, labels["train"], "train", True, 20)


def test_serving_projection_preserves_shape_and_rejects_silent_dimension_changes():
    x = np.eye(3, dtype=np.float32)
    weights = {"coarse.weight":np.eye(3, dtype=np.float32), "coarse.bias":np.zeros(3, np.float32)}
    assert np.array_equal(project(x, weights, "coarse"), x)
    weights["coarse.weight"] = np.eye(2, dtype=np.float32)
    with pytest.raises(ValueError, match="dimension"):
        project(x, weights, "coarse")


@pytest.mark.skipif(importlib.util.find_spec("torch") is None, reason="optional training runtime")
def test_two_heads_can_learn_different_coarse_fine_relations_without_final_reads(tmp_path):
    corpus, cache, labels = fixture(tmp_path)
    # Real optimization in a fresh interpreter: avoid native Torch/LightGBM
    # interaction in the application's main pytest process.
    out = tmp_path / "fit"
    code = """from pathlib import Path
import json,sys
from zavozik_ml.category_discovery.train_metric_heads import fit
from zavozik_ml.category_discovery.metric_evaluation import evaluate
c,cache,tr,ca,out=map(Path,sys.argv[1:])
r=fit(c,cache,tr,ca,out,allow_weak=True,epochs=6,minimum_support=1)
assert r['best_calibration_loss'] < r['baseline_centered_calibration_loss']
assert r['final_test_read'] is False and r['full_encoder_fine_tuning'] is False
report=evaluate(c,cache,ca,out.parent/'calibration',out,allow_weak=True)
assert set(report['comparisons']) == {'original','centered','adapted'}
assert report['semantic_accuracy'] is None and report['final_test_read'] is False
assert report['label_provenance'] == {'local_model_weak':6}
"""
    result = subprocess.run([sys.executable, "-c", code, str(corpus), str(cache), str(labels["train"]),
                             str(labels["calibration"]), str(out)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    weights = np.load(out / "best_heads.npz", allow_pickle=False)
    assert not np.array_equal(weights["coarse.weight"], weights["fine.weight"])
    assert not (corpus / "test_unique.jsonl").exists()  # absent on purpose; fitting never reads it
    assert (out / "fit_source.py.txt").is_file()
