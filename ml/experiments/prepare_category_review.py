"""Create blind human-review forms; never infer or prefill gold labels.

The random-operation cohort and a separate empty-purpose challenge cohort must
be reported separately. The source case is already inspected/trained on, so
human review can improve labels but cannot make it an unseen model benchmark.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

from zavozik_ml.classify.text import CATEGORIES

FIELDS = ('company_id', 'operation_id', 'operation_date', 'amount', 'direction',
          'counterparty_inn', 'counterparty_name', 'payment_purpose')


def prepare(rows: list[dict], random_count: int, empty_count: int, seed: int):
    if random_count < 1 or empty_count < 0:
        raise ValueError('random_count must be positive and empty_count nonnegative')
    if any(not set(FIELDS) <= row.keys() for row in rows):
        raise ValueError('missing required source fields')
    ids = [row['operation_id'] for row in rows]
    if any(not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError('operation_id must be nonempty and unique')
    if random_count > len(rows):
        raise ValueError('random cohort exceeds population')
    ordered = sorted(rows, key=lambda row: row['operation_id'])
    rng = random.Random(seed)
    uniform = rng.sample(ordered, random_count)
    selected = {row['operation_id'] for row in uniform}
    empty = [row for row in ordered if row['operation_id'] not in selected
             and not row['payment_purpose'].strip()]
    challenge = rng.sample(empty, min(empty_count, len(empty)))
    cohorts = {row['operation_id']: 'random_operation' for row in uniform}
    cohorts.update({row['operation_id']: 'empty_purpose_challenge' for row in challenge})
    mixed = uniform + challenge
    rng.shuffle(mixed)
    # Whitelist raw fields: rule/teacher/model predictions must not bias annotators.
    forms = [{**{key: row[key] for key in FIELDS},
              'reviewer': '', 'status': '', 'category': '', 'rationale': '', 'evidence_ref': ''}
             for row in mixed]
    return forms, cohorts


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=root/'cashflow_dataset_participants/all_operations.csv')
    parser.add_argument('--out', type=Path, required=True, help='new directory; refuses overwrite')
    parser.add_argument('--random-count', type=int, default=200)
    parser.add_argument('--empty-count', type=int, default=50)
    parser.add_argument('--seed', type=int, default=20261024)
    args = parser.parse_args()
    with args.data.open(encoding='utf-8-sig', newline='') as source:
        rows = list(csv.DictReader(source, delimiter=';'))
    forms, cohorts = prepare(rows, args.random_count, args.empty_count, args.seed)
    args.out.mkdir(parents=True, exist_ok=False)
    payload = ''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in forms)
    for reviewer in ('a', 'b'):
        (args.out/f'reviewer_{reviewer}.jsonl').write_text(payload, encoding='utf-8')
    metadata = {'source_sha256': hashlib.sha256(args.data.read_bytes()).hexdigest(),
                'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'seed': args.seed, 'population_operations': len(rows), 'selected_operations': len(forms),
                'cohorts': cohorts, 'requested_random_count': args.random_count,
                'requested_empty_count': args.empty_count, 'categories': list(CATEGORIES),
                'labels_prefilled': False,
                'limitation': 'Previously inspected/trained-on synthetic case. No independent external test. '
                              'Challenge oversampling must not be pooled into random-cohort accuracy.'}
    (args.out/'selection_manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n')
    (args.out/'README.txt').write_text(
        'Дайте reviewer_a.jsonl и reviewer_b.jsonl двум проверяющим независимо.\n'
        'Не показывайте им прогнозы модели, правила и selection_manifest до завершения.\n'
        'Заполняйте reviewer, status, category, rationale, evidence_ref; исходные поля не меняйте.\n'
        'status: labeled или unresolved. Для unresolved оставьте category пустой и опишите,\n'
        'каких первичных документов не хватает. Не угадывайте смысл по названию банка.\n'
        'other — экономический смысл установлен, но нет подходящей категории; это не\n'
        'замена unresolved при недостатке информации. Способ платежа не задаёт категорию.\n'
        'Категории: '+', '.join(CATEGORIES)+'.\n'
        'После независимой разметки согласуйте расхождения с третьим проверяющим/документами.\n'
        'Считайте долю unresolved, согласие и ошибки отдельно для случайной и сложной когорты.\n'
        'Это исправление слабых меток изученного кейса, а не независимый тест модели.\n',
        encoding='utf-8')
    print(json.dumps({'output': str(args.out), 'operations': len(forms), 'human_labels': 0}))


if __name__ == '__main__':
    main()
