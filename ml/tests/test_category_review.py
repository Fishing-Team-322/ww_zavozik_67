import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('prepare_category_review',
    Path(__file__).parents[1]/'experiments/prepare_category_review.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def rows():
    return [{**dict.fromkeys(module.FIELDS, ''), 'operation_id': str(i),
             'payment_purpose': '' if i % 2 else 'Оплата товара',
             'label': 'supplier', 'prediction': 'tax', 'confidence': .99} for i in range(20)]


def test_blind_review_preserves_raw_data_without_label_leakage():
    data = rows()
    forms, cohorts = module.prepare(data, 5, 3, 42)
    assert len(forms) == len(cohorts) == 8
    assert list(cohorts.values()).count('random_operation') == 5
    assert list(cohorts.values()).count('empty_purpose_challenge') == 3
    source = {row['operation_id']: row for row in data}
    for form in forms:
        assert not {'label', 'prediction', 'confidence'} & form.keys()
        assert form['category'] == form['status'] == form['reviewer'] == ''
        assert all(form[key] == source[form['operation_id']][key] for key in module.FIELDS)
        if cohorts[form['operation_id']] == 'empty_purpose_challenge':
            assert not form['payment_purpose'].strip()
    assert module.prepare(list(reversed(data)), 5, 3, 42) == (forms, cohorts)


def test_review_rejects_ambiguous_ids_and_impossible_sample():
    with pytest.raises(ValueError, match='unique'):
        module.prepare(rows()+[rows()[0]], 5, 3, 42)
    with pytest.raises(ValueError, match='exceeds'):
        module.prepare(rows(), 21, 0, 42)
    with pytest.raises(ValueError, match='required'):
        module.prepare([{'operation_id': '1'}], 1, 0, 42)
    forms, cohorts = module.prepare(rows(), 20, 50, 42)
    assert len(forms) == 20 and set(cohorts.values()) == {'random_operation'}
