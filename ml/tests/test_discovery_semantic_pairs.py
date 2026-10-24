import json

import pytest

from zavozik_ml.category_discovery.corpus import read_rows, write_rows
from zavozik_ml.category_discovery.preparation import PROTOCOL
from zavozik_ml.category_discovery.semantic_pairs import sample, consensus, contradictions
from zavozik_ml.classify_v2.model import sha256_file


def review_fixture(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    meta = dict(protocol=PROTOCOL, source_kind="case_synthetic")
    for part in ("train", "calibration", "test"):
        rows = [dict(id=f"{part}-{i}", content_key=f"{part}-key-{i}", template_family=f"{part}-family-{i}",
                     company=str(i), companies=[str(i)], direction="out", purpose=f"оплата за предмет {i}",
                     semantic_text=f"оплата за предмет {i}", usable=True) for i in range(4)]
        path = corpus / f"{part}_unique.jsonl"
        write_rows(path, rows)
        meta[part] = dict(unique_sha256=sha256_file(path))
    (corpus / "manifest.json").write_text(json.dumps(meta))
    review = tmp_path / "review"
    report = sample(corpus, review, per_partition=10)
    return review, report


def answers(review, tmp_path, reviewer, kind="human", judgment=("same", "different")):
    rows = read_rows(review / "train_blind.jsonl")
    for r in rows:
        r.update(coarse=judgment[0], fine=judgment[1], rationale="Same broad nature, different explicit object",
                 reviewer=reviewer, reviewer_kind=kind)
    path = tmp_path / (reviewer + ".jsonl")
    write_rows(path, rows)
    return path


def test_two_level_pairs_are_blind_and_consensus_does_not_make_external_gold(tmp_path):
    review, report = review_fixture(tmp_path)
    assert report["partitions"]["train"]["pairs"] == 6
    rows = read_rows(review / "train_blind.jsonl")
    assert all(r["coarse"] is None and r["fine"] is None for r in rows)
    a = answers(review, tmp_path, "reviewer-A")
    b = answers(review, tmp_path, "reviewer-B")
    result = consensus(review, "train", [a, b], tmp_path / "consensus")
    assert result["accepted"] == 6 and result["status"] == "PASS"
    assert result["source_kind"] == "case_synthetic" and not result["independent_external_test"]
    assert all(r["coarse"] == "same" and r["fine"] == "different" for r in read_rows(tmp_path / "consensus/pairs.jsonl"))


def test_agent_votes_and_single_human_are_not_two_human_consensus(tmp_path):
    review, _ = review_fixture(tmp_path)
    a = answers(review, tmp_path, "A")
    b = answers(review, tmp_path, "B", kind="agent")
    result = consensus(review, "train", [a, b], tmp_path / "consensus")
    assert result["accepted"] == 0 and result["weak_votes_excluded"] == 6
    assert result["status"] == "NO_LABELS"
    with pytest.raises(ValueError, match="repeated reviewer"):
        consensus(review, "train", [a, a], tmp_path / "duplicates")


def test_judgments_bind_input_and_hierarchy_logic(tmp_path):
    review, _ = review_fixture(tmp_path)
    a = answers(review, tmp_path, "A", judgment=("different", "same"))
    with pytest.raises(ValueError, match="fine same"):
        consensus(review, "train", [a], tmp_path / "invalid")
    a = answers(review, tmp_path, "A")
    rows = read_rows(a)
    rows[0]["left"]["purpose"] += " changed"
    write_rows(a, rows)
    with pytest.raises(ValueError, match="input changed"):
        consensus(review, "train", [a], tmp_path / "changed")


def test_transitive_cannot_link_is_rejected_without_silent_repair():
    def row(a, b, judgment):
        return dict(pair_id=a+b, left=dict(content_key=a), right=dict(content_key=b), coarse=judgment, fine=judgment)
    result = contradictions([row("a", "b", "same"), row("b", "c", "same"), row("a", "c", "different")])
    assert {r["level"] for r in result} == {"coarse", "fine"}


def test_disagreeing_reviewers_require_adjudication(tmp_path):
    review, _ = review_fixture(tmp_path)
    a = answers(review, tmp_path, "A")
    b = answers(review, tmp_path, "B", judgment=("different", "different"))
    result = consensus(review, "train", [a, b], tmp_path / "conflicts")
    assert result["accepted"] == 0 and len(result["disagreements"]) == 6
    assert result["status"] == "REVIEW_REQUIRED"


def test_two_level_ui_is_blind_offline_and_escapes_source_text(tmp_path):
    from zavozik_ml.category_discovery.semantic_review_ui import build
    review, _ = review_fixture(tmp_path)
    rows = read_rows(review / "train_blind.jsonl")
    rows[0]["left"]["purpose"] = '</script><script>alert("raw input")</script>'
    path = review / "train_blind.jsonl"
    write_rows(path, rows)
    meta = json.loads((review / "manifest.json").read_text())
    meta["partitions"]["train"]["blind_sha256"] = sha256_file(path)
    (review / "manifest.json").write_text(json.dumps(meta))
    out = tmp_path / "review.html"
    build(review, "train", out)
    html = out.read_text()
    assert '</script><script>alert("raw input")' not in html
    assert "\\u003c/script>" in html
    assert '"coarse": null' in html and '"fine": null' in html
    assert "private_sampling" not in html and "predicted_same" not in html
    assert "fetch(" not in html and "https://" not in html and "http://" not in html
    assert 'value="agent"' in html and 'value="human"' in html
