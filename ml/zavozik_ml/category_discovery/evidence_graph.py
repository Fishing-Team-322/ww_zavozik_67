"""Research hierarchy requiring economic pair evidence, not forced linkage.

The verifier is an explicit dependency: absent/uncertain evidence never means
same. No named seeds, category vocabulary or target cluster count. Complete
cross-member checks prevent a single bridge from joining incompatible groups.
This is not yet wired into the sealed v1 runtime or a claim of verifier quality.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json


def identity(prefix, members):
    value = json.dumps(sorted(members), separators=(",", ":"))
    return prefix + hashlib.sha256(value.encode()).hexdigest()[:24]


def pair_key(a, b):
    return tuple(sorted((a, b)))


def evidence_index(rows, *, allow_weak=False):
    index = {}
    for r in rows:
        a, b = r["left"]["content_key"], r["right"]["content_key"]
        key = pair_key(a, b)
        if a == b or key in index:
            raise ValueError("duplicate/self economic evidence")
        weak = r.get("provenance") == "local_model_weak"
        if weak and (not allow_weak or r.get("reviewer_kind") != "local_model"):
            raise ValueError("weak evidence provenance requires explicit research opt-in and local_model reviewer")
        if not weak and r.get("provenance") not in ("human_consensus", "calibrated_verifier"):
            raise ValueError("economic evidence requires explicit verified provenance")
        if r.get("provenance") == "calibrated_verifier" and not r.get("calibration_version"):
            raise ValueError("verifier calibration version required")
        coarse, fine = r["coarse"], r["fine"]
        if coarse not in ("same", "different", "uncertain") or fine not in ("same", "different", "uncertain"):
            raise ValueError("invalid economic relation")
        if fine == "same" and coarse != "same" or coarse == "different" and fine != "different":
            raise ValueError("contradictory economic levels")
        index[key] = r
    return index


def partitions(keys, relation):
    groups = [(k,) for k in sorted(keys)]
    while True:
        # A proposed merge must have same evidence for EVERY cross member.
        # Missing data and a high mean cosine are not permission to merge.
        candidates = [(a+b, i, j) for i, a in enumerate(groups) for j, b in enumerate(groups) if i < j
                      and all(relation(x, y) == "same" for x in a for y in b)]
        if not candidates:
            return groups
        members, i, j = min(candidates, key=lambda c: (-len(c[0]), sorted(c[0])))
        groups = [g for n, g in enumerate(groups) if n not in (i, j)] + [tuple(sorted(members))]
        groups.sort()


def fit(rows, evidence, *, min_members=2, min_companies=2, min_families=2, allow_weak=False):
    if min(min_members, min_companies, min_families) < 1:
        raise ValueError("positive support requirements required")
    by_id = {}
    for r in rows:
        if not r["usable"]:
            continue
        key = r["content_key"]
        if r["direction"] not in ("in", "out"):
            raise ValueError("invalid direction")
        if key in by_id:
            raise ValueError("density input must contain exact semantic texts once")
        by_id[key] = r
    index = evidence_index(evidence, allow_weak=allow_weak)
    contains_weak = any(r.get("provenance") == "local_model_weak" for r in evidence)
    prefix = "weak-research-" if contains_weak else "economic-"
    if any(a not in by_id or b not in by_id for a, b in index):
        raise ValueError("evidence endpoint outside training density cohort")
    def relation(a, b, level):
        if by_id[a]["direction"] != by_id[b]["direction"]:
            return "different"
        return index.get(pair_key(a, b), {}).get(level, "uncertain")
    def support(members):
        companies = {c for k in members for c in by_id[k].get("companies", [by_id[k]["company"]])}
        families = {by_id[k]["template_family"] for k in members}
        return dict(members=len(members), companies=len(companies), families=len(families))
    def supported(members):
        s = support(members)
        return s["members"] >= min_members and s["companies"] >= min_companies and s["families"] >= min_families
    nodes, assigned = [], set()
    for coarse in partitions(by_id, lambda a, b: relation(a, b, "coarse")):
        if not supported(coarse):
            continue
        cid = identity(prefix+"coarse-", coarse)
        # Titles intentionally remain proposals from actual member texts;
        # naming cannot repair membership and is not pair evidence.
        examples = sorted({by_id[k]["semantic_text"] for k in coarse})
        node = dict(id=cid, level="coarse", parent_id=None, direction=by_id[coarse[0]]["direction"],
                    members=list(coarse), support=support(coarse), title_proposals=examples[:3])
        nodes.append(node)
        assigned.update(coarse)
        for fine in partitions(coarse, lambda a, b: relation(a, b, "fine")):
            if not supported(fine):
                continue
            nodes.append(dict(id=identity(prefix+"fine-", fine), level="fine", parent_id=cid,
                direction=by_id[fine[0]]["direction"], members=list(fine), support=support(fine),
                title_proposals=sorted({by_id[k]["semantic_text"] for k in fine})[:3]))
    document = dict(schema="weak_research_evidence_forest_v1" if contains_weak else "economic_evidence_forest_v2", nodes=nodes,
                    unassigned=sorted(set(by_id) - assigned),
                    policy="complete supplied coarse/fine compatibility; no forced economic root",
                    contains_weak_evidence=contains_weak,
                    evidence_provenance=dict(Counter(r["provenance"] for r in evidence)),
                    semantic_accuracy=None, independent_test=False,
                    support_requirements=dict(min_members=min_members, min_companies=min_companies, min_families=min_families),
                    evidence_sha256=hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                    status="weak_research_not_deployable" if contains_weak else "research; correctness depends on independently validated verifier")
    document["hierarchy_version"] = identity("economic-forest-", [json.dumps(document, sort_keys=True)])
    return document


def assign(document, query, evidence, *, allow_weak=False):
    """Require compatibility with all members; coarse-only is a real output.

    `evidence` contains verifier responses between this new content and training
    members. No centroid similarity fallback. Large groups will need a measured
    representative/verification strategy before online deployment.
    """
    if document.get("contains_weak_evidence") and not allow_weak:
        raise ValueError("weak research hierarchy requires explicit research opt-in")
    empty = dict(status="unknown", category_id=None, coarse_category_id=None, category_path=[],
                 contains_weak_evidence=document.get("contains_weak_evidence", False) or any(
                     r.get("provenance") == "local_model_weak" for r in evidence),
                 hierarchy_version=document["hierarchy_version"])
    if not query.get("usable"):
        return dict(empty, status="insufficient_text")
    index = evidence_index(evidence, allow_weak=allow_weak)
    def matches(node, level):
        return node["direction"] == query["direction"] and all(
            index.get(pair_key(query["content_key"], k), {}).get(level) == "same" for k in node["members"])
    parents = [n for n in document["nodes"] if n["level"] == "coarse" and matches(n, "coarse")]
    if len(parents) != 1:
        return dict(empty, status="ambiguous" if parents else "unknown")
    parent = parents[0]
    leaves = [n for n in document["nodes"] if n["parent_id"] == parent["id"] and matches(n, "fine")]
    if len(leaves) > 1:
        return dict(empty, status="ambiguous")
    if not leaves:
        return dict(empty, status="coarse_only", coarse_category_id=parent["id"], category_path=[parent["id"]])
    return dict(empty, status="assigned", category_id=leaves[0]["id"], coarse_category_id=parent["id"],
                category_path=[parent["id"], leaves[0]["id"]])
