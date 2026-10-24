from copy import deepcopy
import json

import numpy as np
import pytest

from zavozik_ml.category_discovery.core import CategoryInventory, Settings, family_points, fit_inventory, unit
from zavozik_ml.category_discovery.corpus import semantic_text, informative


def fixture():
    rng = np.random.default_rng(42)
    centers = np.eye(12, dtype=np.float32)[:3]
    rows, values = [], []
    for group in range(3):
        for j in range(8):
            rows.append(dict(id=f"{group}-{j}", company=f"c{j%3}", companies=[f"c{j%3}"],
                             template_family=f"f{group}-{j}", direction="out",
                             semantic_text=f"{'аренда помещения' if group == 0 else 'поставка оборудования' if group == 1 else 'заработная плата'} вид{j}"))
            values.append(unit(centers[group] + rng.normal(0, .005, 12)))
    return rows, np.array(values, np.float32)


def test_real_groups_discovered_without_vocabulary_and_stable_roundtrip(tmp_path):
    pytest.importorskip("sklearn")
    rows, x = fixture()
    inv, report, _ = fit_inventory(rows, x, "test-encoder")
    assert len(inv.categories) == 3
    assert not inv.document["seed_categories"]
    assert inv.document["fixed_category_count"] is None
    assert report["noise_points"] == 0
    assert all(c["title_status"] == "auto_extractive" for c in inv.categories)
    inv.save(tmp_path / "model")
    loaded = CategoryInventory.load(tmp_path / "model")
    assert loaded.version == inv.version
    assert all(a["status"] == "assigned" for a in loaded.assign(rows, x, "test-encoder"))
    with pytest.raises(ValueError, match="incompatible"):
        loaded.assign(rows, x, "different-encoder")
    with pytest.raises(ValueError, match="immutable"):
        inv.save(tmp_path / "model")
    (tmp_path / "model/taxonomy.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        CategoryInventory.load(tmp_path / "model")


def test_repetition_and_arbitrary_legacy_labels_do_not_change_fit():
    pytest.importorskip("sklearn")
    rows, x = fixture()
    a, _, _ = fit_inventory(rows, x, "encoder")
    repeated = [dict(r, label="WRONG", category="any", weight=100000) for r in rows] * 20
    b, _, _ = fit_inventory(repeated, np.tile(x, (20, 1)), "encoder")
    assert a.version == b.version
    assert sum(c["independent_families"] for c in b.categories) == 24


def test_no_fake_density_from_same_template():
    pytest.importorskip("sklearn")
    rows, x = fixture()
    for row in rows:
        row["template_family"] = "one-template"
    inv, report, _ = fit_inventory(rows, x, "encoder")
    assert inv.categories == []
    assert report["independent_points"] == 1
    assert all(r["status"] == "no_category" for r in inv.assign(rows, x, "encoder"))


def test_ambiguous_unknown_empty_and_direction_are_not_forced():
    document = dict(settings=Settings().__dict__, categories=[
        dict(id="a", title="a", direction="out", radius=.2),
        dict(id="b", title="b", direction="out", radius=.2)], encoder_version="e", embedding_dim=3)
    inv = CategoryInventory(document, unit(np.array([[1, .1, 0], [1, -.1, 0]], np.float32)))
    rows = [dict(id=str(i), direction=d, semantic_text=t) for i, (d, t) in enumerate([
        ("out", "аренда"), ("out", "аренда"), ("out", ""), ("in", "аренда")])]
    pred = inv.assign(rows, np.array([[1, 0, 0], [0, 0, 1], [1, 0, 0], [1, 0, 0]], np.float32), "e")
    assert [p["status"] for p in pred] == ["ambiguous", "outside_cluster", "insufficient_text", "no_category"]
    assert all(p["category_id"] is None for p in pred)
    assert all(p["score_kind"] == "cosine_geometry_not_probability" for p in pred)


def test_incremental_inventory_preserves_existing_ids(tmp_path):
    pytest.importorskip("sklearn")
    rows, x = fixture()
    parent, _, _ = fit_inventory(rows, x, "e")
    more = deepcopy(rows)
    # Three genuinely new semantic groups, distinct families/companies.
    for row in more:
        row["template_family"] += "new"
    y = np.roll(x, 4, axis=1)
    child, report, _ = fit_inventory(more, y, "e", parent=parent)
    assert len(child.categories) > len(parent.categories)
    assert child.categories[:len(parent.categories)] == parent.categories
    assert child.document["parent_taxonomy_version"] == parent.version
    np.testing.assert_array_equal(child.centers[:len(parent.centers)], parent.centers)
    unchanged, report, _ = fit_inventory(rows, x, "e", parent=parent)
    assert report["discovered_categories"] == 0
    assert unchanged.version == parent.version


def test_invalid_geometry():
    rows, x = fixture()
    for bad in (x[:2], x * np.nan, x * 0):
        with pytest.raises(ValueError):
            fit_inventory(rows, bad, "e")
    with pytest.raises(ValueError):
        Settings(min_cluster_size=1).validate()


def test_structural_purpose_has_no_category_lookup():
    assert semantic_text("Оплата аренды по договору № 123 от 01.10.2026") == semantic_text("Оплата аренды по договору № 987 от 22.11.2025")
    assert not informative(semantic_text(""))
    assert not informative("оплата по счету")
    assert informative("поставка оборудования")
