from copy import deepcopy

import numpy as np
import pytest

from zavozik_ml.category_discovery.core import CategoryInventory, Settings, unit
from zavozik_ml.category_discovery.hierarchy import CategoryHierarchy, build


def inventory():
    cats = [dict(id=str(i), title=t, title_status="auto_extractive", direction="out", radius=.1,
                 independent_families=3, support_families=[f"f{i}-{j}" for j in range(3)])
            for i, t in enumerate(["товары материалы", "товары оборудование", "заработная плата", "аванс сотруднику"])]
    return CategoryInventory(dict(settings=Settings().__dict__, categories=cats, encoder_version="e", embedding_dim=4),
                             unit(np.array([[1, .1, 0, 0], [1, -.1, 0, 0], [0, 0, 1, .1], [0, 0, 1, -.1]], np.float32)))


def test_discovered_tree_has_coarse_groups_and_unchanged_leaf_ids(tmp_path):
    inv = inventory()
    tree = build(inv)
    assert len(tree.document["coarse_nodes"]) == 2
    assert tree.leaf_coarse["0"] == tree.leaf_coarse["1"]
    assert tree.leaf_coarse["2"] == tree.leaf_coarse["3"]
    assert tree.leaf_coarse["0"] != tree.leaf_coarse["2"]
    path = tree.leaf_paths["0"]
    assert path[0] == "flow_out" and path[-1] == "0"
    assert all(tree.nodes[k]["title_status"] == "auto_extractive" for k in path[1:])
    tree.save(tmp_path / "hierarchy.json")
    assert CategoryHierarchy.load(tmp_path / "hierarchy.json", inv).version == tree.version
    assignments = [dict(category_id="0", taxonomy_version=inv.version), dict(category_id=None, taxonomy_version=inv.version)]
    enriched = tree.decorate(assignments)
    assert enriched[0]["category_path"] == path
    assert enriched[1]["category_path"] == []
    assert enriched[0]["coarse_category_id"] == tree.leaf_coarse["0"]


def test_invalid_tree_and_mixed_version_refused():
    inv = inventory()
    tree = build(inv)
    changed = deepcopy(tree.document)
    changed["nodes"][0]["children"] = [changed["nodes"][0]["id"]]
    with pytest.raises(ValueError):
        CategoryHierarchy(changed, inv)
    with pytest.raises(ValueError, match="version"):
        tree.decorate([dict(category_id="0", taxonomy_version="other")])
    changed = deepcopy(tree.document)
    changed["coarse_nodes"] = ["0"]
    with pytest.raises(ValueError, match="partition"):
        CategoryHierarchy(changed, inv)
