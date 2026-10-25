from zavozik_ml.category_discovery.relation_guard import conflict


def test_employee_payment_is_not_the_contribution_calculated_on_it():
    assert conflict('на вклади відпускні за жовтень','сплата єдин заг об соц страх з відпускних','coarse')
    assert conflict('військовий збір із зарплати','пдфо із зарплати','fine')
    assert not conflict('військовий збір із зарплати','пдфо із зарплати','coarse')
    assert not conflict('пдфо із лікарняних за вересень','податок з доходів фізичних осіб з лікарняних за серпень','fine')
    assert conflict('фінансування мат забезпечення з твп','єдиний соціальний внесок','coarse')


def test_generic_goods_or_works_cannot_authorize_a_specific_subgroup():
    from zavozik_ml.category_discovery.relation_guard import conflict
    assert conflict('оплата за товар по договору','оплата за мебельную фурнитуру','fine')=='specific_object_not_established'
    assert conflict('оплата за выполненные работы','оплата за ремонт автомобиля','fine')=='specific_object_not_established'
    assert conflict('оплата за услуги фулфилмента','оплата за услуги фулфилмента по договору','fine') is None
    assert conflict('оплата за товар по договору','оплата за мебельную фурнитуру','coarse') is None


def test_numeric_budget_prefix_does_not_hide_statutory_abbreviation():
    from zavozik_ml.category_discovery.relation_guard import conflict,obligation_evidence
    assert obligation_evidence('8000 00єсв нарахований на зарплату')[0]=={'social_contribution'}
    assert conflict('8000 00єсв нарахований на зарплату','перечисление зарплаты','coarse')
    assert not obligation_evidence('зарплата за вересень податки i збори перерахованi')[1]
