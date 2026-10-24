import pytest

from zavozik_ml.category_discovery.normalization import analyze, semantic_text, content_key


@pytest.mark.parametrize("tail", [
    "Сумма 125 000,00 руб. Без НДС", "Сумма 125000-00. НДС 20% 25000-00",
    "Сумма: 125000.00 руб. В т.ч. НДС (20%) 25000,00 руб.",
    "НДС не облагается", "НДС: 25000-00 руб.",
])
def test_amount_and_vat_variants_do_not_inflate_support(tail):
    assert semantic_text("Оплата за ЛКМ. " + tail) == "оплата за лкм"


def test_document_variants_and_payment_stage_are_separate_axes():
    a = analyze("Окончательный расчет за автомобиль по счету № А-123/45 от 12.10.2024. Без НДС")
    b = analyze("Предоплата за автомобиль по счету № Б-987 от 13.11.2025. Сумма 100,00 руб.")
    assert a.semantic_text == b.semantic_text == "оплата за автомобиль"
    assert a.stages != b.stages
    assert content_key("out", a.semantic_text) == content_key("out", b.semantic_text)
    assert content_key("in", a.semantic_text) != content_key("out", a.semantic_text)


@pytest.mark.parametrize("purpose", ["", "Окончательный расчет", "Частичная оплата", "Оплата по УПД № 45 от 01.01.2025. Без НДС"])
def test_generic_payment_cannot_supply_economic_object(purpose):
    assert not analyze(purpose).usable


@pytest.mark.parametrize("left,right", [
    ("Перечисление заработной платы по реестру", "Перечисление арендной платы за земельные паи по реестру"),
    ("Выдача кредита на проведение полевых работ", "Субсидия на проведение полевых работ"),
    ("Погашение основного долга", "Уплата процентов по кредиту"),
    ("Оплата за автомобиль", "Оплата за автохимию"),
    ("Возврат суммы займа", "Выдача займа"),
    ("Перевод на свой счет", "Перевод не на свой счет"),
])
def test_cleanup_does_not_erase_economic_contrasts(left, right):
    assert semantic_text(left) != semantic_text(right)


def test_tax_object_credit_role_and_numbered_goods_survive():
    assert semantic_text("Уплата НДС за квартал") == "уплата ндс за квартал"
    assert "кредитной линии" in semantic_text("Проценты по договору кредитной линии № КЛ-123 от 02.03.2025")
    assert "пшеница 4 класса" in semantic_text("Оплата за пшеница 4 класса 12000,00 руб.")
    assert analyze("Возврат суммы займа").usable


def test_old_sealed_normalizer_remains_available():
    from zavozik_ml.category_discovery.corpus import TEXT_VERSION, semantic_text as legacy
    assert TEXT_VERSION == "purpose_only_structural_query_v1"
    assert "сумма" in legacy("Оплата за ЛКМ. Сумма 123,00 руб.")


def test_acquiring_summary_amounts_are_not_diverse_supports_or_zero_refunds():
    a = "Зачисление средств по операциям эквайринга. Мерчант №5416907. Дата реестра 18.02.2026. Сумма операций 100 065.37, комиссия 1 737.79, возврат покупки 0.00. НДС не облагается"
    b = a.replace("100 065.37", "54 002,18").replace("1 737.79", "899-00").replace("5416907", "123456")
    assert semantic_text(a) == semantic_text(b)
    assert not any(x.isdigit() for x in semantic_text(a))
    assert "возврат" not in semantic_text(a)
    assert "возврат покупки" in semantic_text(a.replace("0.00", "150.00"))


def test_bare_document_number_is_not_a_good_or_account_role():
    assert semantic_text("Оплата по счету 1026 от 09.01.2025 за поставку товара") == "оплата за поставку товара"
    assert "на счет" in semantic_text("Перевод на счет предпринимателя")
    assert "4 5 литра" in semantic_text("Масло 4.5 литра")


def test_debt_breakdown_is_evidence_not_amount_noise():
    a = "Погашение кредита по договору № КД-4995 от 11.03.2023: основной долг 2 097 669.07, проценты 61 810.51. НДС не облагается"
    b = a.replace("2 097 669.07", "128 123-00").replace("61 810.51", "1 000,00")
    assert semantic_text(a) == semantic_text(b) == "погашение кредита основной долг проценты"
    assert "проценты" not in semantic_text(a.replace("61 810.51", "0.00"))


def test_account_identifier_does_not_change_connectivity_object():
    a = "Оплата услуг связи и доступа в Интернет по лицевому счету 1006059 за октябрь 2024 г. В т.ч. НДС 20% - 981.67"
    b = a.replace("1006059", "9991234").replace("981.67", "1062-13")
    assert semantic_text(a) == semantic_text(b)
    assert "услуг связи" in semantic_text(a)
    assert "1006059" not in semantic_text(a)


def test_english_negation_is_not_a_number_marker():
    assert semantic_text("no refund") == "no refund"
    assert semantic_text("Оплата №123 за пшеницу") == "оплата за пшеницу"
