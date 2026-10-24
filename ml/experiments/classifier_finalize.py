"""Fit the fixed dropout recipe on all companies without repeating evaluation.

Writes a candidate artifact and report under ignored data/, not into serving.
Company holdout results come from classifier_counterparty_dropout.py.
"""
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,time
import pandas as pd
from zavozik_ml.classify import train, labels, evaluate
from zavozik_ml.classify.model import Classifier
from zavozik_ml.provenance import source_fingerprint

root=Path(__file__).resolve().parents[1]
repo=root.parent
source=repo/'cashflow_dataset_participants/all_operations.csv'
eval_dir=root/'data/classifier_counterparty_dropout'
meta=json.loads((eval_dir/'meta.json').read_text())
results=json.loads((eval_dir/'evaluation.json').read_text())
assert meta['weak_label_scope']=='partition_only' and meta['counterparty_dropout']==.25
results['novel']['df']=pd.DataFrame(results['novel']['df'])
df=labels.teacher_labels(labels.load_dataset(source),labels.go_rule_labels(source,repo,root/'data/rule_labels.csv'))
final=train.train_model(train.real_rows(df),42,60000,1500,3e-6,name_dropout=.25)
final.temperature=meta['temperature']
final.meta=dict(trained_at=time.strftime('%Y-%m-%d'),n_operations=len(df),l2=3e-6,perturb=60000,synth=1500,seed=42,name_dropout=.25,
    holdout_eval={k:results[k]['summary'] for k in ['holdout','novel']},
    calibration_companies=meta['calibration_companies'],test_companies=meta['test_companies'],
    evaluation_protocol='company_train_calibration_test_60_20_20',
    weak_label_scope='partition_only_for_evaluation_all_companies_for_final_fit',
    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),training_code_sha256=source_fingerprint(),
    novel_usage='regression_set_previously_inspected_not_external_test')
out=root/'data/classifier_candidate_final'
final.save(out)
results['final_novel']=evaluate.novel(Classifier.load(out),repo)
evaluate.write_report(results,SimpleNamespace(holdout=.2,min_confidence=.3),root/'data/classifier_candidate_final.md')
results['final_novel']['df'].to_csv(out/'novel.csv',index=False)
print('final regression',results['final_novel']['summary'],flush=True)
