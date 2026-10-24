"""Repeat company evaluation with weak counterparty labels isolated by split.

This is a correction of evaluation preprocessing, not a new independent test.
The final all-company artifact is left untouched by this experiment.
"""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
import pandas as pd
from zavozik_ml.classify import labels, evaluate
from zavozik_ml.classify.model import Classifier
from zavozik_ml.classify.train import real_rows, dev_set, train_model
from zavozik_ml.provenance import source_fingerprint

root=Path(__file__).resolve().parents[1]
repo=root.parent
out=root/'data/classifier_partition_labels'
out.mkdir(parents=True,exist_ok=True)
old_meta=json.loads((root/'data/classifier_evaluation/meta.json').read_text())
df=labels.load_dataset(repo/'cashflow_dataset_participants/all_operations.csv')
go=labels.go_rule_labels(repo/'cashflow_dataset_participants/all_operations.csv',repo,root/'data/rule_labels.csv')
original=labels.teacher_labels(df,go).set_index('operation_id')
parts={}
changes={}
for group in ['train','calibration','test']:
    ids=old_meta[group+'_companies']
    parts[group]=labels.teacher_labels(df[df.company_id.isin(ids)],go)
    p=parts[group]
    changed=p[p.label.to_numpy()!=original.label.loc[p.operation_id].to_numpy()]
    changes[group]=len(changed)
    print(group,len(p),'changed weak labels',len(changed),flush=True)
calibration=dev_set(real_rows(parts['calibration']),42,6000,name_dropout=0)
clf=train_model(real_rows(parts['train']),42,60000,1500,3e-6,dev_rows=calibration,name_dropout=0)
clf.meta.update(old_meta)
clf.meta['weak_label_scope']='partition_only'
clf.save(out)
clf=Classifier.load(out)
results=evaluate.evaluate_all(clf,parts['test'],real_rows(parts['test']),calibration,repo)

def serializable(value):
    if isinstance(value,pd.DataFrame): return value.to_dict(orient='records')
    if isinstance(value,dict): return {str(k):serializable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [serializable(v) for v in value]
    if isinstance(value,np.generic): return value.item()
    return value

results['protocol']={'weak_label_scope':'partition_only','changed_labels':changes,
    'source_sha256':source_fingerprint(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'limitation':'Correction of an already inspected synthetic holdout, not a new independent test.',
    'temperature':clf.temperature}
(out/'evaluation.json').write_text(json.dumps(serializable(results),ensure_ascii=False,indent=2))
results['novel']['df'].to_csv(out/'novel.csv',index=False)
print(json.dumps({k:results[k]['summary'] for k in ['holdout','novel']},indent=2),flush=True)
