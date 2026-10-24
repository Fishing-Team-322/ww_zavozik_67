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


@pytest.fixture
def validator(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'experiments'))
    import validate_category_review
    return validate_category_review


def completed_forms():
    from copy import deepcopy
    forms, cohorts = module.prepare(rows(), 5, 0, 42)
    first, second = deepcopy(forms), deepcopy(forms)
    for forms, reviewer in [(first, 'Reviewer A'), (second, 'Reviewer B')]:
        for row in forms:
            row.update(status='labeled', category='supplier', reviewer=reviewer,
                       rationale='Payment for goods, supported by document')
    return first, second, {row['operation_id']: row for row in rows()}, cohorts


def test_empty_forms_cannot_create_human_labels(validator):
    forms, cohorts = module.prepare(rows(), 5, 3, 42)
    candidates, queue, counts = validator.reconcile(forms, forms,
        {row['operation_id']: row for row in rows()}, cohorts)
    assert not candidates and len(queue) == 8
    assert all(row['outcome'] == 'pending' for row in queue)
    assert counts['random_operation']['agreement_among_both_labeled'] is None


def test_agreement_disagreement_and_insufficient_context_are_separate(validator):
    first, second, originals, cohorts = completed_forms()
    second[0]['category'] = 'services'
    second[1].update(status='unresolved', category='', rationale='Need invoice')
    candidates, queue, counts = validator.reconcile(first, second, originals, cohorts)
    assert len(candidates) == 3
    assert {row['outcome'] for row in queue} == {'unresolved', 'disagreement'}
    assert counts['random_operation']['both_labeled'] == 4
    assert counts['random_operation']['agreement_among_both_labeled'] == .75


@pytest.mark.parametrize('change,match', [
    ({'amount': '999'}, 'source fields'),
    ({'category': 'not_a_category'}, 'invalid category'),
    ({'reviewer': ' reviewer a '}, 'independent reviewer'),
    ({'status': 'unresolved'}, 'cannot carry a category'),
    ({'rationale': ''}, 'rationale'),
])
def test_review_rejects_invalid_or_biased_forms(validator, change, match):
    first, second, originals, cohorts = completed_forms()
    second[0].update(change)
    with pytest.raises(ValueError, match=match):
        validator.reconcile(first, second, originals, cohorts)


def test_review_rejects_missing_and_duplicate_responses(validator):
    first, second, originals, cohorts = completed_forms()
    with pytest.raises(ValueError, match='every selected'):
        validator.reconcile(first, second[:-1], originals, cohorts)
    with pytest.raises(ValueError, match='duplicate'):
        validator.reconcile(first, second+[second[0]], originals, cohorts)
