import json

import pytest

from zavozik_ml.category_discovery.corpus import read_rows
from zavozik_ml.category_discovery.public_transactions import qualify, ABOUT, LICENSE


def fixture(tmp_path):
    response = tmp_path / "response.json"
    response.write_text(json.dumps([
        dict(id=1, payer_edrpou="12345678", recipt_edrpou="87654321", payment_details="Оплата за електроенергію згідно договору", trans_date="2021-10-04T00:00:00", amount=10, payer_name="Not a feature", payer_account="Private field", kekv="Not a target"),
        dict(id=2, payer_edrpou="12345678", recipt_edrpou="1234567890", payment_details="Individual", trans_date="2021-10-04"),
    ], ensure_ascii=False))
    evidence = tmp_path / "license.json"
    evidence.write_text(json.dumps(dict(source_url=ABOUT, license="CC-BY-4.0", license_url=LICENSE, excerpt="fixture license statement")))
    return response, evidence


def test_public_data_preserves_ukrainian_letters_and_excludes_person_accounts_targets(tmp_path):
    response, evidence = fixture(tmp_path)
    out = tmp_path / "qualified"
    report = qualify(response, out, "2021-10-04", attribution_document=evidence)
    assert report["retained_rows"] == 1 and report["gold_labels"] == 0
    r = read_rows(out / "source_operations.jsonl")[0]
    assert r["purpose"] == "Оплата за електроенергію згідно договору"
    assert all(k not in r for k in ("payer_name", "payer_account", "amount", "kekv", "label", "category"))
    assert "12345678" not in r["company"] and "87654321" not in r["counterparty_group"]
    assert (out / "ATTRIBUTION.txt").is_file()
    assert report["training_approved_scope"] == "auxiliary_research_only"
    with pytest.raises(ValueError, match="overwrite"):
        qualify(response, out, "2021-10-04", attribution_document=evidence)


def test_public_snapshot_is_bound_to_actual_record_dates_and_license(tmp_path):
    response, evidence = fixture(tmp_path)
    with pytest.raises(ValueError, match="outside requested day"):
        qualify(response, tmp_path / "bad", "2021-10-05", attribution_document=evidence)
    assert not (tmp_path / "bad").exists()
    evidence.write_text(json.dumps(dict(source_url="https://example.invalid", license="unknown")))
    with pytest.raises(ValueError, match="license evidence"):
        qualify(response, tmp_path / "bad", "2021-10-04", attribution_document=evidence)
