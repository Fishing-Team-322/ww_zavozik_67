"""Training-only sparse evidence forest pilot with explicit weak provenance.

This audits the grouping algorithm and supplied evidence, NOT encoder quality,
new-operation coverage, human semantic purity or online serving readiness.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import itertools
import json
from pathlib import Path

from zavozik_ml.classify_v2.model import sha256_file
from .audit_relations import audit
from .corpus import read_rows
from .evidence_graph import evidence_index, fit, identity, pair_key


def component_forest(rows, evidence, *, allow_weak=False):
    """Decompose only along positive coarse edges; no possible merge is lost.

    Missing cross-component evidence cannot authorize a merge in `fit`, so this
    avoids repeated all-cohort quadratic scans without changing membership.
    """
    index = evidence_index(evidence, allow_weak=allow_weak)
    by_key = {r["content_key"]:r for r in rows if r["usable"]}
    if len(by_key) != sum(r["usable"] for r in rows):
        raise ValueError("duplicate semantic density rows")
    if any(r["direction"] not in ("in","out") for r in by_key.values()):
        raise ValueError("invalid training direction")
    if any(a not in by_key or b not in by_key for a,b in index):
        raise ValueError("evidence endpoint outside usable training cohort")
    adjacency = defaultdict(set)
    for (a,b), r in index.items():
        if r["coarse"] == "same" and by_key[a]["direction"] == by_key[b]["direction"]:
            adjacency[a].add(b); adjacency[b].add(a)
    component, components = {}, []
    for start in sorted(adjacency):
        if start in component:
            continue
        cid = len(components); queue = deque([start]); members = []; component[start] = cid
        while queue:
            node = queue.popleft(); members.append(node)
            for neighbor in sorted(adjacency[node]):
                if neighbor not in component:
                    component[neighbor] = cid; queue.append(neighbor)
        components.append(sorted(members))
    component_evidence = defaultdict(list)
    for (a,b), r in index.items():
        if a in component and component.get(b) == component[a]:
            component_evidence[component[a]].append(r)
    nodes, assigned = [], set()
    for cid, members in enumerate(components):
        doc = fit([by_key[k] for k in members], component_evidence[cid], allow_weak=allow_weak)
        nodes.extend(doc["nodes"])
        assigned.update(k for n in doc["nodes"] if n["level"] == "coarse" for k in n["members"])
    weak = any(r.get("provenance") == "local_model_weak" for r in evidence)
    doc = dict(schema="sparse_training_evidence_forest_pilot_v1", nodes=sorted(nodes,key=lambda n:n["id"]),
        unassigned=sorted(set(by_key)-assigned), contains_weak_evidence=weak,
        evidence_provenance=dict(Counter(r["provenance"] for r in evidence)),
        status="weak_research_not_deployable" if weak else "research_not_deployable",
        semantic_accuracy=None, independent_test=False, final_test_read=False,
        encoder_evaluated=False, support_requirements=dict(min_members=2,min_companies=2,min_families=2),
        policy="Every cross-member pair must have same evidence at its level; no forced root; absent evidence abstains",
        limitations="Sparse training evidence only. Consistency is not semantic truth. Coverage below is training membership, not held-out assignment coverage.")
    doc["hierarchy_version"] = identity("research-forest-", [json.dumps(doc,sort_keys=True)])
    # Explicitly audit all output membership rather than trusting the fitter.
    membership = {level:{} for level in ("coarse","fine")}
    by_node = {n["id"]:n for n in nodes}
    checked = Counter()
    for node in nodes:
        level = node["level"]
        if level == "fine" and not set(node["members"]) <= set(by_node[node["parent_id"]]["members"]):
            raise ValueError("child outside its economic parent")
        for k in node["members"]:
            if k in membership[level]:
                raise ValueError("overlapping economic groups at one level")
            membership[level][k] = node["id"]
        for a,b in itertools.combinations(node["members"],2):
            r = index.get(pair_key(a,b),{})
            if r.get(level) != "same" or by_key[a]["direction"] != by_key[b]["direction"]:
                raise ValueError("unsupported output membership")
            checked[level] += 1
    pair_diagnostics = {}
    for level in ("coarse","fine"):
        same, joined_same, joined_different = 0, 0, 0
        for (a,b), r in index.items():
            joined = a in membership[level] and membership[level].get(b) == membership[level][a]
            same += r[level] == "same"
            joined_same += joined and r[level] == "same"
            joined_different += joined and r[level] == "different"
        if joined_different:
            raise ValueError("explicit negative merged in output")
        pair_diagnostics[level] = dict(supplied_same_pairs=same, retained_same_pairs=joined_same,
            split_same_pairs=same-joined_same, merged_explicit_different_pairs=joined_different)
    stats = dict(training_unique_rows=len(by_key), coarse_groups=sum(n["level"]=="coarse" for n in nodes),
        fine_groups=sum(n["level"]=="fine" for n in nodes),
        coarse_assigned_training_rows=len(membership["coarse"]), fine_assigned_training_rows=len(membership["fine"]),
        coarse_only_training_rows=len(set(membership["coarse"])-set(membership["fine"])),
        unassigned_training_rows=len(doc["unassigned"]), all_cross_pairs_checked=dict(checked),
        largest_positive_component=max(map(len,components),default=0),
        coarse_group_size_distribution=dict(Counter(len(n["members"]) for n in nodes if n["level"]=="coarse")),
        pair_diagnostics=pair_diagnostics, held_out_coverage=None, semantic_purity=None)
    return doc, stats


def run(corpus: Path, labels: Path, out: Path, *, allow_weak=False):
    if out.exists():
        raise ValueError("immutable hierarchy pilot output exists")
    meta = json.loads((corpus / "manifest.json").read_text())
    if any(v for entry in meta["intersections"].values() for v in entry.values()):
        raise ValueError("nonzero prepared split intersection")
    source = corpus / "train_unique.jsonl"
    if sha256_file(source) != meta["train"]["unique_sha256"]:
        raise ValueError("training corpus changed")
    rows, pairs = read_rows(source), read_rows(labels)
    consistency = audit(pairs)
    if consistency["partition"] != "train":
        raise ValueError("hierarchy fit uses training evidence only")
    by_key = {r["content_key"]:r for r in rows}
    for r in pairs:
        for side in ("left","right"):
            endpoint = r[side]; original = by_key.get(endpoint["content_key"])
            if original is None or any(endpoint[k] != original[k] for k in ("id","purpose","direction")):
                raise ValueError("bound economic evidence endpoint changed")
    doc, stats = component_forest(rows,pairs,allow_weak=allow_weak)
    examples = [dict(id=n["id"],level=n["level"],parent_id=n["parent_id"],support=n["support"],
        member_examples=[dict(content_key=k,semantic_text=by_key[k]["semantic_text"],
                             template_family=by_key[k]["template_family"]) for k in n["members"]]) for n in doc["nodes"]]
    report = dict(scope="training-only sparse evidence graph pilot; not encoder evaluation",status=doc["status"],
        statistics=stats,label_consistency=consistency,semantic_accuracy=None,independent_test=False,
        final_test_read=False, corpus_manifest_sha256=sha256_file(corpus/"manifest.json"),
        labels_sha256=sha256_file(labels), allow_weak_supervision=allow_weak,
        code_sha256={n:sha256_file(Path(__file__).with_name(n)) for n in
                     ("research_forest.py","evidence_graph.py","audit_relations.py")})
    out.mkdir(parents=True)
    for name,value in [("forest.json",doc),("report.json",report),("membership_examples.json",examples)]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus",type=Path,required=True)
    p.add_argument("--labels",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--allow-weak-supervision",action="store_true")
    a=p.parse_args()
    print(json.dumps(run(a.corpus,a.labels,a.out,allow_weak=a.allow_weak_supervision),indent=2))


if __name__ == "__main__":
    main()
