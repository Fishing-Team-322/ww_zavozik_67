import json

import pytest

from zavozik_ml.classify_v2.select_model import select, selection_score
from zavozik_ml.classify_v2.splitting import PROTOCOL


def candidate(tmp_path, name, accuracy, size=100, signature="same"):
    path = tmp_path / name; path.mkdir()
    (path / "encoder").mkdir()
    (path / "encoder/model.safetensors").write_bytes(b"x" * size)
    (path / "heads.npz").write_bytes(b"test heads")
    calibration = {"source": "calibration_companies_only", "category": {"accuracy": accuracy, "macro_f1": .99},
                   "channel": {"accuracy": .99}, "tags": {"micro_f1": .99}}
    config = {"base_source": {"model_id": name, "revision": "0" * 40}, "selected_epoch": 2,
              "hidden_categories": [], "data_manifest": {"calibration": {"sha256": signature}, "test_companies": ["T1"],
                "train": {"sha256": "same-train"}, "template_registry_sha256": "same-families",
                "split_protocol": PROTOCOL, "split_audit": {"passed": True}}}
    (path / "config.json").write_text(json.dumps(config))
    (path / "calibration.json").write_text(json.dumps(calibration))
    return path


def test_selection_uses_completed_calibration_quality_not_artifact_size(tmp_path):
    tiny = candidate(tmp_path, "tiny", .991, 10)
    good = candidate(tmp_path, "good", .995, 1000)
    report = select([tiny, good])
    assert report["selected_checkpoint"] == str(good)
    assert "not accessed" in report["evaluation_scope"]


def test_exact_quality_tie_prefers_smaller_weights(tmp_path):
    first = candidate(tmp_path, "large", .995, 1000)
    second = candidate(tmp_path, "small", .995, 10)
    assert select([first, second])["selected_checkpoint"] == str(second)


def test_different_calibration_data_cannot_be_compared_as_equal_cohorts(tmp_path):
    a = candidate(tmp_path, "a", .995)
    b = candidate(tmp_path, "b", .996, signature="other")
    with pytest.raises(ValueError, match="same calibration"):
        select([a, b])


def test_intermediate_or_hidden_category_runs_are_not_main_candidates(tmp_path):
    p = candidate(tmp_path, "a", .995)
    config = json.loads((p / "config.json").read_text())
    config["hidden_categories"] = ["leasing"]
    (p / "config.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="ineligible"):
        select([p])
    config["hidden_categories"] = []
    (p / "config.json").write_text(json.dumps(config))
    (p / "calibration.json").unlink()
    with pytest.raises(FileNotFoundError):
        select([p])


def test_same_calibration_with_different_training_pool_is_not_a_fair_encoder_comparison(tmp_path):
    a = candidate(tmp_path, "a", .995)
    b = candidate(tmp_path, "b", .996)
    cfg = json.loads((b / "config.json").read_text())
    cfg["data_manifest"]["train"]["sha256"] = "more-training-data"
    (b / "config.json").write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match="same calibration"):
        select([a, b])
