"""Train-only hierarchy above discovered leaves, without a named seed list.

Complete-linkage cosine merges are exposed as an inspectable tree. A coarse
cut is determined by the largest adjacent height gap among the last half of
merges per direction (a coarse view rather than a near-leaf cut);
it is a geometric heuristic, not an expert definition of accounting groups.
"""
from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path

import numpy as np

from .core import CategoryInventory, titles


class CategoryHierarchy:
    def __init__(self, document, inventory):
        self.document = json.loads(json.dumps(document))
        if document["leaf_inventory_version"] != inventory.version:
            raise ValueError("hierarchy belongs to a different leaf inventory")
        nodes = document["nodes"]
        self.nodes = {n["id"]: n for n in nodes}
        if len(self.nodes) != len(nodes):
            raise ValueError("duplicate hierarchy node")
        self.parents = {}
        leaves = {c["id"] for c in inventory.categories}
        if {n["id"] for n in nodes if n["node_kind"] == "leaf"} != leaves:
            raise ValueError("hierarchy leaves differ from inventory")
        roots = set(document["roots"])
        for node in nodes:
            if node["direction"] not in ("in", "out") or node["node_kind"] not in ("leaf", "group", "direction"):
                raise ValueError("invalid hierarchy node")
            children = node["children"]
            if (node["node_kind"] == "leaf") != (not children):
                raise ValueError("invalid hierarchy children")
            for child in children:
                if child not in self.nodes or child in self.parents or child == node["id"]:
                    raise ValueError("unknown, repeated or circular child")
                if self.nodes[child]["direction"] != node["direction"]:
                    raise ValueError("mixed direction subtree")
                self.parents[child] = node["id"]
        if roots != set(self.nodes)-set(self.parents):
            raise ValueError("invalid roots")
        for node in self.nodes:
            seen, current = set(), node
            while current in self.parents:
                if current in seen:
                    raise ValueError("cyclic hierarchy")
                seen.add(current)
                current = self.parents[current]
        coarse = set(document["coarse_nodes"])
        if not coarse <= set(self.nodes):
            raise ValueError("unknown coarse node")
        self.leaf_paths = {leaf: self.path(leaf) for leaf in leaves}
        self.leaf_coarse = {}
        for leaf, path in self.leaf_paths.items():
            candidates = [node for node in path if node in coarse]
            if len(candidates) != 1:
                raise ValueError("coarse nodes must partition the leaves")
            self.leaf_coarse[leaf] = candidates[0]
        self.document.pop("hierarchy_version", None)
        digest = hashlib.sha256(json.dumps(self.document, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
        self.version = "hierarchy-v1-" + digest
        self.document["hierarchy_version"] = self.version

    def path(self, leaf):
        path = [leaf]
        while path[-1] in self.parents:
            path.append(self.parents[path[-1]])
        return list(reversed(path))

    def decorate(self, assignments):
        result = []
        for a in assignments:
            if a["taxonomy_version"] != self.document["leaf_inventory_version"]:
                raise ValueError("assignment/inventory version mismatch")
            leaf = a["category_id"]
            coarse = self.leaf_coarse[leaf] if leaf else None
            result.append(dict(a, category_path=self.leaf_paths[leaf] if leaf else [],
                               coarse_category_id=coarse, coarse_category_title=self.nodes[coarse]["title"] if coarse else None,
                               hierarchy_version=self.version))
        return result

    def save(self, path: Path):
        if path.exists():
            raise ValueError("hierarchy exists")
        path.write_text(json.dumps(self.document, ensure_ascii=False, indent=2) + "\n")

    @classmethod
    def load(cls, path, inventory):
        doc = json.loads(Path(path).read_text())
        result = cls(doc, inventory)
        if result.version != doc["hierarchy_version"]:
            raise ValueError("hierarchy version mismatch")
        return result


def build(inventory: CategoryInventory):
    from scipy.cluster.hierarchy import linkage
    nodes, roots, coarse, cuts = [], [], [], {}
    for direction in ("in", "out"):
        ids = sorted([i for i, c in enumerate(inventory.categories) if c["direction"] == direction],
                     key=lambda i: inventory.categories[i]["id"])
        if not ids:
            continue
        local, descendants, heights = {}, {}, {}
        for j, i in enumerate(ids):
            category = inventory.categories[i]
            node = dict(id=category["id"], title=category["title"], title_status=category["title_status"],
                        direction=direction, node_kind="leaf", children=[],
                        independent_families=category["independent_families"])
            nodes.append(node)
            local[j], descendants[j], heights[j] = node["id"], [i], 0.
        z = linkage(inventory.centers[ids].astype(np.float64), method="complete", metric="cosine") if len(ids) > 1 else np.empty((0, 4))
        for j, (a, b, distance, _) in enumerate(z):
            a, b, index = int(a), int(b), len(ids)+j
            children = sorted([local[a], local[b]])
            members = sorted(descendants[a]+descendants[b])
            identity = hashlib.sha256("|".join(sorted(inventory.categories[i]["id"] for i in members)).encode()).hexdigest()[:16]
            title = titles([[inventory.categories[i]["title"] for i in members]])[0]
            node = dict(id="group_"+identity, title=title, title_status="auto_extractive", direction=direction,
                        node_kind="group", children=children, merge_distance=float(distance),
                        independent_families=len({f for i in members for f in inventory.categories[i]["support_families"]}))
            nodes.append(node)
            local[index], descendants[index], heights[index] = node["id"], members, float(distance)
        top = len(ids)+len(z)-1 if len(z) else 0
        root = "flow_"+direction
        roots.append(root)
        nodes.append(dict(id=root, title="Поступления" if direction == "in" else "Списания",
                          title_status="direction_fact", node_kind="direction", direction=direction,
                          children=[local[top]], independent_families=len({f for i in ids for f in inventory.categories[i]["support_families"]})))
        cutoff = 0.
        if len(z) >= 2:
            gaps = np.diff(z[:, 2])
            start = len(gaps)//2
            gap = start + int(np.argmax(gaps[start:]))
            cutoff = float((z[gap, 2]+z[gap+1, 2])/2)
        cuts[direction] = dict(cosine_distance_cutoff=cutoff, method="largest_height_gap_among_last_half_complete_linkage_merges",
                               fitted_on="train_discovered_leaf_centers_only")

        def visit(index):
            if index < len(ids) or heights[index] <= cutoff:
                coarse.append(local[index])
            else:
                a, b = z[index-len(ids), :2].astype(int)
                visit(int(a))
                visit(int(b))
        visit(top)
    document = dict(format_version=1, leaf_inventory_version=inventory.version,
                    nodes=nodes, roots=roots, coarse_nodes=sorted(coarse), cuts=cuts,
                    method="direction_separated_complete_linkage_on_train_only_discovered_centers",
                    caveat="Geometric hierarchy and extractive names; semantic correctness and preferred granularity require independent review")
    return CategoryHierarchy(document, inventory)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    tree = build(CategoryInventory.load(a.inventory))
    tree.save(a.out)
    print(json.dumps(dict(hierarchy_version=tree.version, nodes=len(tree.nodes),
                          coarse_nodes=tree.document["coarse_nodes"]), indent=2))


if __name__ == "__main__":
    main()
