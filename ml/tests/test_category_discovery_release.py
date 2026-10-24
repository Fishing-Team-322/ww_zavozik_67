import json

import numpy as np
import pytest

from zavozik_ml.category_discovery.core import CategoryInventory, Settings
from zavozik_ml.category_discovery.corpus import TEXT_VERSION
from zavozik_ml.category_discovery.hierarchy import build
from zavozik_ml.category_discovery.release import publish, verify
from zavozik_ml.classify_v2.model import sha256_file


def test_release_is_bound_immutable_and_detects_corruption(tmp_path):
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    category = dict(id="a", title="аренда", direction="out", title_status="auto_extractive", radius=.1,
                    support_families=["1", "2", "3"], independent_families=3)
    inv = CategoryInventory(dict(settings=Settings().__dict__, categories=[category],
                            encoder_version=f"e5-small-test-mean128-{TEXT_VERSION}", embedding_dim=2), np.array([[1, 0]], np.float32))
    inv.save(experiment / "inventory")
    tree = build(inv)
    tree.save(tmp_path / "hierarchy.json")
    (experiment / "fit_source").mkdir()
    (experiment / "fit_source/core.py").write_text("# Historical data, not imported\n")
    (experiment / "protocol.json").write_text("{}")
    base = tmp_path / "base"
    base.mkdir()
    (base / "config.json").write_text("{}")
    (base / "base_source.json").write_text(json.dumps(dict(model_id="intfloat/multilingual-e5-small", revision="test",
        files_sha256={"config.json": sha256_file(base / "config.json")})))
    card = tmp_path / "README.md"
    card.write_text("# Research fixture, not a trained model")
    out = publish(experiment, tmp_path / "hierarchy.json", base, tmp_path / "models", card)
    assert verify(out)["hierarchy_version"] == tree.version
    with pytest.raises(ValueError, match="overwrite"):
        publish(experiment, tmp_path / "hierarchy.json", base, tmp_path / "models", card)
    (out / "encoder/config.json").write_text("changed")
    with pytest.raises(ValueError, match="checksum"):
        verify(out)
