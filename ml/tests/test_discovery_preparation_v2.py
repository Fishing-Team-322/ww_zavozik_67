import csv
import json

import pytest

from zavozik_ml.category_discovery.corpus import read_rows
from zavozik_ml.category_discovery.preparation import prepare
from zavozik_ml.classify_v2.model import sha256_file


def fixture(tmp_path):
    source = tmp_path / "raw.csv"
    purposes = ["Оплата за ЛКМ. Сумма 123,00 руб.", "Оплата за ЛКМ. Сумма 456-00 руб.",
                "Погашение тела кредита", "Перечисление субсидии", "Возврат ошибочного платежа"]
    rows = [dict(operation_id=f"{c}-{i}", company_id=c, direction="out", payment_purpose=p,
                 category="DO NOT READ", label="DO NOT READ")
            for c in ("a", "b", "c") for i, p in enumerate(purposes)]
    with source.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    meta = tmp_path / "companies.json"
    meta.write_text(json.dumps(dict(source_sha256=sha256_file(source), train_companies=["a"],
                                    calibration_companies=["b"], test_companies=["c"])))
    return source, meta


def test_family_and_actual_token_closure_precedes_ownership(tmp_path):
    source, meta = fixture(tmp_path)
    def tokenize(texts):
        # Simulate a tokenizer truncation collision between unrelated purposes.
        return [[1] if ("субсидии" in t or "кредита" in t) else list(t.encode()) for t in texts]
    tokenizer = {"test@immutable": (tokenize, dict(max_length=128))}
    out = tmp_path / "prepared"
    report = prepare(source, meta, out, tokenizer, source_kind="case_synthetic")
    assert report["source_unique_direction_texts"] == 4
    assert report["independent_external_test"] is False
    assert all(not any(x.values()) for x in report["intersections"].values())
    registry = json.loads((out / "registry.json").read_text())
    assert registry["families"]["погашение тела кредита"] == registry["families"]["перечисление субсидии"]
    all_rows = [r for p in ("train", "calibration", "test") for r in read_rows(out / f"{p}.jsonl")]
    assert len(all_rows) == 5  # every family retained for exactly one company partition
    assert all("category" not in r and "label" not in r for r in all_rows)
    for p in ("train", "calibration", "test"):
        rows = read_rows(out / f"{p}_unique.jsonl")
        assert len({r["content_key"] for r in rows}) == len(rows)
        for r in rows:
            if r["semantic_text"] == "оплата за лкм":
                assert r["count"] == 2  # one density point; never two independent supports
    with pytest.raises(ValueError, match="overwrite"):
        prepare(source, meta, out, tokenizer, source_kind="case_synthetic")
    other = tmp_path / "again"
    assert prepare(source, meta, other, tokenizer, source_kind="case_synthetic") == report
    assert (out / "train_unique.jsonl").read_bytes() == (other / "train_unique.jsonl").read_bytes()


def test_source_and_company_binding(tmp_path):
    source, meta = fixture(tmp_path)
    document = json.loads(meta.read_text())
    document["calibration_companies"].append("a")
    meta.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="company overlap"):
        prepare(source, meta, tmp_path / "bad", {"x": (lambda x: x, {})}, source_kind="case_synthetic")
    assert not (tmp_path / "bad").exists()
