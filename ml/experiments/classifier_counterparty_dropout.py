"""Development experiment: remove a shortcut from missing counterparty to other.

Fixed 25% additional dropout views; no search over the inspected regression set.
Weak labels and company splits are isolated. This is internal robustness work.
"""
from pathlib import Path
from dataclasses import replace
import hashlib
import json
import random
import numpy as np
import pandas as pd
from zavozik_ml.classify import train, labels, evaluate
from zavozik_ml.classify.model import Classifier
from zavozik_ml.classify.text import normalize, Op

root=Path(__file__).resolve().parents[1]
repo=root.parent
out=root/'data/classifier_counterparty_dropout'
out.mkdir(parents=True,exist_ok=True)
meta=json.loads((root/'data/classifier_evaluation/meta.json').read_text())
df=labels.load_dataset(repo/'cashflow_dataset_participants/all_operations.csv')
go=labels.go_rule_labels(repo/'cashflow_dataset_participants/all_operations.csv',repo,root/'data/rule_labels.csv')
parts={g:labels.teacher_labels(df[df.company_id.isin(meta[g+'_companies'])],go) for g in ['train','calibration','test']}
calibration=train.dev_set(train.real_rows(parts['calibration']),42,6000,name_dropout=.25)
clf=train.train_model(train.real_rows(parts['train']),42,60000,1500,3e-6,dev_rows=calibration,name_dropout=.25)
clf.meta.update(meta)
clf.meta.update(weak_label_scope='partition_only',counterparty_dropout=.25,evaluation_only=True)
clf.save(out)
clf=Classifier.load(out)
results=evaluate.evaluate_all(clf,parts['test'],train.real_rows(parts['test']),calibration,repo)
# Report the same ablation on both models, with nonempty purposes separately.
n=evaluate.load_novel()
ops=[Op(d,p,nm,i,a) for d,p,nm,i,a in zip(n.dir,n.payment_purpose,n.counterparty_name,n.counterparty_inn,n.amount)]
rows=[]
for model_name,model in [('partition_baseline',Classifier.load(root/'data/classifier_partition_labels')),('dropout',clf)]:
    for scenario,examples in [('original',ops),('without_counterparty',[replace(o,counterparty_name='',counterparty_inn='') for o in ops])]:
        pred=model.predict(examples)
        correct=np.array([p.category==y for p,y in zip(pred,n.category)])
        informative=np.array([bool(normalize(o.purpose)) for o in ops])
        assigned=np.array([p.category!='other' and p.confidence>=.8 for p in pred])
        rows.append(dict(model=model_name,scenario=scenario,n=len(pred),accuracy=float(correct.mean()),
            nonempty_purpose_accuracy=float(correct[informative].mean()),nonempty_purpose_n=int(informative.sum()),
            confident_non_other_errors=int((assigned&~correct).sum()),assigned_fraction=float(assigned.mean())))

def cast(v):
    if isinstance(v,pd.DataFrame):return v.to_dict(orient='records')
    if isinstance(v,dict):return {str(k):cast(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [cast(x) for x in v]
    if isinstance(v,np.generic):return v.item()
    return v
results['protocol']={'dropout_fraction':.25,'weak_label_scope':'partition_only','script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'limitation':'Fixed-recipe robustness experiment after inspected synthetic holdout. Not an independent external test.'}
(out/'evaluation.json').write_text(json.dumps(cast(results),ensure_ascii=False,indent=2))
pd.DataFrame(rows).to_csv(out/'robustness.csv',index=False)
print(pd.DataFrame(rows).to_string(index=False),flush=True)
