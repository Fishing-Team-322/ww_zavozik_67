"""Validate blind human forms and separate agreement from adjudication work.

No model predictions or weak labels are read. Matching human labels are only
consensus candidates: this tool cannot verify reviewer independence or evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from prepare_category_review import FIELDS
from zavozik_ml.classify.text import CATEGORIES


def validate_form(forms, originals, cohorts):
    indexed = {}
    for row in forms:
        key = row.get('operation_id')
        if key in indexed or key not in cohorts or key not in originals:
            raise ValueError(f'duplicate or unknown operation_id: {key}')
        if any(row.get(field) != originals[key].get(field) for field in FIELDS):
            raise ValueError(f'source fields changed: {key}')
        fields = ('status', 'category', 'reviewer', 'rationale', 'evidence_ref')
        if any(not isinstance(row.get(field), str) for field in fields):
            raise ValueError(f'missing/nontext review fields: {key}')
        status, category = row['status'], row['category']
        if status not in ('', 'labeled', 'unresolved'):
            raise ValueError(f'invalid status: {key}')
        if status and (not row['reviewer'].strip() or not row['rationale'].strip()):
            raise ValueError(f'completed review needs reviewer and rationale: {key}')
        if status == 'labeled' and category not in CATEGORIES:
            raise ValueError(f'invalid category: {key}')
        if status != 'labeled' and category:
            raise ValueError(f'pending/unresolved row cannot carry a category: {key}')
        indexed[key] = row
    if set(indexed) != set(cohorts):
        raise ValueError('form must contain every selected operation, including pending rows')
    return indexed


def reconcile(first, second, originals, cohorts):
    a, b = (validate_form(rows, originals, cohorts) for rows in (first, second))
    candidates, queue = [], []
    counts = {cohort: dict(total=0, pending=0, unresolved=0, disagreement=0,
                         consensus=0, both_labeled=0) for cohort in sorted(set(cohorts.values()))}
    for key, cohort in cohorts.items():
        left, right = a[key], b[key]
        counts[cohort]['total'] += 1
        if left['status'] and right['status'] and left['reviewer'].strip().casefold() == right['reviewer'].strip().casefold():
            raise ValueError(f'two independent reviewer identities required: {key}')
        if not left['status'] or not right['status']:
            outcome = 'pending'
        elif left['status'] == 'unresolved' or right['status'] == 'unresolved':
            outcome = 'unresolved'
        else:
            counts[cohort]['both_labeled'] += 1
            outcome = 'consensus' if left['category'] == right['category'] else 'disagreement'
        counts[cohort][outcome] += 1
        record = dict(operation_id=key, cohort=cohort, outcome=outcome,
            reviewer_a=left['reviewer'], reviewer_b=right['reviewer'],
            category_a=left['category'], category_b=right['category'],
            rationale_a=left['rationale'], rationale_b=right['rationale'],
            evidence_ref_a=left['evidence_ref'], evidence_ref_b=right['evidence_ref'])
        if outcome == 'consensus':
            candidates.append(dict(record, category=left['category']))
        else:
            queue.append(record)
    for values in counts.values():
        values['agreement_among_both_labeled'] = values['consensus']/values['both_labeled'] if values['both_labeled'] else None
    return candidates, queue, counts


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=root/'cashflow_dataset_participants/all_operations.csv')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--reviewer-a', type=Path, required=True)
    parser.add_argument('--reviewer-b', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='new directory; refuses overwrite')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if hashlib.sha256(args.data.read_bytes()).hexdigest() != manifest['source_sha256']:
        raise ValueError('source dataset fingerprint differs from selection manifest')
    with args.data.open(encoding='utf-8-sig', newline='') as source:
        rows = list(csv.DictReader(source, delimiter=';'))
    originals = {row['operation_id']: row for row in rows}
    if len(originals) != len(rows):
        raise ValueError('source dataset has duplicate operation IDs')
    forms = [[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
             for path in (args.reviewer_a, args.reviewer_b)]
    candidates, queue, counts = reconcile(*forms, originals, manifest['cohorts'])
    args.out.mkdir(parents=True, exist_ok=False)
    for name, values in [('consensus_candidates', candidates), ('adjudication_queue', queue)]:
        (args.out/f'{name}.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in values))
    report = dict(cohorts=counts, consensus_candidates=len(candidates), unresolved_or_pending=len(queue),
        model_accuracy=None, source_sha256=manifest['source_sha256'],
        input_sha256={name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in
                      [('manifest', args.manifest), ('reviewer_a', args.reviewer_a), ('reviewer_b', args.reviewer_b)]},
        limitation='Matching entries do not establish reviewer independence or factual correctness. '
                   'No automatic gold label promotion; reconcile evidence and disagreements before use. '
                   'No model accuracy is computed; keep random and challenge cohorts separate.')
    (args.out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'consensus_candidates': len(candidates), 'unresolved_or_pending': len(queue)}))


if __name__ == '__main__':
    main()
