"""Read-only consistency audit of supplied coarse/fine equivalence evidence.

A same-chain ending in an explicit different edge cannot all describe one
partition. Report the contradictory cycle; do not guess which edge is wrong,
repair labels, train again, or interpret consistency as semantic correctness.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import json
from pathlib import Path

from zavozik_ml.classify_v2.model import sha256_file
from .corpus import read_rows


def audit(rows):
    seen, partitions, provenance = set(), set(), Counter()
    for r in rows:
        a, b = (r[s]["content_key"] for s in ("left", "right"))
        key = tuple(sorted((a, b)))
        if a == b or key in seen:
            raise ValueError("duplicate/self relation evidence")
        seen.add(key)
        partitions.add(r["partition"])
        provenance[r["provenance"]] += 1
        if any(r[level] not in ("same", "different", "uncertain") for level in ("coarse", "fine")):
            raise ValueError("invalid relation")
        if r["fine"] == "same" and r["coarse"] != "same" or r["coarse"] == "different" and r["fine"] != "different":
            raise ValueError("inconsistent relation levels")
    if len(partitions) != 1 or not partitions <= {"train", "calibration"}:
        raise ValueError("one train/calibration partition required; never final")
    result = dict(scope="supplied_pair_equivalence_consistency_only", partition=next(iter(partitions)),
        label_provenance=dict(provenance), pairs=len(rows), semantic_accuracy=None,
        independent_test=False, final_test_read=False, labels_modified=False, levels={},
        limitations="Consistency is necessary for equivalence groups, not proof of semantic correctness. No automatic edge repair or new fit.")
    for level in ("coarse", "fine"):
        graph = defaultdict(dict)
        for r in rows:
            a, b = (r[s]["content_key"] for s in ("left", "right"))
            graph[a]; graph[b]
            if r[level] == "same":
                graph[a][b] = graph[b][a] = r["pair_id"]
        components, sizes = {}, []
        for start in sorted(graph):
            if start in components:
                continue
            component = len(sizes)
            queue = deque([start]); components[start] = component; size = 0
            while queue:
                node = queue.popleft(); size += 1
                for neighbor in sorted(graph[node]):
                    if neighbor not in components:
                        components[neighbor] = component; queue.append(neighbor)
            sizes.append(size)
        conflicts = []
        for r in rows:
            a, b = (r[s]["content_key"] for s in ("left", "right"))
            if r[level] != "different" or components[a] != components[b]:
                continue
            # Deterministic shortest positive path is a concrete conflict witness.
            queue, previous = deque([a]), {a:None}
            while queue and b not in previous:
                node = queue.popleft()
                for neighbor in sorted(graph[node]):
                    if neighbor not in previous:
                        previous[neighbor] = node; queue.append(neighbor)
            nodes, edges, node = [b], [], b
            while previous[node] is not None:
                parent = previous[node]; edges.append(graph[parent][node]); nodes.append(parent); node = parent
            conflicts.append(dict(different_pair_id=r["pair_id"],
                same_path_pair_ids=list(reversed(edges)), same_path_content_keys=list(reversed(nodes))))
        result["levels"][level] = dict(relation_counts=dict(Counter(r[level] for r in rows)),
            endpoint_count=len(graph), positive_components=len(sizes), maximum_component_size=max(sizes),
            conflicting_different_pairs=len(conflicts), conflicts=conflicts)
    return result


def run(labels: Path, out: Path):
    if out.exists():
        raise ValueError("immutable relation audit exists")
    report = audit(read_rows(labels))
    report.update(labels_sha256=sha256_file(labels), code_sha256=sha256_file(Path(__file__)))
    out.mkdir(parents=True)
    (out / "report.json").write_text(json.dumps(report, indent=2)+"\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(run(a.labels, a.out), indent=2))


if __name__ == "__main__":
    main()
