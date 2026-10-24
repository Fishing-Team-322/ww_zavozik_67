import json
from pathlib import Path

import pytest

from zavozik_ml.classify.text import Op
from zavozik_ml.classify_v2.taxonomy import Taxonomy
from zavozik_ml.classify_v2.text import Operation, dedupe_key, encoder_text, normalize
from zavozik_ml.classify_v2.weak_labels import annotate


@pytest.mark.parametrize("purpose,name,direction,channel,tags", [
    ("Оплата материалов цифровыми рублями по QR", "Поставщик", "out", "digital_ruble", set()),
    ("Зарплата на кошелек ЦР за май", "", "out", "digital_ruble", {"recurring_like"}),
    ("Предоплата через СБП", "", "out", "sbp", {"prepayment"}),
    ("Зачисление выручки по эквайрингу", "Банк", "in", "card_acquiring", set()),
    ("Инкассация наличной выручки", "Банк", "in", "cash", set()),
    ("Выплата за продажи", "Ozon", "in", "marketplace_payout", set()),
    ("Комиссия банка за ведение счета", "Банк", "out", "internal_bank", set()),
    ("Комиссия маркетплейса за логистику", "Ozon", "out", "unknown", set()),
    ("Перевод по реквизитам", "", "out", "bank_transfer", set()),
    ("Оплата услуг", "Банк", "out", "unknown", set()),
    ("", "Банк", "out", "unknown", set()),
    ("???", "", "in", "unknown", set()),
    ("Оплата по договору № А-73 от 03.02.2026", "", "out", "bank_transfer", {"with_document"}),
    ("Оплата по договору № А-73", "", "out", "bank_transfer", set()),
    ("Частичная оплата за июль", "", "out", "unknown", {"partial_payment", "recurring_like"}),
    ("Доплата за ремонт", "", "out", "unknown", {"final_payment"}),
    ("НДФЛ за август", "Казначейство", "out", "unknown", {"budget_payment", "recurring_like"}),
    ("Возврат оплаты за товар", "", "out", "unknown", {"refund"}),
    ("Возврат займа учредителю", "", "out", "unknown", {"owner_money"}),
    ("Взыскание по исполнительному листу", "ФССП", "out", "unknown", {"enforcement"}),
    ("Оплата товара. Без НДС", "", "out", "unknown", set()),
    ("Оплата товара. Без налога (НДС)", "", "out", "unknown", set()),
    ("Оплата товара. В том числе НДС 20% 100.00", "", "out", "unknown", set()),
    ("Перечисление остатка в связи с закрытием счета", "Банк", "out", "unknown", {"owner_money"}),
    ("Возврат остатка с собственного счета", "", "in", "unknown", {"owner_money"}),
])
def test_weak_channel_and_tags(purpose, name, direction, channel, tags):
    result = annotate(Operation(direction, purpose, name), Taxonomy.load())
    assert result.channel == channel
    assert set(result.tags) == tags


def test_taxonomy_matches_current_go_categories_and_attributes():
    from zavozik_ml.classify.text import CATEGORIES
    t = Taxonomy.load()
    assert t.categories == CATEGORIES
    assert t.category("supplier")["attributes"]["flow"] == "business"
    assert t.category("owner_loan")["attributes"]["flow"] == "owner"
    assert t.category("salary")["attributes"]["mandatory"]
    assert t.without({"leasing"}).categories == tuple(k for k in t.categories if k != "leasing")
    d = t.document.copy()
    d["taxonomy_version"] = ""
    with pytest.raises(ValueError):
        Taxonomy(d)


def test_normalizer_keeps_channel_and_never_inn():
    a = Operation.from_legacy(Op("out", "Оплата цифровыми рублями за товар №125 от 02.01.2026", "ООО Вектор", "7701234567", 900))
    b = Operation.from_legacy(Op("out", a.purpose, a.counterparty_name, "7809876543", 900))
    assert encoder_text(a) == encoder_text(b)
    assert "цифровыми рублями" in encoder_text(a)
    assert "7701234567" not in encoder_text(a)
    assert normalize("Oплата") == "оплата"
    assert "неизвестна" in encoder_text(Operation("in", amount=float("nan")))


def test_template_dedupe_removes_document_and_name_shortcuts():
    a = Operation("out", "Оплата товара №123 от 01.01.2026", "ООО Первый", amount=100)
    b = Operation("out", "Оплата товара №456 от 02.02.2026", "ООО Второй", amount=20000)
    assert dedupe_key(a) == dedupe_key(b)
    assert dedupe_key(Operation("out", "", "Энергосбыт")) != dedupe_key(Operation("out", "", "Банк"))


def test_frozen_fixture_integrity():
    import hashlib
    import csv
    from zavozik_ml.classify_v2 import taxonomy
    p = Path(taxonomy.__file__).with_name("heldout_v1.tsv")
    manifest = json.loads(p.with_suffix(".manifest.json").read_text())
    assert hashlib.sha256(p.read_bytes()).hexdigest() == manifest["sha256"]
    rows = list(csv.DictReader(p.open(), delimiter="\t"))
    t = Taxonomy.load()
    assert len(rows) == manifest["rows"] >= 150
    for r in rows:
        assert r["category"] in t.categories
        assert r["channel"] in t.channels
        assert set(filter(None, r["tags"].split(","))) <= set(t.tags)
