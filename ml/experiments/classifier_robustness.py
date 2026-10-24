"""Metamorphic checks of the saved classifier on the existing regression set.

These are transformations of already inspected synthetic examples, not new gold
labels. Counterparty removal is an ablation and may remove essential context.
"""
from dataclasses import replace
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
import pandas as pd
from zavozik_ml.classify.model import Classifier, DEFAULT_DIR
from zavozik_ml.classify.text import Op, normalize
from zavozik_ml.classify.evaluate import load_novel

root=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--artifact',type=Path,default=DEFAULT_DIR)
ap.add_argument('--out',type=Path,default=root/'reports/metrics/classifier_robustness.csv')
args=ap.parse_args()
model=Classifier.load(args.artifact)
df=load_novel()
ops=[Op(d,p,n,i,a) for d,p,n,i,a in zip(df.dir,df.payment_purpose,df.counterparty_name,df.counterparty_inn,df.amount)]
variants={
    'original':lambda o:o,
    'uppercase':lambda o:replace(o,purpose=o.purpose.upper(),counterparty_name=o.counterparty_name.upper()),
    'whitespace':lambda o:replace(o,purpose='  \t'+o.purpose.replace(' ','\u00a0\n ')),
    'vat_suffix':lambda o:replace(o,purpose=o.purpose+'. Без НДС.'),
    'digital_ruble_suffix':lambda o:replace(o,purpose=o.purpose+' в цифровых рублях'),
    'amount_x01':lambda o:replace(o,amount=o.amount*.1),
    'amount_x10':lambda o:replace(o,amount=o.amount*10),
    'without_counterparty':lambda o:replace(o,counterparty_name='',counterparty_inn=''),
}
base=model.predict(ops)
rows=[];detail=[]
for name,transform in variants.items():
    changed=[transform(o) for o in ops]
    preds=model.predict(changed)
    correct=np.array([p.category==y for p,y in zip(preds,df.category)])
    confident=np.array([p.confidence>=.8 for p in preds])
    same=np.array([p.category==b.category for p,b in zip(preds,base)])
    assigned=np.array([p.category!='other' for p in preds])&confident
    informative=np.array([bool(normalize(o.purpose)) for o in ops])
    rows.append(dict(variant=name,n=len(preds),accuracy=float(correct.mean()),unchanged_fraction=float(same.mean()),
        confident_errors=int((confident&~correct).sum()),accepted_fraction=float(confident.mean()),
        confident_non_other_errors=int((assigned&~correct).sum()),assigned_fraction=float(assigned.mean()),
        nonempty_purpose_accuracy=float(correct[informative].mean()),nonempty_purpose_n=int(informative.sum())))
    for r,p,b in zip(df.itertuples(index=False),preds,base):
        if p.category!=r.category or p.category!=b.category:
            detail.append(dict(variant=name,id=r.id,expected=r.category,prediction=p.category,confidence=p.confidence,base=b.category))
    if name in {'uppercase','whitespace'}:
        assert same.all(), f'{name} changed predictions'
        assert all(abs(p.confidence-b.confidence)<1e-7 for p,b in zip(preds,base)), name
out=args.out
out.parent.mkdir(parents=True,exist_ok=True)
pd.DataFrame(rows).to_csv(out,index=False)
pd.DataFrame(detail).to_csv(out.with_name(out.stem+'_errors.csv'),index=False)
metadata={'weights_sha256':hashlib.sha256((args.artifact/'weights.npz').read_bytes()).hexdigest(),
    'protocol':'metamorphic_regression_only','input':'zavozik_ml/classify/novel_test.csv',
    'limitation':'Already inspected synthetic cases. Counterparty removal may destroy information; amount perturbation is a stress check.'}
out.with_suffix('.json').write_text(json.dumps(metadata,indent=2))
print(pd.DataFrame(rows).to_string(index=False))
