from zavozik_ml.category_discovery.public_corpus import analyze, TEXT_VERSION


def test_public_normalizer_preserves_ukrainian_object_role_and_negation():
    a = analyze("Оплата за електроенергію згідно договору №А-123 від 12.03.2021. Сума 1200,00 грн. Без ПДВ")
    b = analyze("Оплата за електроенергію згідно договору №Б-345 від 14.05.2022. Сума 2400-00 грн. Без ПДВ")
    assert a.semantic_text == b.semantic_text
    assert "електроенергію" in a.semantic_text and "згідно" in a.semantic_text
    assert a.usable and a.text_version == TEXT_VERSION
    assert "не" in analyze("Кошти не є оплатою оренди").semantic_text
    assert analyze("Повернення позики").semantic_text != analyze("Надання позики").semantic_text


def test_budget_codes_masked_records_do_not_become_categories():
    a = analyze("КЕКВ xxxx; за електроенергію. Без ПДВ")
    b = analyze("КЕКВ 2273; за електроенергію. Без ПДВ")
    assert a.semantic_text == b.semantic_text == "за електроенергію"
    assert not analyze("xxxx;xxxx;оплата згідно договору").usable
    assert "4 класу" in analyze("Пшениця 4 класу").semantic_text


def test_pdv_as_the_tax_object_is_not_erased():
    a = analyze("Сплата ПДВ за період")
    assert "пдв" in a.semantic_text and a.usable
