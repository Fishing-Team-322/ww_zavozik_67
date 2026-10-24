import csv
import json

import pytest

from zavozik_ml.category_discovery.corpus import prepare, read_rows
from zavozik_ml.category_discovery.review import create, score
from zavozik_ml.classify_v2.model import sha256_file
from zavozik_ml.classify_v2.splitting import signatures, template_text


def test_corpus_ignores_labels_and_keeps_only_owner_company_rows(tmp_path):
    source = tmp_path / "source.csv"
    rows = [dict(operation_id=str(i), company_id=c, direction="Списание", payment_purpose=p, label="arbitrary_wrong_target")
            for i, (c, p) in enumerate([("a", "аренда"), ("b", "налоги"), ("c", "зарплата"), ("b", "аренда")])]
    with source.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, delimiter=";", fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    families, owners = {}, {}
    for i, (p, owner) in enumerate([("аренда", "train"), ("налоги", "calibration"), ("зарплата", "test")]):
        family = str(i)
        for alias in signatures(p):
            families[alias] = family
        owners[family] = owner
    registry = frozen / "template_registry.json"
    registry.write_text(json.dumps(dict(families=families, owners=owners)))
    (frozen / "data_manifest.json").write_text(json.dumps(dict(source_sha256=sha256_file(source),
        template_registry_sha256=sha256_file(registry), train_companies=["a"], calibration_companies=["b"], test_companies=["c"])))
    out = tmp_path / "new"
    report = prepare(source, frozen, out)
    assert report["calibration"]["purged_rows"] == 1
    assert report["fit_targets"] == "none" and report["synthetic_rows"] == 0
    for part in ("train", "calibration", "test"):
        result = read_rows(out / f"{part}.jsonl")
        assert len(result) == 1
        assert not any(k in result[0] for k in ("label", "category", "weight", "tags", "channel"))
    assert all(not any(checks.values()) for checks in report["intersections"].values())
    with pytest.raises(ValueError, match="overwrite"):
        prepare(source, frozen, out)


def test_blind_review_has_no_prefilled_answers_and_binds_inputs(tmp_path):
    rows = [dict(id=str(i), company=str(i), template_family=str(i), direction="out", purpose="purpose"+str(i)) for i in range(5)]
    assignments = [dict(category_id=c, taxonomy_version="v1") for c in ("a", "a", "b", "b", None)]
    root = tmp_path / "review"
    create(rows, assignments, root)
    blind = read_rows(root / "blind_pairs.jsonl")
    assert all(r["judgment"] is None and "predicted_same" not in r for r in blind)
    result = score(root, root / "blind_pairs.jsonl")
    assert result["selected_pair_precision"] is None
    assert result["unreviewed"] == len(blind)
    blind[0]["judgment"] = "same"
    output = tmp_path / "reviewed.jsonl"
    output.write_text("\n".join(json.dumps(r) for r in blind))
    with pytest.raises(ValueError, match="reviewer"):
        score(root, output)
    blind[0]["reviewer"] = "unit-test reviewer"
    blind[0]["left"]["purpose"] += "changed"
    output.write_text("\n".join(json.dumps(r) for r in blind))
    with pytest.raises(ValueError, match="input changed"):
        score(root, output)
