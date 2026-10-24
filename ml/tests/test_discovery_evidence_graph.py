import itertools

import pytest

from zavozik_ml.category_discovery.evidence_graph import fit, assign


def row(k, text=None):
    return dict(content_key=k, semantic_text=text or k, company=k, companies=[k],
                template_family=k, usable=True, direction="out")


def ev(a, b, coarse="same", fine="same"):
    return dict(left=dict(content_key=a), right=dict(content_key=b), coarse=coarse, fine=fine,
                provenance="human_consensus")


def test_no_forced_economic_parent_and_coarse_only_path():
    rows = [row(k) for k in ("salary1", "salary2", "rent1", "rent2", "principal", "interest")]
    evidence = [ev("salary1", "salary2"), ev("rent1", "rent2"), ev("principal", "interest", fine="different")]
    doc = fit(rows, evidence)
    parents = [n for n in doc["nodes"] if n["level"] == "coarse"]
    assert len(parents) == 3 and all(n["parent_id"] is None for n in parents)
    assert len([n for n in doc["nodes"] if n["level"] == "fine"]) == 2
    query = row("new")
    result = assign(doc, query, [ev("new", "principal", fine="uncertain"), ev("new", "interest", fine="uncertain")])
    assert result["status"] == "coarse_only" and result["category_id"] is None
    assert len(result["category_path"]) == 1
    result = assign(doc, query, [ev("new", "salary1"), ev("new", "salary2")])
    assert result["status"] == "assigned" and len(result["category_path"]) == 2


def test_a_positive_bridge_does_not_merge_a_negative_cross_pair():
    doc = fit([row(k) for k in "abc"], [ev("a", "b"), ev("b", "c"), ev("a", "c", "different", "different")])
    assert all(len(n["members"]) <= 2 for n in doc["nodes"])
    assert len(doc["unassigned"]) == 1


def test_missing_evidence_abstains_and_generic_text_never_matches():
    doc = fit([row("a"), row("b")], [ev("a", "b")])
    assert assign(doc, row("new"), [ev("new", "a")])["status"] == "unknown"
    assert assign(doc, dict(row("new"), usable=False), [ev("new", "a"), ev("new", "b")])["status"] == "insufficient_text"


def test_multiple_compatible_coarse_groups_do_not_get_arbitrary_choice():
    doc = fit([row(k) for k in "abcd"], [ev("a", "b"), ev("c", "d")])
    assert assign(doc, row("new"), [ev("new", k) for k in "abcd"])["status"] == "ambiguous"


def test_duplicates_and_unverified_or_inconsistent_evidence_rejected():
    with pytest.raises(ValueError, match="once"):
        fit([row("a"), row("a")], [])
    with pytest.raises(ValueError, match="provenance"):
        fit([row("a"), row("b")], [dict(ev("a", "b"), provenance="agent_guess")])
    with pytest.raises(ValueError, match="contradictory"):
        fit([row("a"), row("b")], [ev("a", "b", "different", "same")])


def test_duplicate_operations_cannot_satisfy_independent_family_support():
    rows = [dict(row("a"), template_family="same"), dict(row("b"), template_family="same")]
    assert fit(rows, [ev("a", "b")])["nodes"] == []
